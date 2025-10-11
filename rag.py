# rag.py
# 包含文本分块、向量检索、以及与 Outline 同步（全量、增量）等核心 RAG 功能
import re
import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from sqlalchemy import text
from database import engine, redis_client
import services
import config

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
    """
    批量处理文档及其分片，使用数据库的批量插入功能。
    docs_to_process: 一个字典列表，每个字典包含 id, title, content, updated_at, outline_updated_at_str, chunks, embeddings
    """
    if not docs_to_process:
        return

    docs_to_insert = []
    chunks_to_insert = []
    all_doc_ids_to_delete_chunks = [d['id'] for d in docs_to_process]

    for doc in docs_to_process:
        docs_to_insert.append({
            "id": doc["id"],
            "title": doc["title"],
            "content": doc["content"],
            "updated_at": doc["updated_at"],
            "outline_updated_at_str": doc["outline_updated_at_str"] # 新增
        })
        for idx, (chunk_content, emb) in enumerate(zip(doc["chunks"], doc["embeddings"])):
            if emb:
                chunks_to_insert.append({
                    "doc_id": doc["id"],
                    "idx": idx,
                    "content": chunk_content,
                    "embedding": json.dumps(emb)
                })

    with engine.begin() as conn:
        # 1. 批量更新或插入文档元数据（包含新的字符串时间戳列）
        if docs_to_insert:
            conn.execute(
                text("""
                     INSERT INTO documents (id, title, content, updated_at, outline_updated_at_str)
                     VALUES (:id, :title, :content, :updated_at, :outline_updated_at_str)
                         ON CONFLICT (id) DO UPDATE SET
                         title = EXCLUDED.title,
                                                 content = EXCLUDED.content,
                                                 updated_at = EXCLUDED.updated_at,
                                                 outline_updated_at_str = EXCLUDED.outline_updated_at_str
                     """),
                docs_to_insert
            )

        # 2. 删除这些文档之前的所有分片
        if all_doc_ids_to_delete_chunks:
            conn.execute(
                text("DELETE FROM chunks WHERE doc_id = ANY(string_to_array(:doc_ids, ','))"),
                {"doc_ids": ",".join(all_doc_ids_to_delete_chunks)}
            )

        # 3. 批量插入新的分片
        if chunks_to_insert:
            conn.execute(
                text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:doc_id, :idx, :content, :embedding)"),
                chunks_to_insert
            )

def process_doc_batch_task(doc_ids: list):
    """处理一批文档，获取内容、分片、向量化，并批量写入数据库。"""
    if not doc_ids:
        return

    docs_to_process = []
    for doc_id in doc_ids:
        info = services.outline_get_doc(doc_id)
        if not info:
            logger.warning("文档 %s 在处理时已不存在，跳过。", doc_id)
            continue

        content = info.get("text") or ""
        chunks = chunk_text(content)
        if not chunks:
            delete_doc(doc_id)
            continue

        embeddings = services.create_embeddings(chunks)

        # 同时获取原始时间戳字符串和解析后的 datetime 对象
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
            "id": doc_id,
            "title": info.get("title") or "",
            "content": content,
            "updated_at": updated_at_dt,
            "outline_updated_at_str": updated_at_str, # 传递原始字符串
            "chunks": chunks,
            "embeddings": embeddings
        })

    if docs_to_process:
        _bulk_persist_docs_and_chunks(docs_to_process)
        logger.info("后台任务完成了一批 %d 个文档的处理。", len(docs_to_process))

def refresh_all_task():
    """优雅刷新任务：对比并找出差异，然后分批将任务加入队列。"""
    try:
        # 1. 获取 Outline 上的所有文档，并提取 id -> updatedAt 原始字符串的映射
        remote_docs_raw = services.outline_list_docs()
        if remote_docs_raw is None:
            raise ConnectionError("无法从 Outline API 获取文档列表。")
        remote_docs_str = {doc['id']: doc['updatedAt'] for doc in remote_docs_raw if doc.get('id') and doc.get('updatedAt')}

        # 2. 获取本地数据库中的 id -> outline_updated_at_str 原始字符串的映射
        with engine.connect() as conn:
            local_docs_raw = conn.execute(text("SELECT id, outline_updated_at_str FROM documents")).mappings().all()
            local_docs_str = {doc['id']: doc['outline_updated_at_str'] for doc in local_docs_raw if doc.get('outline_updated_at_str')}

        # 3. 计算差异
        remote_ids = set(remote_docs_str.keys())
        local_ids = set(local_docs_str.keys())

        to_add = list(remote_ids - local_ids)
        to_delete = list(local_ids - remote_ids)
        to_check = remote_ids.intersection(local_ids)

        # 核心修复：直接比较原始时间戳字符串是否相等
        to_update = [doc_id for doc_id in to_check if remote_docs_str[doc_id] != local_docs_str[doc_id]]

        # 4. 处理删除
        if to_delete:
            logger.info("需要删除 %d 个文档。", len(to_delete))
            for doc_id in to_delete:
                delete_doc(doc_id)

        # 5. 分批处理新增和更新
        docs_to_process = to_add + to_update
        if not docs_to_process:
            logger.info("优雅刷新完成，没有文档需要更新。")
            if redis_client:
                status = {"status": "success", "message": "优雅刷新完成，没有文档需要更新。"}
                redis_client.set("refresh:status", json.dumps(status), ex=300)
            return

        batch_size = getattr(config, 'REFRESH_BATCH_SIZE', 100)
        num_batches = (len(docs_to_process) + batch_size - 1) // batch_size
        logger.info("共有 %d 个文档需要新增/更新，将分 %d 批处理。", len(docs_to_process), num_batches)

        for i in range(0, len(docs_to_process), batch_size):
            batch = docs_to_process[i:i+batch_size]
            task = {"task": "process_doc_batch", "doc_ids": batch}
            redis_client.lpush("task_queue", json.dumps(task))

        status_msg = f"优雅刷新任务已启动，共 {len(docs_to_process)} 个文档已加入处理队列。"
        logger.info(status_msg)
        if redis_client:
            status = {"status": "success", "message": status_msg}
            redis_client.set("refresh:status", json.dumps(status), ex=300)

    except Exception as e:
        logger.exception("refresh_all_task failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            redis_client.set("refresh:status", json.dumps(status), ex=300)
    finally:
        if redis_client:
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