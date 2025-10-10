# rag.py
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

def refresh_all_task():
    """
    在后台任务中执行的优雅刷新任务的包装器。
    由 'refresh_all' 任务触发，负责处理状态和锁。
    """
    try:
        num_changes = refresh_all_graceful()
        status = {"status": "success", "message": f"优雅刷新完成，共处理 {num_changes} 个文档变更。"}
        if redis_client:
            redis_client.set("refresh:status", json.dumps(status), ex=3600)
        logger.info(status["message"])
    except Exception as e:
        logger.exception("优雅刷新任务执行失败: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            redis_client.set("refresh:status", json.dumps(status), ex=3600)
    finally:
        if redis_client:
            # 任务结束，删除锁
            redis_client.delete("refresh:lock")

def refresh_all_graceful():
    """
    执行“优雅”刷新：对比本地与远程文档，仅处理差异。
    返回处理的文档数量 (新增+更新+删除)。
    """
    logger.info("开始执行优雅刷新...")
    # 1. 获取远程 Outline 文档列表
    remote_docs = services.outline_list_docs()
    if not remote_docs:
        logger.warning("从 Outline API 未获取到任何文档。")
        return 0
    remote_docs_map = {d['id']: d['updatedAt'] for d in remote_docs}

    # 2. 获取本地数据库中的文档列表
    with engine.begin() as conn:
        local_docs_raw = conn.execute(text("SELECT id, updated_at FROM documents")).mappings().all()
    local_docs_map = {r['id']: r['updated_at'].isoformat().replace('+00:00', 'Z') for r in local_docs_raw}

    # 3. 对比差异
    remote_ids = set(remote_docs_map.keys())
    local_ids = set(local_docs_map.keys())

    ids_to_add = list(remote_ids - local_ids)
    ids_to_delete = list(local_ids - remote_ids)
    ids_to_check = remote_ids.intersection(local_ids)

    ids_to_update = []
    for doc_id in ids_to_check:
        try:
            remote_dt = datetime.fromisoformat(remote_docs_map[doc_id].replace('Z', '+00:00'))
            local_dt = datetime.fromisoformat(local_docs_map[doc_id].replace('Z', '+00:00'))
            if remote_dt > local_dt:
                ids_to_update.append(doc_id)
        except (ValueError, TypeError):
            logger.warning("无法解析或比较文档 %s 的时间戳，将强制更新。", doc_id)
            ids_to_update.append(doc_id)

    total_changes = len(ids_to_add) + len(ids_to_update) + len(ids_to_delete)
    logger.info(f"刷新对比完成：新增 {len(ids_to_add)}, 更新 {len(ids_to_update)}, 删除 {len(ids_to_delete)}。")
    if not total_changes:
        return 0

    # 4. 执行批量删除操作
    if ids_to_delete:
        delete_docs_bulk(ids_to_delete)

    # 5. 将新增和更新任务分批次放入队列
    docs_to_process = ids_to_add + ids_to_update
    batch_size = config.REFRESH_BATCH_SIZE
    for i in range(0, len(docs_to_process), batch_size):
        batch = docs_to_process[i:i + batch_size]
        task = {"task": "process_doc_batch", "doc_ids": batch}
        redis_client.lpush("task_queue", json.dumps(task))

    logger.info(f"已将 {len(docs_to_process)} 个文档处理任务分批加入队列。")
    return total_changes

def process_doc_batch_task(doc_ids):
    """处理一批文档，获取内容、分块、向量化，并批量写入数据库。"""
    if not doc_ids: return
    logger.info("开始处理批次，包含 %d 个文档: %s...", len(doc_ids), doc_ids[:3])

    docs_data, chunks_data = [], []
    for doc_id in doc_ids:
        info = services.outline_get_doc(doc_id)
        if not info:
            logger.warning("获取文档 %s 信息失败，跳过。", doc_id)
            continue

        title = info.get("title") or ""
        content = info.get("text") or ""
        updated_at_str = info.get("updatedAt") or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        updated_at_dt = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))

        docs_data.append({"id": doc_id, "title": title, "content": content, "updated_at": updated_at_dt})

        chunks = chunk_text(content)
        if chunks:
            embs = services.create_embeddings(chunks)
            for idx, (chunk_content, emb) in enumerate(zip(chunks, embs)):
                if emb:
                    chunks_data.append({"doc_id": doc_id, "idx": idx, "content": chunk_content, "embedding": json.dumps(emb)})

    if docs_data:
        _bulk_persist_docs_and_chunks(docs_data, chunks_data)
        logger.info("批次处理完成，成功写入 %d 个文档和 %d 个文本块。", len(docs_data), len(chunks_data))

def verify_outline_signature(raw_body, signature_hex: str) -> bool:
    if not config.OUTLINE_WEBHOOK_SIGN: return True
    try:
        sig = (signature_hex or "").strip()
        logger.debug("收到的签名头: %s", sig)
        if sig.lower().startswith("sha256="): sig = sig.split("=", 1)[1].strip()
        if sig.lower().startswith("bearer "): sig = sig.split(" ", 1)[1].strip()

        mac = hmac.new(config.OUTLINE_WEBHOOK_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        expected_sig = mac.hexdigest()

        is_valid = hmac.compare_digest(expected_sig, sig)
        if not is_valid:
            logger.warning("Webhook 签名不匹配。预期: %s, 实际: %s", expected_sig, sig)
        return is_valid
    except Exception as e:
        logger.warning("校验 Outline Webhook 签名时出错: %s", e)
        return False

def _bulk_persist_docs_and_chunks(docs_to_upsert, chunks_to_insert):
    """使用原生 SQL 批量 upsert 文档和批量 insert 文本块。"""
    with engine.begin() as conn:
        if docs_to_upsert:
            conn.execute(
                text("""
                     INSERT INTO documents (id, title, content, updated_at)
                     VALUES (:id, :title, :content, :updated_at)
                         ON CONFLICT (id) DO UPDATE SET
                         title = EXCLUDED.title,
                                                 content = EXCLUDED.content,
                                                 updated_at = EXCLUDED.updated_at
                     """),
                docs_to_upsert
            )

        doc_ids_in_batch = [d['id'] for d in docs_to_upsert]
        if not doc_ids_in_batch: return

        conn.execute(text("DELETE FROM chunks WHERE doc_id = ANY(:ids)"), {"ids": doc_ids_in_batch})

        if chunks_to_insert:
            conn.execute(
                text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:doc_id, :idx, :content, :embedding::vector)"),
                chunks_to_insert
            )

def upsert_one_doc(doc_id):
    """将单个文档的 upsert 请求放入任务队列。"""
    task = {"task": "process_doc_batch", "doc_ids": [doc_id]}
    if redis_client:
        redis_client.lpush("task_queue", json.dumps(task))
        logger.info("已将单个文档加入处理队列: %s", doc_id)
    else:
        # 当 Redis 不可用时，同步执行作为降级方案
        logger.warning("Redis 未配置，同步处理文档: %s", doc_id)
        process_doc_batch_task([doc_id])

def delete_doc(doc_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
    logger.info("已删除文档: %s", doc_id)

def delete_docs_bulk(doc_ids: list):
    """批量删除文档。"""
    if not doc_ids: return
    with engine.begin() as conn:
        # ON DELETE CASCADE 会自动处理关联的 chunks
        conn.execute(text("DELETE FROM documents WHERE id = ANY(:ids)"), {"ids": doc_ids})
    logger.info("已批量删除 %d 个文档。", len(doc_ids))
