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
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text

import config
from database import async_engine, AsyncSessionLocal, redis_client as async_redis_client
from llm_services import embeddings_model, reranker
from outline_client import outline_list_docs, outline_get_doc, outline_export_doc

logger = logging.getLogger(__name__)

vector_store: Optional[AsyncPGVectorStore] = None
parent_store: Optional[BaseStore[str, Document]] = None
base_retriever: Optional[BaseRetriever] = None
compression_retriever: Optional[ContextualCompressionRetriever] = None

_rag_lock = asyncio.Lock()


async def initialize_rag_components():
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

        base_sql_store = SQLStore(
            engine=async_engine,
            namespace="rag_parent_documents"
        )
        logger.info(f"Async SQLStore for ParentStore configured (engine=async_engine, namespace='rag_parent_documents').")

        parent_store = EncoderBackedStore[str, Document](
            store=base_sql_store,
            key_encoder=lambda k: k,
            value_serializer=pickle.dumps,
            value_deserializer=pickle.loads
        )
        logger.info("ParentStore configured (EncoderBackedStore over SQLStore).")

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

        base_retriever = vector_store.as_retriever(
            search_kwargs={"k": config.TOP_K}
        )
        logger.info(f"Base chunk retriever configured (PGVectorStore.as_retriever, k={config.TOP_K}).")

        pipeline_compressor = DocumentCompressorPipeline(
            transformers=[
                reranker
            ]
        )

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=pipeline_compressor,
            base_retriever=base_retriever
        )
        logger.info("RAG components initialization complete (Reranking Chunks).")


headers_to_split_on = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]

markdown_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=headers_to_split_on,
    strip_headers=False,
    return_each_line=False
)

# --- 第二层拆分器 (细分) ---
# 用于拆分过长的 Markdown 块
# 我们使用 Python 默认的换行符作为主要分隔符
child_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1024, # 示例值：1024 个字符
    chunk_overlap=100, # 示例值：100 个字符
    separators=["\n\n", "\n", " ", ""] # 适用于通用文本
)


async def process_doc_batch_task(doc_ids: list):
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

                # 获取父文档标题
                parent_title = parent_doc.metadata.get("title") or ""

                # 1. [粗分]：首先按 Markdown 标题拆分
                # 这会产生一些 Document，可能有的很长，有的很短
                # 它们已经包含了 chunk.metadata (例如 {'Header 1': '共和国之辉'})
                md_chunks = markdown_splitter.split_text(parent_doc.page_content)

                for md_chunk in md_chunks:
                    # 2. [细分]：检查每个块是否过长，如果过长，则再次拆分
                    # 我们将 md_chunk 的元数据（包含标题信息）传递给子块

                    if len(md_chunk.page_content) > child_splitter._chunk_size:
                        # 这个块太长了，使用 RecursiveCharacterTextSplitter 进一步细分
                        sub_chunks = child_splitter.create_documents(
                            [md_chunk.page_content],
                            metadatas=[md_chunk.metadata]
                        )
                    else:
                        # 这个块长度合适，直接使用
                        sub_chunks = [md_chunk]

                    # 3. [处理子块]：处理所有细分后的块
                    for chunk in sub_chunks:
                        # 合并父文档元数据 (source_id, title, url...)
                        # 和块元数据 (Header 1, Header 2...)
                        parent_metadata = parent_doc.metadata.copy()
                        merged_metadata = {**chunk.metadata, **parent_metadata}
                        chunk.metadata = merged_metadata

                        # 2. 将父标题强行注入 page_content (保持不变)
                        if parent_title:
                            chunk.page_content = f"文档标题: {parent_title}\n\n{chunk.page_content}"

                        if not chunk.page_content.strip():
                            continue

                        chunks_to_add.append(chunk)

            if chunks_to_add:
                logger.info(f"Processing {len(chunks_to_add)} chunks for {len(docs_to_process_lc)} documents...")

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

                try:
                    await parent_store.amset(parents_to_add)
                    await vector_store.aadd_documents(chunks_to_add)

                except Exception as e:
                    logger.error(f"Failed (async) to add {len(chunks_to_add)} chunks or {len(parents_to_add)} parent docs: {e}.", exc_info=True)
                    raise e

            for doc in docs_to_process_lc:
                successful_ids_final.add(doc.metadata["source_id"])

    except Exception as e:
        logger.error(f"Batch task for doc_ids {doc_ids} failed during processing: {e}", exc_info=True)
        successful_ids_final = set()
        skipped_ids_final = set(doc_ids)

    finally:
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
    await initialize_rag_components()

    if not vector_store or not parent_store:
        logger.critical("Vector store or Parent store not initialized in delete_doc!")
        raise RuntimeError("RAG components (vector_store/parent_store) not initialized")

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

    try:
        await parent_store.amdelete([doc_id])
        logger.info(f"Deleted from ParentStore (SQLStore): {doc_id}")
    except Exception as e:
        logger.error(f"parent_store.amdelete (async) failed for {doc_id}: {e}", exc_info=True)