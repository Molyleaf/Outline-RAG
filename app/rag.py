# app/rag.py
import asyncio
import json
import logging
import pickle
from datetime import datetime, timezone
from typing import Optional

from langchain_community.storage.sql import SQLStore
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors.base import DocumentCompressorPipeline
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.stores import BaseStore
from langchain_postgres.v2.async_vectorstore import AsyncPGVectorStore
from langchain_postgres.v2.engine import PGEngine
from langchain_classic.storage import EncoderBackedStore
from langchain_text_splitters.markdown import MarkdownHeaderTextSplitter
from sqlalchemy import text

import config
from database import async_engine, AsyncSessionLocal, redis_client as async_redis_client
from llm_services import embeddings_model, reranker, store as embedding_cache_store
from outline_client import outline_list_docs, outline_get_doc, outline_export_doc

logger = logging.getLogger(__name__)

# LangChain 组件将按需延迟初始化
vector_store: Optional[AsyncPGVectorStore] = None
parent_store: Optional[BaseStore[str, Document]] = None
base_retriever: Optional[BaseRetriever] = None # (*** 修改：现在是块检索器 ***)
compression_retriever: Optional[ContextualCompressionRetriever] = None # (*** 修改：现在是块重排器 ***)

# 确保 RAG 组件在多进程环境中只初始化一次的锁
_rag_lock = asyncio.Lock()


async def initialize_rag_components():
    """
    异步初始化所有 RAG 相关的 LangChain 组件。
    使用锁来确保在并发请求下只执行一次。
    """
    global vector_store, base_retriever, compression_retriever, parent_store

    if vector_store:
        return

    async with _rag_lock:
        if vector_store:
            return

        logger.info("Initializing RAG components (AsyncEngine, PGVectorStore v2, SQLStore)...")

        if not async_engine:
            raise ValueError("AsyncEngine from database.py is not available")
        if not config.DATABASE_URL:
            raise ValueError("DATABASE_URL is not set, but is required for SQLStore")

        # 1. 创建基础的字节存储 (SQLStore)
        base_sql_store = SQLStore(
            engine=async_engine,
            namespace="rag_parent_documents"
        )
        logger.info(f"Async SQLStore for ParentStore configured (engine=async_engine, namespace='rag_parent_documents').")

        # 2. 包装基础存储，使其能处理 Document 对象的序列化/反序列化
        parent_store = EncoderBackedStore[str, Document](
            store=base_sql_store,
            key_encoder=lambda k: k,
            value_serializer=pickle.dumps,
            value_deserializer=pickle.loads
        )
        logger.info("ParentStore configured (EncoderBackedStore over SQLStore).")


        # 3. 初始化 PGVectorStore (子块存储)
        pg_engine_wrapper = PGEngine.from_engine(async_engine)
        try:
            vector_store = await AsyncPGVectorStore.create(
                engine=pg_engine_wrapper,
                embedding_service=embeddings_model,
                table_name="langchain_pg_embedding",
                metadata_columns=[
                    "source_id",
                    "title",
                    "outline_updated_at_str",
                    "url",
                ],
            )
            logger.info("AsyncPGVectorStore (v2) initialized (using explicit metadata columns).")
        except Exception as e:
            logger.critical(f"Failed to initialize PGVectorStore: {e}", exc_info=True)
            raise

        # 4. 初始化基础 *块* 检索器 (k=12)
        base_retriever = vector_store.as_retriever(
            search_kwargs={"k": config.TOP_K}
        )
        logger.info(f"Base chunk retriever configured (PGVectorStore.as_retriever, k={config.TOP_K}).")

        # 5. 初始化压缩/重排管线
        pipeline_compressor = DocumentCompressorPipeline(
            transformers=[
                reranker # 异步 Reranker (top_n=K=6)
            ]
        )

        # 6. 创建一个 reranker 包装的 *块* 检索器
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=pipeline_compressor,
            base_retriever=base_retriever
        )
        logger.info("RAG components initialization complete (Reranking Chunks).")


# 定义要分割的 Markdown 标题级别
headers_to_split_on = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]

# 这个分割器将在索引时用于创建子块
text_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=headers_to_split_on,
    strip_headers=False,
    return_each_line=False
)

# --- 数据库同步任务 ---

