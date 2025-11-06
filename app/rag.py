# app/rag.py
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors.base import DocumentCompressorPipeline
from langchain_community.document_transformers import EmbeddingsRedundantFilter
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_postgres.v2.async_vectorstore import AsyncPGVectorStore
from langchain_postgres.v2.engine import PGEngine
from langchain_classic.retrievers import ParentDocumentRetriever
from langchain_classic.storage import InMemoryStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text

import config
from database import async_engine, AsyncSessionLocal, redis_client
from llm_services import embeddings_model, reranker
from outline_client import outline_list_docs, outline_get_doc

logger = logging.getLogger(__name__)

# 延迟初始化 LangChain 组件
vector_store: Optional[AsyncPGVectorStore] = None
# (新) Req 4: 为父文档创建 docstore
parent_store: Optional[InMemoryStore] = None
base_retriever: Optional[BaseRetriever] = None
compression_retriever: Optional[ContextualCompressionRetriever] = None

# 使用 asyncio.Lock
_rag_lock = asyncio.Lock()


async def initialize_rag_components():
    global vector_store, base_retriever, compression_retriever, parent_store
    if vector_store:
        return

    async with _rag_lock:
        if vector_store:
            return

        logger.info("Initializing RAG components (AsyncEngine, PGVectorStore v2)...")

        if not async_engine:
            raise ValueError("AsyncEngine from database.py is not available")

        # (新) Req 4: 初始化 InMemoryStore
        parent_store = InMemoryStore()

        # 创建 v2 API 需要的 PGEngine 包装器
        pg_engine_wrapper = PGEngine.from_engine(async_engine)

        # 初始化 PGVector 存储
        try:
            vector_store = await AsyncPGVectorStore.create(
                engine=pg_engine_wrapper,
                embedding_service=embeddings_model,
                table_name="langchain_pg_embedding",
            )
            logger.info("AsyncPGVectorStore (v2) initialized.")
        except Exception as e:
            logger.critical(f"Failed to initialize PGVectorStore: {e}", exc_info=True)
            raise

        # (新) Req 4: 初始化基础检索器为 ParentDocumentRetriever
        # child_splitter (text_splitter) 将用于在 .add_documents 期间即时创建子块
        # id_key="source_id" 告诉 PDR 如何在 docstore 中查找父文档
        base_retriever = ParentDocumentRetriever(
            vectorstore=vector_store,
            docstore=parent_store,
            child_splitter=text_splitter, # text_splitter (1000/200) 现在是子块分割器
            id_key="source_id" # 确保元数据中的 source_id 用于 docstore 查找
        )
        logger.info("Base retriever configured (ParentDocumentRetriever).")


        # 初始化压缩/重排检索器
        pipeline_compressor = DocumentCompressorPipeline(
            transformers=[
                EmbeddingsRedundantFilter(embeddings=embeddings_model),
                reranker # (我们异步感知的 reranker)
            ]
        )

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=pipeline_compressor,
            base_retriever=base_retriever
        )

        logger.info("RAG components initialization complete.")


# 初始化文本分割器
# (新) Req 4: 这个分割器现在是 ParentDocumentRetriever 的 'child_splitter'
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""],
)

# 数据库同步任务

