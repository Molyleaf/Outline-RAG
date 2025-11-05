# app/rag.py
# 包含文本分块、向量检索、以及与 Outline 同步（全量、增量）等核心 RAG 功能
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from langchain_community.vectorstores import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.document_transformers import EmbeddingsRedundantFilter
from langchain_core.documents import Document

import config
from database import engine, redis_client
from app.llm_services import embeddings_model, reranker
from app.outline_client import outline_list_docs, outline_get_doc

logger = logging.getLogger(__name__)

# --- 1. 初始化 LangChain 组件 ---

# 1a. 初始化 PGVector 存储
# PGVector 将自动创建 'langchain_pg_collection' 和 'langchain_pg_embedding' 表
vector_store = PGVector(
    connection_string=config.DATABASE_URL,
    collection_name="outline_rag_collection",
    embedding_function=embeddings_model,
)

# 1b. 初始化文本分割器 (替换 chunk_text)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""],
)

# 1c. 初始化基础检索器 (替换 search_similar)
base_retriever = vector_store.as_retriever(
    search_type="similarity",
    search_kwargs={"k": config.TOP_K}
)

# 1d. 初始化压缩/重排检索器 (替换 services.rerank)
#    这个检索器会自动运行基础检索，然后使用 reranker (SiliconFlowReranker) 压缩结果
pipeline_compressor = DocumentCompressorPipeline(
    transformers=[
        EmbeddingsRedundantFilter(embeddings=embeddings_model),
        reranker # 来自 llm_services.py
    ]
)

compression_retriever = ContextualCompressionRetriever(
    base_compressor=pipeline_compressor,
    base_retriever=base_retriever
)

# --- 2. 数据库同步任务 (重写) ---

def process_doc_batch_task(doc_ids: list):
    """
    (重写) 处理一批文档：获取、分块、嵌入并存储到 PGVector 和 SQL 跟踪表。
    """
    if not doc_ids:
        return

    docs_to_process_lc = []
    docs_to_process_sql = []
    successful_ids = set()
    skipped_ids = set()

    for doc_id in doc_ids:
        info = outline_get_doc(doc_id)
        if not info:
            logger.warning(f"无法获取文档 {doc_id} 的内容，跳过。")
            skipped_ids.add(doc_id)
            continue

        content = info.get("text") or ""
        if not content.strip():
            skipped_ids.add(doc_id)
            continue

        # (逻辑保留自 rag.py)
        updated_at_str = info.get("updatedAt")
        if not updated_at_str:
            now_dt = datetime.now(timezone.utc)
            updated_at_dt = now_dt
            updated_at_str = now_dt.isoformat().replace('+00:00', 'Z')
        else:
            try:
                updated_at_dt = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                logger.warning("无法解析文档 %s 的 updatedAt 时间戳 '%s'，使用当前时间代替。", doc_id, updated_at_str)
                updated_at_dt = datetime.now(timezone.utc)

        # 1. 创建 LangChain Document 对象
        doc = Document(
            page_content=content,
            metadata={
                "source_id": doc_id, # 用于 PGVector 过滤
                "title": info.get("title") or "",
                "outline_updated_at_str": updated_at_str,
            }
        )
        docs_to_process_lc.append(doc)

        # 2. 准备 SQL 跟踪表数据
        docs_to_process_sql.append({
            "id": doc_id, "title": info.get("title") or "", "content": content,
            "updated_at": updated_at_dt,
            "outline_updated_at_str": updated_at_str
        })
        successful_ids.add(doc_id)

    if docs_to_process_lc:
        # 1. 分块
        chunks = text_splitter.split_documents(docs_to_process_lc)

        if chunks:
            logger.info(f"正在为 {len(successful_ids)} 篇文档处理 {len(chunks)} 个分块...")
            # 2. (原子操作) 删除 PGVector 中所有旧分块
            vector_store.delete(filter={"source_id": {"$in": list(successful_ids)}})

            # 3. (原子操作) 添加新分块
            #    我们提供自定义 ID 以确保幂等性
            chunk_ids = [f"{c.metadata['source_id']}_{i}" for i, c in enumerate(chunks)]
            vector_store.add_documents(chunks, ids=chunk_ids)

    if docs_to_process_sql:
        # 4. 更新 SQL 跟踪表 (逻辑保留自 rag.py)
        with engine.begin() as conn:
            conn.execute(
                text("""
                     INSERT INTO documents (id, title, content, updated_at, outline_updated_at_str)
                     VALUES (:id, :title, :content, :updated_at, :outline_updated_at_str)
                         ON CONFLICT (id) DO UPDATE SET
                         title = EXCLUDED.title, content = EXCLUDED.content,
                                                 updated_at = EXCLUDED.updated_at, outline_updated_at_str = EXCLUDED.outline_updated_at_str
                     """),
                docs_to_process_sql
            )

    # (逻辑保留自 rag.py)
    if redis_client:
        try:
            p = redis_client.pipeline()
            if successful_ids:
                p.incrby("refresh:success_count", len(successful_ids))
            if skipped_ids:
                p.incrby("refresh:skipped_count", len(skipped_ids))
            p.execute()
        except Exception as e:
            logger.error("更新Redis刷新计数器时出错: %s", e)

    logger.info(f"批处理任务完成: 成功处理 {len(successful_ids)} 篇, 跳过 {len(skipped_ids)} 篇。")


