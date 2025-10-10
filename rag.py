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
    docs_to_process: 一个字典列表，每个字典包含 id, title, content, updated_at, chunks, embeddings
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
            "updated_at": doc["updated_at"]
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
        # 1. 批量更新或插入文档元数据
        if docs_to_insert:
            # 使用 ON CONFLICT (id) DO UPDATE
            conn.execute(
                text("""
                     INSERT INTO documents (id, title, content, updated_at)
                     VALUES (:id, :title, :content, :updated_at)
                         ON CONFLICT (id) DO UPDATE SET
                         title = EXCLUDED.title,
                                                 content = EXCLUDED.content,
                                                 updated_at = EXCLUDED.updated_at
                     """),
                docs_to_insert
            )

        # 2. 删除这些文档之前的所有分片
        if all_doc_ids_to_delete_chunks:
            # 使用 UNNEST 和 TEXT[] 来高效处理列表
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
        docs_to_process.append({
            "id": doc_id,
            "title": info.get("title") or "",
            "content": content,
            "updated_at": info.get("updatedAt") or datetime.now(timezone.utc).isoformat(),
            "chunks": chunks,
            "embeddings": embeddings
        })

    if docs_to_process:
        _bulk_persist_docs_and_chunks(docs_to_process)
        logger.info("后台任务完成了一批 %d 个文档的处理。", len(docs_to_process))

def refresh_all_task():
    """优雅刷新任务：对比并找出差异，然后分批将任务加入队列。"""
    try:
        # 1. 获取 Outline 上的所有文档
        remote_docs_raw = services.outline_list_docs()
        if remote_docs_raw is None: # API调用失败
            raise ConnectionError("无法从 Outline API 获取文档列表。")

        # 修复：将远程时间字符串解析为 datetime 对象以便正确比较
        remote_docs = {}
        for doc in remote_docs_raw:
            # Outline API 返回的格式是 '2023-01-01T12:00:00.123Z'
            # Python fromisoformat 需要将 Z 替换为 +00:00
            try:
                ts_str = doc['updatedAt'].replace('Z', '+00:00')
                remote_docs[doc['id']] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                logger.warning("无法解析文档 %s 的 updatedAt 时间戳: %s", doc.get('id'), doc.get('updatedAt'))
                continue # 跳过格式不正确的条目

        # 2. 获取本地数据库中的所有文档
        with engine.connect() as conn:
            local_docs_raw = conn.execute(text("SELECT id, updated_at FROM documents")).mappings().all()
            # 修复：直接使用数据库返回的 timezone-aware datetime 对象
            local_docs = {doc['id']: doc['updated_at'] for doc in local_docs_raw}

        # 3. 计算差异
        remote_ids = set(remote_docs.keys())
        local_ids = set(local_docs.keys())

        to_add = list(remote_ids - local_ids)
        to_delete = list(local_ids - remote_ids)
        to_check = remote_ids.intersection(local_ids)

        # 修复：直接比较两个 datetime 对象
        to_update = [doc_id for doc_id in to_check if remote_docs[doc_id] > local_docs[doc_id]]

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
                status = {"status": "success", "message": f"优雅刷新完成，没有文档需要更新。"}
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