async def process_doc_batch_task(doc_ids: list):
    """
    异步处理文档批次
    """
    await initialize_rag_components()

    # (新) Req 4: 确保 parent_store 和 vector_store 都已初始化
    if not vector_store or not parent_store:
        logger.critical("Vector store 或 Parent store 未在 process_doc_batch_task 中初始化！")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

    if not doc_ids:
        return

    docs_to_process_lc = []
    successful_ids = set()
    skipped_ids = set()

    for doc_id in doc_ids:
        info = await outline_get_doc(doc_id)
        if not info:
            logger.warning(f"无法获取文档 {doc_id} 的内容，跳过。")
            skipped_ids.add(doc_id)
            continue

        content = info.get("text") or ""
        if not content.strip():
            skipped_ids.add(doc_id)
            continue

        updated_at_str = info.get("updatedAt")
        if not updated_at_str:
            now_dt = datetime.now(timezone.utc)
            updated_at_str = now_dt.isoformat().replace('+00:00', 'Z')

        # (新) Req 5: 将 'url' 添加到元数据中以便溯源
        doc = Document(
            page_content=content,
            metadata={
                "source_id": doc_id,
                "title": info.get("title") or "",
                "outline_updated_at_str": updated_at_str,
                "url": info.get("url") # 假设 info 字典中有 'url' 键
            }
        )
        docs_to_process_lc.append(doc)
        successful_ids.add(doc_id)

    if docs_to_process_lc:
        # (新) Req 4: ParentDocumentRetriever 需要我们手动删除旧块

        # 1. (不变) 手动删除 PGVector 中的旧子块
        chunks = text_splitter.split_documents(docs_to_process_lc)

        if chunks:
            logger.info(f"正在为 {len(successful_ids)} 篇文档处理 {len(chunks)} 个分块...")

            ids_to_delete = []
            try:
                async with AsyncSessionLocal.begin() as session:
                    ids_to_delete_rows = (await session.execute(
                        text("""
                             SELECT langchain_id FROM langchain_pg_embedding
                             WHERE (cmetadata ->> 'source_id') = ANY(:source_ids)
                             """),
                        {"source_ids": list(successful_ids)}
                    )).fetchall()
                    ids_to_delete = [row[0] for row in ids_to_delete_rows]
            except Exception as e:
                logger.error(f"查询旧分块 UUIDs 时出错 (async): {e}，将跳过删除，尝试直接 Upsert。")
                ids_to_delete = []

            if ids_to_delete:
                logger.info(f"正在从 PGVectorStore 删除 {len(ids_to_delete)} 个与 {len(successful_ids)} 篇文档关联的旧分块...")
                try:
                    await vector_store.adelete(ids=ids_to_delete)
                except Exception as e:
                    logger.error(f"调用 vector_store.adelete (async) 删除 chunks: {ids_to_delete} 时失败: {e}。继续尝试添加...")

            # 2. (新) Req 4: 使用 base_retriever (PDR) 添加文档
            # PDR 的 .add_documents 会自动:
            # a) 将父文档 (docs_to_process_lc) 存入 docstore (parent_store)
            # b) 使用 child_splitter (text_splitter) 分割父文档
            # c) 将子块 (chunks) 存入 vectorstore (vector_store)
            try:
                # (新) Req 4: 我们不再直接调用 vector_store.aadd_documents
                # 我们调用 PDR 的 add_documents
                # 注意：PDR 尚不支持 'aadd_documents'，我们必须使用同步的 'add_documents'
                # base_retriever.add_documents(docs_to_process_lc, ids=list(successful_ids), add_to_docstore=True)

                # --- 修正 ---
                # PDR 的 add_documents 接口是同步的，且在异步环境中运行它很棘手。
                # PDR 的逻辑是：
                # 1. add_documents -> docstore.mset(parents)
                # 2. add_documents -> child_splitter.split(parents)
                # 3. add_documents -> vectorstore.add_documents(children)
                # 我们可以异步地手动执行此操作：

                # 2a. (新) Req 4: 将父文档存入 docstore
                # 我们使用 source_id 作为键
                parent_docs_tuples = [(doc.metadata["source_id"], doc) for doc in docs_to_process_lc]
                await parent_store.amset(parent_docs_tuples)

                # 2b. (不变) 将子块存入 vectorstore
                # chunks 已经从 text_splitter.split_documents(docs_to_process_lc) 中获得
                await vector_store.aadd_documents(chunks)

            except Exception as e:
                logger.error(f"调用 PDR (async) 添加 {len(chunks)} 个 chunks 和 {len(docs_to_process_lc)} 个父文档时失败: {e}。")


    if redis_client:
        try:
            p = redis_client.pipeline()
            if successful_ids:
                p.incrby("refresh:success_count", len(successful_ids))
            if skipped_ids:
                p.incrby("refresh:skipped_count", len(skipped_ids))
            await p.execute()
        except Exception as e:
            logger.error("更新Redis刷新计数器时出错 (async): %s", e)

    logger.info(f"批处理任务完成 (async): 成功处理 {len(successful_ids)} 篇, 跳过 {len(skipped_ids)} 篇。")


