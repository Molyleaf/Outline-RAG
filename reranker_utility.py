import os
from typing import List, Tuple
from app.http_client import http_post

RERANKER_API_URL = os.getenv("RERANKER_API_URL", "").rstrip("/")
RERANKER_API_TOKEN = os.getenv("RERANKER_API_TOKEN", "")

def rerank(query: str, candidates: List[Tuple[str, str]]) -> List[int]:
    # candidates: [(doc_id, text)]
    headers = {"Authorization": f"Bearer {RERANKER_API_TOKEN}"} if RERANKER_API_TOKEN else {}
    payload = {
        "model": "bge-reranker-m2",
        "query": query,
        "documents": [c[1] for c in candidates],
    }
    resp = http_post(f"{RERANKER_API_URL}/rerank", payload, headers=headers)
    # Expected: { "data": [ {"index": idx, "score": ...}, ... ] } sorted by score desc
    order = [item["index"] for item in resp.get("data", [])]
    return order
