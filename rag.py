# 包含文本分块、向量检索、以及与 Outline 同步（全量、增量）等核心 RAG 功能
import re
import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from sqlalchemy import text
from database import engine
import services

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

def refresh_all():
    docs = services.outline_list_docs()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE chunks, documents"))
    if not docs:
        logger.info("全量刷新完成，没有发现任何文档。")
        return 0
    for d in docs:
        upsert_one_doc(d["id"])
    logger.info("全量刷新完成，共处理 %d 个文档。", len(docs))
    return len(docs)

def verify_outline_signature(raw_body, signature_hex: str) -> bool:
    from config import OUTLINE_WEBHOOK_SIGN, OUTLINE_WEBHOOK_SECRET
    if not OUTLINE_WEBHOOK_SIGN: return True
    try:
        sig = (signature_hex or "").strip()
        if sig.lower().startswith("sha256="): sig = sig.split("=", 1)[1].strip()
        if sig.lower().startswith("bearer "): sig = sig.split(" ", 1)[1].strip()
        mac = hmac.new(OUTLINE_WEBHOOK_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), sig)
    except Exception as e:
        logger.warning("verify_outline_signature error: %s", e)
        return False

def _persist_doc_and_chunks(doc_id, title, content, updated_at, chunks, embs):
    with engine.begin() as conn:
        conn.execute(text("""
                          INSERT INTO documents (id, title, content, updated_at) VALUES (:id, :t, :c, :u)
                              ON CONFLICT (id) DO UPDATE
                                                      SET title=EXCLUDED.title, content=EXCLUDED.content, updated_at=EXCLUDED.updated_at
                          """), {"id": doc_id, "t": title, "c": content, "u": updated_at})
        conn.execute(text("DELETE FROM chunks WHERE doc_id=:d"), {"d": doc_id})
        for idx, (ck, emb) in enumerate(zip(chunks, embs)):
            if emb:
                conn.execute(text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:d,:i,:c,:e)"),
                             {"d": doc_id, "i": idx, "c": ck, "e": json.dumps(emb)})

def upsert_one_doc(doc_id):
    info = services.outline_get_doc(doc_id)
    if not info: return
    title = info.get("title") or ""
    content = info.get("text") or ""
    updated_at = info.get("updatedAt") or datetime.now(timezone.utc).isoformat()
    chunks = chunk_text(content)
    if not chunks:
        delete_doc(doc_id)
        return
    embs = services.create_embeddings(chunks)
    _persist_doc_and_chunks(doc_id, title, content, updated_at, chunks, embs)
    logger.info("Upserted document: %s", doc_id)

def delete_doc(doc_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
    logger.info("Deleted document: %s", doc_id)