# app/rag.py
# 包含文本分块、向量检索、以及与 Outline 同步（全量、增量）等核心 RAG 功能
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

import config
import services
from database import engine, redis_client

logger = logging.getLogger(__name__)

def chunk_text(text, max_chars=1000, overlap=200):
    text = text.strip()
    if not text: return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    sentences = []
    for p in paragraphs:
        parts = re.split(r"(?<=[。！？!?；;])\s*|(?<=[!])\s+", p)
        sentences.extend([s.strip() for s in parts if s.strip()] or [p])
    chunks, buf = [], ""
    for s in sentences:
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_chars:
            buf = f"{buf}\n{s}"
        else:
            if len(buf) >= max(100, overlap):
                chunks.append(buf)
            else:
                buf = f"{buf} {s}" if len(buf) + 1 + len(s) <= max_chars else s
                continue
            tail = chunks[-1][-overlap:] if overlap > 0 and chunks[-1] else ""
            buf = tail + s if len(tail) + len(s) <= max_chars else s
    if buf and len(buf) >= 100:
        chunks.append(buf)
    return chunks

def search_similar(query, k=12):
    q_emb = services.create_embeddings([query])[0]
    if not q_emb: return []
    qv_text = json.dumps(q_emb)
    with engine.begin() as conn:
        rs = conn.execute(text("""
                               SELECT id, doc_id, idx, content, 1 - (embedding <=> (:qv_text)::vector) AS score
                               FROM chunks ORDER BY embedding <=> (:qv_text)::vector LIMIT :k
                               """), {"qv_text": qv_text, "k": k}).mappings().all()
    return [dict(r) for r in rs]

def _bulk_persist_docs_and_chunks(docs_to_process: list):
    if not docs_to_process:
        return
    docs_to_insert = []
    chunks_to_insert = []
    all_doc_ids_to_delete_chunks = [d['id'] for d in docs_to_process]
    for doc in docs_to_process:
        docs_to_insert.append({
            "id": doc["id"], "title": doc["title"], "content": doc["content"],
            "updated_at": doc["updated_at"], "outline_updated_at_str": doc["outline_updated_at_str"]
        })
        for idx, (chunk_content, emb) in enumerate(zip(doc["chunks"], doc["embeddings"])):
            if emb:
                chunks_to_insert.append({
                    "doc_id": doc["id"], "idx": idx, "content": chunk_content, "embedding": json.dumps(emb)
                })
    with engine.begin() as conn:
        if docs_to_insert:
            conn.execute(
                text("""
                     INSERT INTO documents (id, title, content, updated_at, outline_updated_at_str)
                     VALUES (:id, :title, :content, :updated_at, :outline_updated_at_str)
                         ON CONFLICT (id) DO UPDATE SET
                         title = EXCLUDED.title, content = EXCLUDED.content,
                                                 updated_at = EXCLUDED.updated_at, outline_updated_at_str = EXCLUDED.outline_updated_at_str
                     """),
                docs_to_insert
            )
        if all_doc_ids_to_delete_chunks:
            conn.execute(
                text("DELETE FROM chunks WHERE doc_id = ANY(string_to_array(:doc_ids, ','))"),
                {"doc_ids": ",".join(all_doc_ids_to_delete_chunks)}
            )
        if chunks_to_insert:
            conn.execute(
                text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:doc_id, :idx, :content, :embedding)"),
                chunks_to_insert
            )

