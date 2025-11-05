# app/rag.py
import asyncio
import json
import logging
from datetime import datetime, timezone
# (*** 新增 ***) 导入类型提示
from typing import Optional

from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors.base import DocumentCompressorPipeline
from langchain_community.document_transformers import EmbeddingsRedundantFilter
from langchain_core.documents import Document
# (*** 新增 ***) 导入 BaseRetriever 类型
from langchain_core.retrievers import BaseRetriever
from langchain_postgres import PGVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text

import config
# 导入异步 engine, session, 和 redis
from database import async_engine, AsyncSessionLocal, redis_client
from llm_services import embeddings_model, reranker
# (ASYNC REFACTOR)
from outline_client import outline_list_docs, outline_get_doc

logger = logging.getLogger(__name__)

# --- (*** 修改 ***) ---
# 1. 延迟初始化 LangChain 组件
# 将所有需要I/O的组件在全局设为 None
# 它们将在 initialize_rag_components() 中被真正初始化

# 删除了此文件中的 async_engine 定义，我们将使用 database.py 中的
vector_store: Optional[PGVectorStore] = None
base_retriever: Optional[BaseRetriever] = None
compression_retriever: Optional[ContextualCompressionRetriever] = None

# (*** 新增 ***)
# 使用 asyncio.Lock
_rag_lock = asyncio.Lock()


# (*** 新增 ***)
# 转换为 async def
async def initialize_rag_components():
    """
    延迟初始化 RAG 组件。
    """
    global vector_store, base_retriever, compression_retriever

    if vector_store:
        return

    # (ASYNC REFACTOR)
    async with _rag_lock:
        if vector_store:
            return

        logger.info("Initializing RAG components (AsyncEngine, PGVectorStore)...")

        # --- 1a. (已移除) AsyncEngine 现在从 database.py 导入
        if not async_engine:
            raise ValueError("AsyncEngine from database.py is not available")

        # --- 1b. 初始化 PGVector 存储 ---
        # (*** 这是对 Error 1 的核心修复 ***)
        try:
            # 使用 await .create() 而不是 .create_sync()
            vector_store = await PGVectorStore.create(
                async_engine,
                table_name="outline_rag_collection",
                embedding_service=embeddings_model,
            )
            logger.info("PGVectorStore initialized (async).")
        except Exception as e:
            logger.critical(f"Failed to initialize PGVectorStore (async): {e}", exc_info=True)
            raise

        # --- 1c. 初始化基础检索器 ---
        base_retriever = vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": config.TOP_K}
        )

        # --- 1d. 初始化压缩/重排检索器 ---
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


# 1e. 初始化文本分割器 (不变)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""],
)

# --- 2. 数据库同步任务 ---