async def refresh_all_task():
    """异步优雅刷新任务"""
    await initialize_rag_components()

    try:
        remote_docs_raw = await outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("无法从 Outline API 获取文档列表。")

        remote_docs_map = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        local_docs_map = {}
        try:
            # (新) Req 4: 我们现在需要检查 parent_store (InMemoryStore)
            # 但 PDR 依赖 vector_store 中的元数据，所以我们继续查询 pg_embedding
            async with AsyncSessionLocal.begin() as session:
                local_docs_raw = (await session.execute(
                    text("""
                         SELECT DISTINCT ON ((cmetadata ->> 'source_id'))
                             (cmetadata ->> 'source_id') as id,
                             (cmetadata ->> 'outline_updated_at_str') as outline_updated_at_str
                         FROM langchain_pg_embedding
                         WHERE (cmetadata ->> 'source_id') IS NOT NULL
                         """)
                )).mappings().all()
                local_docs_map = {doc['id']: doc['outline_updated_at_str'] for doc in local_docs_raw if doc.get('id') and doc.get('outline_updated_at_str')}
        except Exception as e:
            logger.error(f"从 PGVectorStore 读取元数据失败 (async): {e}")

        remote_ids = set(remote_docs_map.keys())
        local_ids = set(local_docs_map.keys())

        to_add_ids = list(remote_ids - local_ids)
        to_delete_ids = list(local_ids - remote_ids)
        to_check_ids = remote_ids.intersection(local_ids)
        to_update_ids = [doc_id for doc_id in to_check_ids if remote_docs_map[doc_id] != local_docs_map.get(doc_id)]

        if to_delete_ids:
            logger.warning(f"发现 {len(to_delete_ids)} 篇在本地存在但在远程不存在的文档，将被删除。")
            for doc_id in to_delete_ids:
                await delete_doc(doc_id) # delete_doc 现在也会从 parent_store 中删除

        docs_to_process_ids = to_add_ids + to_update_ids
        if not docs_to_process_ids:
            final_message = f"刷新完成。删除了 {len(to_delete_ids)} 篇陈旧文档。" if to_delete_ids else "刷新完成，数据已是最新。"
            if redis_client:
                status = {"status": "success", "message": final_message}
                await redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        if redis_client:
            try:
                p = redis_client.pipeline()
                p.set("refresh:total_queued", len(docs_to_process_ids))
                p.set("refresh:success_count", 0)
                p.set("refresh:skipped_count", 0)
                p.set("refresh:delete_count", len(to_delete_ids))
                p.delete("refresh:status")
                await p.execute()
            except Exception as e:
                logger.error("初始化Redis刷新计数器时出错 (async): %s", e)

        batch_size = config.REFRESH_BATCH_SIZE
        num_batches = (len(docs_to_process_ids) + batch_size - 1) // batch_size
        logger.info(f"共有 {len(docs_to_process_ids)} 个文档需要新增/更新，将分 {num_batches} 批处理。")

        for i in range(0, len(docs_to_process_ids), batch_size):
            batch = docs_to_process_ids[i:i+batch_size]
            task = {"task": "process_doc_batch", "doc_ids": batch}
            await redis_client.lpush("task_queue", json.dumps(task))

        logger.info(f"已将 {len(docs_to_process_ids)} 个文档的新增/更新任务加入处理队列。")

    except Exception as e:
        logger.exception("refresh_all_task (async) failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            await redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        if redis_client and not (await redis_client.exists("refresh:total_queued")):
            await redis_client.delete("refresh:lock")

async def delete_doc(doc_id):
    """从 PGVectorStore 和 ParentStore 中异步删除文档"""
    await initialize_rag_components()

    # (新) Req 4: 确保 parent_store 和 vector_store 都已初始化
    if not vector_store or not parent_store:
        logger.critical("Vector store 或 Parent store 未在 delete_doc 中初始化！")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

    # 1. (不变) 从 PGVector 删除子块
    ids_to_delete = []
    try:
        async with AsyncSessionLocal.begin() as session:
            ids_to_delete_rows = (await session.execute(
                text("""
                     SELECT langchain_id FROM langchain_pg_embedding
                     WHERE (cmetadata ->> 'source_id') = :source_id
                     """),
                {"source_id": doc_id}
            )).fetchall()
            ids_to_delete = [row[0] for row in ids_to_delete_rows]
    except Exception as e:
        logger.error(f"查询 {doc_id} 的旧分块 UUIDs 时出错 (async): {e}")
        return

    if ids_to_delete:
        try:
            await vector_store.adelete(ids=ids_to_delete)
            logger.info("已从 PGVectorStore 删除文档: %s (共 %d 个分块)", doc_id, len(ids_to_delete))
        except Exception as e:
            logger.error(f"调用 vector_store.adelete (async) 删除 {doc_id} (chunks: {ids_to_delete}) 时失败: {e}")
    else:
        logger.info("在 PGVectorStore 中未找到要删除的文档: %s", doc_id)

    # 2. (新) Req 4: 从 InMemoryStore 删除父文档
    try:
        await parent_store.amdelete([doc_id])
        logger.info("已从 ParentStore (InMemory) 删除文档: %s", doc_id)
    except Exception as e:
        logger.error(f"调用 parent_store.amdelete (async) 删除 {doc_id} 时失败: {e}")