def process_doc_batch_task(doc_ids: list):
    """处理一批文档，并更新全局刷新计数器。"""
    if not doc_ids:
        return

    docs_to_process = []
    successful_ids = set()
    skipped_ids = set()

    for doc_id in doc_ids:
        info = services.outline_get_doc(doc_id)
        if not info:
            logger.warning(f"无法获取文档 {doc_id} 的内容，跳过。")
            skipped_ids.add(doc_id)
            continue

        content = info.get("text") or ""
        chunks = chunk_text(content)
        if not chunks:
            skipped_ids.add(doc_id)
            continue

        embeddings = services.create_embeddings(chunks)
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

        docs_to_process.append({
            "id": doc_id, "title": info.get("title") or "", "content": content,
            "updated_at": updated_at_dt, "outline_updated_at_str": updated_at_str,
            "chunks": chunks, "embeddings": embeddings
        })
        successful_ids.add(doc_id)

    if docs_to_process:
        _bulk_persist_docs_and_chunks(docs_to_process)

    # 更新Redis中的全局计数器
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
    """优雅刷新任务：对比并找出差异，然后分批将任务加入队列。"""
    try:
        remote_docs_raw = services.outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("无法从 Outline API 获取文档列表。")

        remote_docs_str = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        with engine.connect() as conn:
            local_docs_raw = conn.execute(text("SELECT id, outline_updated_at_str FROM documents")).mappings().all()
            local_docs_str = {doc['id']: doc['outline_updated_at_str'] for doc in local_docs_raw if doc.get('outline_updated_at_str')}

        remote_ids = set(remote_docs_str.keys())
        local_ids = set(local_docs_str.keys())

        to_add = list(remote_ids - local_ids)
        to_delete = list(local_ids - remote_ids)
        to_check = remote_ids.intersection(local_ids)
        to_update = [doc_id for doc_id in to_check if remote_docs_str[doc_id] != local_docs_str.get(doc_id)]

        if to_delete:
            logger.warning(f"发现 {len(to_delete)} 篇在本地存在但在远程不存在的文档，将被删除。")
            for doc_id in to_delete:
                delete_doc(doc_id)

        docs_to_process = to_add + to_update
        if not docs_to_process:
            if not to_delete:
                logger.info("优雅刷新完成，所有文档均是最新。")
            # 即使没有要处理的文档，也设置最终状态
            final_message = f"刷新完成。删除了 {len(to_delete)} 篇陈旧文档。" if to_delete else "刷新完成，数据已是最新。"
            if redis_client:
                status = {"status": "success", "message": final_message}
                redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        # 初始化刷新任务的计数器
        if redis_client:
            try:
                p = redis_client.pipeline()
                p.set("refresh:total_queued", len(docs_to_process))
                p.set("refresh:success_count", 0)
                p.set("refresh:skipped_count", 0)
                p.set("refresh:delete_count", len(to_delete)) # 记录删除数量
                p.delete("refresh:status") # 清除旧的最终状态
                p.execute()
            except Exception as e:
                logger.error("初始化Redis刷新计数器时出错: %s", e)

        batch_size = config.REFRESH_BATCH_SIZE
        num_batches = (len(docs_to_process) + batch_size - 1) // batch_size
        logger.info(f"共有 {len(docs_to_process)} 个文档需要新增/更新，将分 {num_batches} 批处理。")

        for i in range(0, len(docs_to_process), batch_size):
            batch = docs_to_process[i:i+batch_size]
            task = {"task": "process_doc_batch", "doc_ids": batch}
            redis_client.lpush("task_queue", json.dumps(task))

        logger.info(f"已将 {len(docs_to_process)} 个文档的新增/更新任务加入处理队列。")

    except Exception as e:
        logger.exception("refresh_all_task failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        if redis_client and not redis_client.exists("refresh:total_queued"):
            # 如果任务因为启动失败而没有设置计数器，确保解锁
            redis_client.delete("refresh:lock")

def verify_outline_signature(raw_body, signature_hex: str) -> bool:
    if not config.OUTLINE_WEBHOOK_SIGN: return True
    try:
        sig = (signature_hex or "").strip()
        if sig.lower().startswith("sha256="): sig = sig.split("=", 1)[1].strip()
        if sig.lower().startswith("bearer "): sig = sig.split(" ", 1)[1].strip()
        mac = hmac.new(config.OUTLINE_WEBHOOK_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), sig)
    except Exception as e:
        logger.warning("verify_outline_signature error: %s", e)
        return False

def delete_doc(doc_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
    logger.info("Deleted document: %s", doc_id)