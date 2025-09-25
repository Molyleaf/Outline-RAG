from __future__ import annotations
import os
import math
from typing import List, Dict, Any, Tuple
from sqlalchemy import text
from app.db import session_scope, engine
from app.models import embedding_dim

def upsert_document(doc: Dict[str, Any], embedding: List[float]):
    with session_scope() as s:
        sql = text("""
            INSERT INTO documents (id, title, slug, collection_id, updated_at, url, content, embedding)
            VALUES (:id, :title, :slug, :collection_id, :updated_at, :url, :content, :embedding)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                slug = EXCLUDED.slug,
                collection_id = EXCLUDED.collection_id,
                updated_at = EXCLUDED.updated_at,
                url = EXCLUDED.url,
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding
        """)
        s.execute(sql, {
            "id": doc["id"],
            "title": doc.get("title") or "",
            "slug": doc.get("urlId") or doc.get("slug") or "",
            "collection_id": doc.get("collectionId") or "",
            "updated_at": doc.get("updatedAt"),
            "url": doc.get("url") or "",
            "content": doc.get("text") or doc.get("content") or "",
            "embedding": embedding,
        })

def replace_all_documents(rows: List[Dict[str, Any]], embeddings: List[List[float]]):
    with session_scope() as s:
        s.execute(text("TRUNCATE documents RESTART IDENTITY"))
        for doc, emb in zip(rows, embeddings):
            s.execute(text("""
                INSERT INTO documents (id, title, slug, collection_id, updated_at, url, content, embedding)
                VALUES (:id, :title, :slug, :collection_id, :updated_at, :url, :content, :embedding)
            """), {
                "id": doc["id"],
                "title": doc.get("title") or "",
                "slug": doc.get("urlId") or doc.get("slug") or "",
                "collection_id": doc.get("collectionId") or "",
                "updated_at": doc.get("updatedAt"),
                "url": doc.get("url") or "",
                "content": doc.get("text") or doc.get("content") or "",
                "embedding": emb,
            })

def search_by_embedding(query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
    # Cosine distance using pgvector: 1 - cosine_similarity
    sql = text(f"""
        SELECT id, title, url, content, 1 - (embedding <#> :q::vector) AS score
        FROM documents
        ORDER BY embedding <#> :q::vector
        LIMIT :k
    """)
    with session_scope() as s:
        res = s.execute(sql, {"q": query_embedding, "k": top_k}).mappings().all()
        return [dict(r) for r in res]

def get_documents_by_ids(ids: List[str]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    sql = text("""
        SELECT id, title, url, content FROM documents WHERE id = ANY(:ids)
    """)
    with session_scope() as s:
        res = s.execute(sql, {"ids": ids}).mappings().all()
        return [dict(r) for r in res]
