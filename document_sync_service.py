from __future__ import annotations
import os
from typing import Dict, Any, List
from app.outline_client import paginate_all_documents, fetch_document
from app.embeddings import embed_texts
from app.repo import upsert_document, replace_all_documents

def normalize_doc_item(item: Dict[str, Any]) -> Dict[str, Any]:
    # Outline documents.list returns minimal data; often need documents.info to get text
    doc_id = item["id"]
    info = fetch_document(doc_id)
    data = info.get("data", {})
    # data.text contains Markdown; data.title; data.url
    return {
        "id": data.get("id") or doc_id,
        "title": data.get("title") or item.get("title") or "",
        "urlId": data.get("urlId") or item.get("urlId"),
        "slug": data.get("slug") or item.get("slug"),
        "collectionId": data.get("collectionId") or item.get("collectionId"),
        "updatedAt": data.get("updatedAt") or item.get("updatedAt"),
        "url": data.get("url"),
        "text": data.get("text") or "",
    }

def sync_full_replace() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for item in paginate_all_documents():
        rows.append(normalize_doc_item(item))
    texts = [r.get("text","") for r in rows]
    vecs = embed_texts(texts) if rows else []
    replace_all_documents(rows, vecs)
    return {"status": "ok", "count": len(rows)}

def sync_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Outline webhook payload structure: see docs; handle document.created/updated
    event = payload.get("event")
    data = payload.get("data") or {}
    doc = data.get("document") or data
    doc_id = doc.get("id") or data.get("id")
    if not doc_id:
        return {"status": "ignored", "reason": "no doc id"}
    normalized = normalize_doc_item({"id": doc_id})
    vec = embed_texts([normalized.get("text","")])[0] if normalized.get("text") else [0.0]*int(os.getenv("EMBEDDING_DIM","1024"))
    upsert_document(normalized, vec)
    return {"status": "ok", "doc_id": doc_id, "event": event}
