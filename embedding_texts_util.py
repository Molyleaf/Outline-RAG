import os
from typing import List
from app.http_client import http_post

EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "").rstrip("/")
EMBEDDING_API_TOKEN = os.getenv("EMBEDDING_API_TOKEN", "")

def embed_texts(texts: List[str]) -> List[List[float]]:
    # Expected request schema: { "model": "bge-m3", "input": [ ... ] }
    # Adapt to your provider; we keep a generic JSON.
    headers = {"Authorization": f"Bearer {EMBEDDING_API_TOKEN}"} if EMBEDDING_API_TOKEN else {}
    payload = {"model": "bge-m3", "input": texts}
    resp = http_post(f"{EMBEDDING_API_URL}/embeddings", payload, headers=headers)
    # Expected response: { "data": [ { "embedding": [..] }, ... ] }
    vecs = [item["embedding"] for item in resp.get("data", [])]
    return vecs