async def process_doc_batch_task(doc_ids: list):
    """
    异步处理文档批次
    """
    # (ASYNC REFACTOR)
    await initialize_rag_components()

    # (*** 新增 ***) 修复 Linter 警告
    # 添加此断言以向静态分析器证明 vector_store 不是 None
    if not vector_store:
        logger.critical("Vector store 未在 process_doc_batch_task 中初始化！")
        raise RuntimeError("RAG components (vector_store) not initialized")
    # (*** 修复结束 ***)

    if not doc_ids:
        return

    docs_to_process_lc = []
    successful_ids = set()
    skipped_ids = set()

    for doc_id in doc_ids:
        # (ASYNC REFACTOR)
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

        doc = Document(
            page_content=content,
            metadata={
                "source_id": doc_id,
                "title": info.get("title") or "",
                "outline_updated_at_str": updated_at_str,
            }
        )
        docs_to_process_lc.append(doc)
        successful_ids.add(doc_id)

    if docs_to_process_lc:
        chunks = text_splitter.split_documents(docs_to_process_lc)

        if chunks:
            logger.info(f"正在为 {len(successful_ids)} 篇文档处理 {len(chunks)} 个分块...")

            ids_to_delete = []
            try:
                # (ASYNC REFACTOR)
                async with AsyncSessionLocal.begin() as session:
                    coll_id_row = (await session.execute(text("SELECT uuid FROM langchain_pg_collection WHERE name = :coll_name"), {"coll_name": "outline_rag_collection"})).first()
                    coll_id = coll_id_row[0] if coll_id_row else None

                    if coll_id:
                        ids_to_delete_rows = (await session.execute(
                            text("""
                                 SELECT uuid FROM langchain_pg_embedding
                                 WHERE collection_id = :coll_id AND (cmetadata ->> 'source_id') = ANY(:source_ids)
                                 """),
                            {"coll_id": coll_id, "source_ids": list(successful_ids)}
                        )).fetchall()
                        ids_to_delete = [row[0] for row in ids_to_delete_rows]
            except Exception as e:
                logger.error(f"查询旧分块 UUIDs 时出错 (async): {e}，将跳过删除，尝试直接 Upsert。")
                ids_to_delete = []

            if ids_to_delete:
                logger.info(f"正在从 PGVectorStore 删除 {len(ids_to_delete)} 个与 {len(successful_ids)} 篇文档关联的旧分块...")
                try:
                    # (ASYNC REFACTOR)
                    # Linter 现在知道 vector_store 不是 None
                    await vector_store.adelete(ids=ids_to_delete)
                except Exception as e:
                    logger.error(f"调用 vector_store.adelete (async) 删除 chunks: {ids_to_delete} 时失败: {e}。继续尝试添加...")

            try:
                # (ASYNC REFACTOR)
                # Linter 现在知道 vector_store 不是 None
                await vector_store.aadd_documents(chunks)
            except Exception as e:
                logger.error(f"调用 vector_store.aadd_documents (async) 添加 {len(chunks)} 个 chunks 时失败: {e}。")


    if redis_client:
        try:
            # (ASYNC REFACTOR)
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
    # (ASYNC REFACTOR)
    await initialize_rag_components()

    try:
        # (ASYNC REFACTOR)
        remote_docs_raw = await outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("无法从 Outline API 获取文档列表。")

        remote_docs_map = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        local_docs_map = {}
        try:
            # (ASYNC REFACTOR)
            async with AsyncSessionLocal.begin() as session:
                coll_id_row = (await session.execute(text("SELECT uuid FROM langchain_pg_collection WHERE name = :coll_name"), {"coll_name": "outline_rag_collection"})).first()
                coll_id = coll_id_row[0] if coll_id_row else None

                if coll_id:
                    local_docs_raw = (await session.execute(
                        text("""
                             SELECT DISTINCT ON ((cmetadata ->> 'source_id'))
                                 (cmetadata ->> 'source_id') as id,
                                 (cmetadata ->> 'outline_updated_at_str') as outline_updated_at_str
                             FROM langchain_pg_embedding
                             WHERE collection_id = :coll_id AND (cmetadata ->> 'source_id') IS NOT NULL
                             """),
                        {"coll_id": coll_id}
                    )).mappings().all()
                    local_docs_map = {doc['id']: doc['outline_updated_at_str'] for doc in local_docs_raw if doc.get('id') and doc.get('outline_updated_at_str')}
                else:
                    logger.info("未找到 PGVectorStore 集合，假定本地为空。")
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
                # (ASYNC REFACTOR)
                await delete_doc(doc_id)

        docs_to_process_ids = to_add_ids + to_update_ids
        if not docs_to_process_ids:
            final_message = f"刷新完成。删除了 {len(to_delete_ids)} 篇陈旧文档。" if to_delete_ids else "刷新完成，数据已是最新。"
            if redis_client:
                status = {"status": "success", "message": final_message}
                # (ASYNC REFACTOR)
                await redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        if redis_client:
            try:
                # (ASYNC REFACTOR)
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
            # (ASYNC REFACTOR)
            await redis_client.lpush("task_queue", json.dumps(task))

        logger.info(f"已将 {len(docs_to_process_ids)} 个文档的新增/更新任务加入处理队列。")

    except Exception as e:
        logger.exception("refresh_all_task (async) failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            # (ASYNC REFACTOR)
            await redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        if redis_client and not (await redis_client.exists("refresh:total_queued")):
            # (ASYNC REFACTOR)
            await redis_client.delete("refresh:lock")

async def delete_doc(doc_id):
    """从 PGVectorStore 中异步删除文档"""
    # (ASYNC REFACTOR)
    await initialize_rag_components()

    # (*** 新增 ***) 修复 Linter 警告
    # 添加此断言以向静态分析器证明 vector_store 不是 None
    if not vector_store:
        logger.critical("Vector store 未在 delete_doc 中初始化！")
        raise RuntimeError("RAG components (vector_store) not initialized")
    # (*** 修复结束 ***)

    ids_to_delete = []
    try:
        # (ASYNC REFACTOR)
        async with AsyncSessionLocal.begin() as session:
            coll_id_row = (await session.execute(text("SELECT uuid FROM langchain_pg_collection WHERE name = :coll_name"), {"coll_name": "outline_rag_collection"})).first()
            if not coll_id_row:
                logger.warning(f"删除 {doc_id} 失败：未找到集合。")
                return

            coll_id = coll_id_row[0]

            ids_to_delete_rows = (await session.execute(
                text("""
                     SELECT uuid FROM langchain_pg_embedding
                     WHERE collection_id = :coll_id AND (cmetadata ->> 'source_id') = :source_id
                     """),
                {"coll_id": coll_id, "source_id": doc_id}
            )).fetchall()
            ids_to_delete = [row[0] for row in ids_to_delete_rows]
    except Exception as e:
        logger.error(f"查询 {doc_id} 的旧分块 UUIDs 时出错 (async): {e}")
        return

    if ids_to_delete:
        try:
            # (ASYNC REFACTOR)
            # Linter 现在知道 vector_store 不是 None
            await vector_store.adelete(ids=ids_to_delete)
            logger.info("已从 PGVectorStore 删除文档: %s (共 %d 个分块)", doc_id, len(ids_to_delete))
        except Exception as e:
            logger.error(f"调用 vector_store.adelete (async) 删除 {doc_id} (chunks: {ids_to_delete}) 时失败: {e}")
    else:
        logger.info("在 PGVectorStore 中未找到要删除的文档: %s", doc_id)