async def process_doc_batch_task(doc_ids: list):
    """
    异步处理一个批次的文档 ID，从 Outline 获取内容，
    并将其存入 ParentStore (SQL) 和 VectorStore (Postgres)。
    (*** 修复：移除 amdelete 逻辑以避免竞态条件 ***)
    """
    await initialize_rag_components()

    if not vector_store or not parent_store:
        logger.critical("Vector store or Parent store not initialized in process_doc_batch_task!")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

    if not doc_ids:
        return

    successful_ids_final = set()
    skipped_ids_final = set()
    docs_to_process_lc = []

    try:
        # 1. 从 Outline API 批量获取文档内容
        for doc_id in doc_ids:
            info = await outline_get_doc(doc_id)
            if not info:
                logger.warning(f"无法获取文档 {doc_id} 的 *信息* (metadata)，跳过。")
                skipped_ids_final.add(doc_id)
                continue

            export_data = await outline_export_doc(doc_id)
            if not export_data:
                logger.warning(f"无法获取文档 {doc_id} 的 *内容* (export)，跳过。")
                skipped_ids_final.add(doc_id)
                continue

            content = export_data or ""
            if not content.strip():
                logger.info(f"Document {doc_id} (title: {info.get('title')}) is empty, skipping.")
                skipped_ids_final.add(doc_id)
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
                    "url": info.get("url")
                }
            )
            docs_to_process_lc.append(doc)

        if docs_to_process_lc:
            # 2. 将父文档分割为子块
            chunks_to_add = []
            parents_to_add = []
            source_ids_to_process = []

            for parent_doc in docs_to_process_lc:
                source_id = parent_doc.metadata.get("source_id")
                if not source_id:
                    logger.warning(f"Skipping document with no source_id: {parent_doc.metadata.get('title')}")
                    continue

                source_ids_to_process.append(source_id)
                parents_to_add.append((source_id, parent_doc))

                child_chunks = text_splitter.split_text(parent_doc.page_content)

                for chunk in child_chunks:
                    parent_metadata = parent_doc.metadata.copy()
                    merged_metadata = {**chunk.metadata, **parent_metadata}
                    chunk.metadata = merged_metadata

                    if not chunk.page_content.strip():
                        continue

                    chunks_to_add.append(chunk)

            if chunks_to_add:
                logger.info(f"Processing {len(chunks_to_add)} chunks for {len(docs_to_process_lc)} documents...")

                # 3. 手动从 PGVector 删除旧的子块
                ids_to_delete = []
                try:
                    async with AsyncSessionLocal.begin() as session:
                        ids_to_delete_rows = (await session.execute(
                            text("""
                                 SELECT langchain_id FROM langchain_pg_embedding
                                 WHERE source_id = ANY(:source_ids)
                                 """),
                            {"source_ids": source_ids_to_process}
                        )).fetchall()
                        ids_to_delete = [row[0] for row in ids_to_delete_rows]
                except Exception as e:
                    logger.error(f"Failed to query old chunk UUIDs (async): {e}. Skipping delete.", exc_info=True)
                    ids_to_delete = []

                if ids_to_delete:
                    logger.info(f"Deleting {len(ids_to_delete)} old chunks from PGVectorStore for {len(source_ids_to_process)} docs...")
                    await vector_store.adelete(ids=ids_to_delete)

                # 4. 异步手动执行索引逻辑
                try:
                    # (*** 修复：已删除 4a (amdelete) ***)

                    # 4b. 将父文档存入 SQLStore
                    await parent_store.amset(parents_to_add)

                    # 4c. 将新的子块存入 PGVectorStore
                    #     CacheBackedEmbeddings 将自动处理缓存。
                    #     如果 key (内容哈希) 已存在，它将跳过 API 调用和 INSERT。
                    await vector_store.aadd_documents(chunks_to_add)

                except Exception as e:
                    logger.error(f"Failed (async) to add {len(chunks_to_add)} chunks or {len(parents_to_add)} parent docs: {e}.", exc_info=True)
                    # 抛出异常以触发外部 except 块
                    raise e

            # 索引成功（或无需索引），标记这些ID为成功
            for doc in docs_to_process_lc:
                successful_ids_final.add(doc.metadata["source_id"])

    except Exception as e:
        logger.error(f"Batch task for doc_ids {doc_ids} failed during processing: {e}", exc_info=True)
        # 如果批次失败，将 *所有* ID 标记为跳过
        successful_ids_final = set()
        skipped_ids_final = set(doc_ids)

    finally:
        # 无论成功还是失败，都在 finally 块中更新计数器
        if async_redis_client:
            try:
                p = async_redis_client.pipeline()
                if successful_ids_final:
                    p.incrby("refresh:success_count", len(successful_ids_final))
                if skipped_ids_final:
                    p.incrby("refresh:skipped_count", len(skipped_ids_final))
                await p.execute()
                logger.info(f"Redis counters updated: success={len(successful_ids_final)}, skipped={len(skipped_ids_final)}")
            except Exception as e:
                logger.error("Failed to update Redis refresh counters (async) in finally block: %s", e)

    logger.info(f"Batch task complete (async): {len(successful_ids_final)} processed, {len(skipped_ids_final)} skipped.")


