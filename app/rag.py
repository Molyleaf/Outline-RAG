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
from langchain_community.storage import RedisStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text

import config
from database import async_engine, AsyncSessionLocal, redis_client
from llm_services import embeddings_model, reranker
from outline_client import outline_list_docs, outline_get_doc

logger = logging.getLogger(__name__)

# LangChain 组件将按需延迟初始化
vector_store: Optional[AsyncPGVectorStore] = None
# 修复：ParentDocumentRetriever 的 docstore 将使用持久化的 RedisStore
parent_store: Optional[RedisStore] = None
base_retriever: Optional[BaseRetriever] = None
compression_retriever: Optional[ContextualCompressionRetriever] = None

# 确保 RAG 组件在多进程环境中只初始化一次的锁
_rag_lock = asyncio.Lock()


async def initialize_rag_components():
    """
    异步初始化所有 RAG 相关的 LangChain 组件。
    使用锁来确保在并发请求下只执行一次。
    """
    global vector_store, base_retriever, compression_retriever, parent_store

    # 如果已初始化，则快速返回
    if vector_store:
        return

    # 异步锁，防止并发初始化
    async with _rag_lock:
        # 再次检查，可能在等待锁时另一个协程已完成初始化
        if vector_store:
            return

        logger.info("Initializing RAG components (AsyncEngine, PGVectorStore v2, RedisStore)...")

        if not async_engine:
            raise ValueError("AsyncEngine from database.py is not available")

        # 修复：为 ParentStore (docstore) 初始化 RedisStore
        # 我们使用 database.py 中定义的共享的 *异步* redis_client
        if not redis_client:
            raise ValueError("Redis (async_client) from database.py is not available, but is required for ParentStore")

        parent_store = RedisStore(
            client=redis_client,
            namespace="rag:parent_store" # 使用专用命名空间
        )
        logger.info("ParentStore configured (RedisStore).")

        # 初始化 PGVectorStore (子块存储)
        pg_engine_wrapper = PGEngine.from_engine(async_engine)
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

        # 初始化基础检索器 (ParentDocumentRetriever)
        # 它使用 vector_store 检索子块，并使用 parent_store (Redis) 查找父文档
        base_retriever = ParentDocumentRetriever(
            vectorstore=vector_store,
            docstore=parent_store,
            child_splitter=text_splitter, # text_splitter 用于即时分割
            id_key="source_id" # 使用 'source_id' 作为父文档的键
        )
        logger.info("Base retriever configured (ParentDocumentRetriever).")

        # 初始化压缩/重排管线
        pipeline_compressor = DocumentCompressorPipeline(
            transformers=[
                EmbeddingsRedundantFilter(embeddings=embeddings_model),
                reranker # 异步 Reranker
            ]
        )

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=pipeline_compressor,
            base_retriever=base_retriever
        )

        logger.info("RAG components initialization complete.")


# 这个分割器将由 ParentDocumentRetriever 在索引时用于创建子块
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""],
)

# --- 数据库同步任务 ---

async def process_doc_batch_task(doc_ids: list):
    """
    异步处理一个批次的文档 ID，从 Outline 获取内容，
    并将其存入 ParentStore (Redis) 和 VectorStore (Postgres)。
    """
    await initialize_rag_components()

    if not vector_store or not parent_store:
        logger.critical("Vector store or Parent store not initialized in process_doc_batch_task!")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

    if not doc_ids:
        return

    docs_to_process_lc = []
    successful_ids = set()
    skipped_ids = set()

    # 1. 从 Outline API 批量获取文档内容
    for doc_id in doc_ids:
        info = await outline_get_doc(doc_id)
        if not info:
            logger.warning(f"Failed to get content for doc {doc_id}, skipping.")
            skipped_ids.add(doc_id)
            continue

        content = info.get("text") or ""
        if not content.strip():
            logger.info(f"Document {doc_id} is empty, skipping.")
            skipped_ids.add(doc_id)
            continue

        updated_at_str = info.get("updatedAt")
        if not updated_at_str:
            now_dt = datetime.now(timezone.utc)
            updated_at_str = now_dt.isoformat().replace('+00:00', 'Z')

        # 构建 LangChain Document 对象
        doc = Document(
            page_content=content,
            metadata={
                "source_id": doc_id, # PDR 将使用此 ID 作为 docstore 键
                "title": info.get("title") or "",
                "outline_updated_at_str": updated_at_str,
                "url": info.get("url") # 用于 RAG 溯源
            }
        )
        docs_to_process_lc.append(doc)
        successful_ids.add(doc_id)

    if docs_to_process_lc:
        # 2. 将父文档分割为子块
        chunks = text_splitter.split_documents(docs_to_process_lc)

        if chunks:
            logger.info(f"Processing {len(chunks)} chunks for {len(successful_ids)} documents...")

            # 3. 手动从 PGVector 删除旧的子块
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
                logger.error(f"Failed to query old chunk UUIDs (async): {e}. Skipping delete.", exc_info=True)
                ids_to_delete = []

            if ids_to_delete:
                logger.info(f"Deleting {len(ids_to_delete)} old chunks from PGVectorStore for {len(successful_ids)} docs...")
                try:
                    await vector_store.adelete(ids=ids_to_delete)
                except Exception as e:
                    logger.error(f"vector_store.adelete (async) failed for chunks {ids_to_delete}: {e}. Continuing...", exc_info=True)

            # 4. 异步手动执行 ParentDocumentRetriever 的索引逻辑
            try:
                # 4a. 将父文档存入 RedisStore
                parent_docs_tuples = [(doc.metadata["source_id"], doc) for doc in docs_to_process_lc]
                await parent_store.amset(parent_docs_tuples)

                # 4b. 将新的子块存入 PGVectorStore
                await vector_store.aadd_documents(chunks)

            except Exception as e:
                logger.error(f"Failed (async) to add {len(chunks)} chunks or {len(docs_to_process_lc)} parent docs: {e}.", exc_info=True)

    # 5. 更新 Redis 中的任务计数器
    if redis_client:
        try:
            p = redis_client.pipeline()
            if successful_ids:
                p.incrby("refresh:success_count", len(successful_ids))
            if skipped_ids:
                p.incrby("refresh:skipped_count", len(skipped_ids))
            await p.execute()
        except Exception as e:
            logger.error("Failed to update Redis refresh counters (async): %s", e)

    logger.info(f"Batch task complete (async): {len(successful_ids)} processed, {len(skipped_ids)} skipped.")


