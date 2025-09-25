import os
import math
from typing import Dict, List, Any, Iterable, Tuple
from app.http_client import http_get

OUTLINE_API_URL = os.getenv("OUTLINE_API_URL", "").rstrip("/")
OUTLINE_API_TOKEN = os.getenv("OUTLINE_API_TOKEN", "")

def _auth_headers():
    return {"Authorization": f"Bearer {OUTLINE_API_TOKEN}"} if OUTLINE_API_TOKEN else {}

def list_documents(limit=100, offset=0):
    # Outline API: GET /api/documents.list?limit=&offset=  (See docs)
    url = f"{OUTLINE_API_URL}/api/documents.list?limit={limit}&offset={offset}"
    return http_get(url, headers=_auth_headers())

def fetch_document(doc_id: str):
    url = f"{OUTLINE_API_URL}/api/documents.info?id={doc_id}"
    return http_get(url, headers=_auth_headers())

def fetch_document_content(doc_id: str):
    url = f"{OUTLINE_API_URL}/api/documents.info?id={doc_id}&shareId="
    data = http_get(url, headers=_auth_headers())
    # The Outline API returns .data.text for Markdown content
    return data

def paginate_all_documents() -> Iterable[Dict[str, Any]]:
    offset = 0
    limit = 100
    while True:
        resp = list_documents(limit=limit, offset=offset)
        rows = resp.get("data", [])
        if not rows:
            break
        for r in rows:
            yield r
        offset += limit