def refresh_all_task():
    """(重写) 优雅刷新任务：对比并找出差异，然后分批将任务加入队列。"""
    try:
        remote_docs_raw = outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("无法从 Outline API 获取文档列表。")

        remote_docs_map = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        # 仍然使用 SQL 'documents' 表进行快速元数据对比
        with engine.connect() as conn:
            local_docs_raw = conn.execute(text("SELECT id, outline_updated_at_str FROM documents")).mappings().all()
            local_docs_map = {doc['id']: doc['outline_updated_at_str'] for doc in local_docs_raw if doc.get('outline_updated_at_str')}

        remote_ids = set(remote_docs_map.keys())
        local_ids = set(local_docs_map.keys())

        to_add_ids = list(remote_ids - local_ids)
        to_delete_ids = list(local_ids - remote_ids)
        to_check_ids = remote_ids.intersection(local_ids)
        to_update_ids = [doc_id for doc_id in to_check_ids if remote_docs_map[doc_id] != local_docs_map.get(doc_id)]

        if to_delete_ids:
            logger.warning(f"发现 {len(to_delete_ids)} 篇在本地存在但在远程不存在的文档，将被删除。")
            for doc_id in to_delete_ids:
                delete_doc(doc_id) # 使用新的 delete_doc

        docs_to_process_ids = to_add_ids + to_update_ids
        if not docs_to_process_ids:
            # (逻辑保留自 rag.py)
            final_message = f"刷新完成。删除了 {len(to_delete_ids)} 篇陈旧文档。" if to_delete_ids else "刷新完成，数据已是最新。"
            if redis_client:
                status = {"status": "success", "message": final_message}
                redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        # (逻辑保留自 rag.py)
        if redis_client:
            try:
                p = redis_client.pipeline()
                p.set("refresh:total_queued", len(docs_to_process_ids))
                p.set("refresh:success_count", 0)
                p.set("refresh:skipped_count", 0)
                p.set("refresh:delete_count", len(to_delete_ids))
                p.delete("refresh:status")
                p.execute()
            except Exception as e:
                logger.error("初始化Redis刷新计数器时出错: %s", e)

        # (逻辑保留自 rag.py)
        batch_size = config.REFRESH_BATCH_SIZE
        num_batches = (len(docs_to_process_ids) + batch_size - 1) // batch_size
        logger.info(f"共有 {len(docs_to_process_ids)} 个文档需要新增/更新，将分 {num_batches} 批处理。")

        for i in range(0, len(docs_to_process_ids), batch_size):
            batch = docs_to_process_ids[i:i+batch_size]
            task = {"task": "process_doc_batch", "doc_ids": batch}
            redis_client.lpush("task_queue", json.dumps(task))

        logger.info(f"已将 {len(docs_to_process_ids)} 个文档的新增/更新任务加入处理队列。")

    except Exception as e:
        # (逻辑保留自 rag.py)
        logger.exception("refresh_all_task failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        # (逻辑保留自 rag.py)
        if redis_client and not redis_client.exists("refresh:total_queued"):
            redis_client.delete("refresh:lock")

def delete_doc(doc_id):
    """(重写) 从 SQL 跟踪表 和 PGVector 中删除文档"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})

    # 按元数据从 PGVector 删除
    vector_store.delete(filter={"source_id": {"$in": [doc_id]}})
    logger.info("已从 SQL 和 PGVector 删除文档: %s", doc_id)