async def refresh_all_task():
    """
    执行 RAG 优雅刷新。
    比较 Outline API 和本地存储，以确定要添加、更新或删除的文档。
    """
    await initialize_rag_components()

    try:
        # 1. 获取远程所有文档的元数据
        remote_docs_raw = await outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("Failed to retrieve document list from Outline API.")

        remote_docs_map = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        # 2. 获取本地所有文档的元数据 (通过查询子块的元数据)
        local_docs_map = {}
        try:
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
            logger.error(f"Failed to read metadata from PGVectorStore (async): {e}", exc_info=True)

        # 3. 计算差异
        remote_ids = set(remote_docs_map.keys())
        local_ids = set(local_docs_map.keys())

        to_add_ids = list(remote_ids - local_ids)
        to_delete_ids = list(local_ids - remote_ids)
        to_check_ids = remote_ids.intersection(local_ids)

        # 如果远程更新时间与本地存储的更新时间不同，则更新
        to_update_ids = [doc_id for doc_id in to_check_ids if remote_docs_map[doc_id] != local_docs_map.get(doc_id)]

        # 4. 执行删除
        if to_delete_ids:
            logger.warning(f"Found {len(to_delete_ids)} docs locally that are not remote. Deleting...")
            for doc_id in to_delete_ids:
                await delete_doc(doc_id) # delete_doc 会同时清理 vector 和 parent store

        # 5. 检查是否需要处理
        docs_to_process_ids = to_add_ids + to_update_ids
        if not docs_to_process_ids:
            final_message = f"Refresh complete. Removed {len(to_delete_ids)} old docs." if to_delete_ids else "Refresh complete. Data is up to date."
            logger.info(final_message)
            if redis_client:
                status = {"status": "success", "message": final_message}
                await redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        # 6. 初始化 Redis 任务计数器
        if redis_client:
            try:
                p = redis_client.pipeline()
                p.set("refresh:total_queued", len(docs_to_process_ids))
                p.set("refresh:success_count", 0)
                p.set("refresh:skipped_count", 0)
                p.set("refresh:delete_count", len(to_delete_ids))
                p.delete("refresh:status") # 清除旧的 "success" 状态
                await p.execute()
            except Exception as e:
                logger.error("Failed to initialize Redis refresh counters (async): %s", e)

        # 7. 将要处理的 ID 分批推送到任务队列
        batch_size = config.REFRESH_BATCH_SIZE
        num_batches = (len(docs_to_process_ids) + batch_size - 1) // batch_size
        logger.info(f"{len(docs_to_process_ids)} docs need update/add, splitting into {num_batches} batches.")

        for i in range(0, len(docs_to_process_ids), batch_size):
            batch = docs_to_process_ids[i:i+batch_size]
            task = {"task": "process_doc_batch", "doc_ids": batch}
            await redis_client.lpush("task_queue", json.dumps(task))

        logger.info(f"Queued {len(docs_to_process_ids)} doc processing tasks.")

    except Exception as e:
        logger.exception("refresh_all_task (async) failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"Refresh failed: {e}"}
            await redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        # 确保在任务完成后（即使是空的）释放锁
        if redis_client and not (await redis_client.exists("refresh:total_queued")):
            await redis_client.delete("refresh:lock")


async def delete_doc(doc_id):
    """
    从 PGVectorStore (子块) 和 RedisStore (父文档) 中异步删除一个文档。
    """
    await initialize_rag_components()

    if not vector_store or not parent_store:
        logger.critical("Vector store or Parent store not initialized in delete_doc!")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

    # 1. 从 PGVector (Postgres) 删除子块
    ids_to_delete = []
    try:
        async with AsyncSessionLocal.begin() as session:
            # 查找所有与该 source_id 关联的子块的 UUID
            ids_to_delete_rows = (await session.execute(
                text("""
                     SELECT langchain_id FROM langchain_pg_embedding
                     WHERE (cmetadata ->> 'source_id') = :source_id
                     """),
                {"source_id": doc_id}
            )).fetchall()
            ids_to_delete = [row[0] for row in ids_to_delete_rows]
    except Exception as e:
        logger.error(f"Failed to query old chunk UUIDs for {doc_id} (async): {e}", exc_info=True)
        return

    if ids_to_delete:
        try:
            await vector_store.adelete(ids=ids_to_delete)
            logger.info(f"Deleted from PGVectorStore: {doc_id} ({len(ids_to_delete)} chunks)")
        except Exception as e:
            logger.error(f"vector_store.adelete (async) failed for {doc_id} (chunks: {ids_to_delete}): {e}", exc_info=True)
    else:
        logger.info(f"No chunks found in PGVectorStore to delete for: {doc_id}")

    # 2. 从 ParentStore (Redis) 删除父文档
    try:
        await parent_store.amdelete([doc_id])
        logger.info(f"Deleted from ParentStore (RedisStore): {doc_id}")
    except Exception as e:
        logger.error(f"parent_store.amdelete (async) failed for {doc_id}: {e}", exc_info=True)