async def refresh_all_task():
    """
    执行 RAG 优雅刷新。
    比较 Outline API 和本地存储，以确定要添加、更新或删除的文档。
    """
    await initialize_rag_components()

    try:
        remote_docs_raw = await outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("Failed to retrieve document list from Outline API.")

        remote_docs_map = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        local_docs_map = {}
        try:
            async with AsyncSessionLocal.begin() as session:
                local_docs_raw = (await session.execute(
                    text("""
                         SELECT DISTINCT ON (source_id)
                             source_id as id,
                             outline_updated_at_str
                         FROM langchain_pg_embedding
                         WHERE source_id IS NOT NULL
                         """)
                )).mappings().all()
                local_docs_map = {doc['id']: doc['outline_updated_at_str'] for doc in local_docs_raw if doc.get('id') and doc.get('outline_updated_at_str')}
        except Exception as e:
            logger.error(f"Failed to read metadata from PGVectorStore (async): {e}", exc_info=True)

        remote_ids = set(remote_docs_map.keys())
        local_ids = set(local_docs_map.keys())

        to_add_ids = list(remote_ids - local_ids)
        to_delete_ids = list(local_ids - remote_ids)
        to_check_ids = remote_ids.intersection(local_ids)

        to_update_ids = [doc_id for doc_id in to_check_ids if remote_docs_map[doc_id] != local_docs_map.get(doc_id)]

        if to_delete_ids:
            logger.warning(f"Found {len(to_delete_ids)} docs locally that are not remote. Deleting...")
            for doc_id in to_delete_ids:
                await delete_doc(doc_id)

        docs_to_process_ids = to_add_ids + to_update_ids
        if not docs_to_process_ids:
            final_message = f"Refresh complete. Removed {len(to_delete_ids)} old docs." if to_delete_ids else "Refresh complete. Data is up to date."
            logger.info(final_message)
            if async_redis_client:
                status = {"status": "success", "message": final_message}
                await async_redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        if async_redis_client:
            try:
                p = async_redis_client.pipeline()
                p.set("refresh:total_queued", len(docs_to_process_ids))
                p.set("refresh:success_count", 0)
                p.set("refresh:skipped_count", 0)
                p.set("refresh:delete_count", len(to_delete_ids))
                p.delete("refresh:status")
                await p.execute()
            except Exception as e:
                logger.error("Failed to initialize Redis refresh counters (async): %s", e)

        batch_size = config.REFRESH_BATCH_SIZE
        num_batches = (len(docs_to_process_ids) + batch_size - 1) // batch_size
        logger.info(f"{len(docs_to_process_ids)} docs need update/add, splitting into {num_batches} batches.")

        for i in range(0, len(docs_to_process_ids), batch_size):
            batch = docs_to_process_ids[i:i+batch_size]
            task = {"task": "process_doc_batch", "doc_ids": batch}
            await async_redis_client.lpush("task_queue", json.dumps(task))

        logger.info(f"Queued {len(docs_to_process_ids)} doc processing tasks.")

    except Exception as e:
        logger.exception("refresh_all_task (async) failed: %s", e)
        if async_redis_client:
            status = {"status": "error", "message": f"Refresh failed: {e}"}
            await async_redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        if async_redis_client and not (await async_redis_client.exists("refresh:total_queued")):
            await async_redis_client.delete("refresh:lock")


async def delete_doc(doc_id):
    """
    从 PGVectorStore (子块) 和 SQLStore (父文档) 中异步删除一个文档。
    """
    await initialize_rag_components()

    if not vector_store or not parent_store:
        logger.critical("Vector store or Parent store not initialized in delete_doc!")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

    # 1. 从 PGVector (Postgres) 删除子块
    ids_to_delete = []
    try:
        async with AsyncSessionLocal.begin() as session:
            ids_to_delete_rows = (await session.execute(
                text("""
                     SELECT langchain_id FROM langchain_pg_embedding
                     WHERE source_id = :source_id
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

    # 2. 从 ParentStore (SQLStore) 删除父文档
    try:
        await parent_store.amdelete([doc_id])
        logger.info(f"Deleted from ParentStore (SQLStore): {doc_id}")
    except Exception as e:
        logger.error(f"parent_store.amdelete (async) failed for {doc_id}: {e}", exc_info=True)