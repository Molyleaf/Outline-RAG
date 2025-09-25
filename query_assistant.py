from __future__ import annotations
import os
from typing import Dict, Any, List, Tuple
from app.embeddings import embed_texts
from app.repo import search_by_embedding, get_documents_by_ids
from app.reranker import rerank
from app.chat_model import chat_generate

TOP_K = int(os.getenv("TOP_K", "8"))
RERANK_K = int(os.getenv("RERANK_K", "5"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))

def build_context(docs: List[Dict[str, Any]]) -> str:
    buf = []
    total = 0
    for d in docs:
        chunk = f"# {d['title']}\n{d['content']}\n\n"
        if total + len(chunk) > MAX_CONTEXT_CHARS:
            break
        buf.append(chunk)
        total += len(chunk)
    return "\n".join(buf)

def answer_query(query: str) -> Dict[str, Any]:
    qv = embed_texts([query])[0]
    candidates = search_by_embedding(qv, TOP_K)
    pairs = [(c["id"], f"{c['title']}\n{c['content']}") for c in candidates]
    order = rerank(query, pairs) if pairs else []
    selected = [candidates[i] for i in order[:RERANK_K] if i < len(candidates)] if order else candidates[:RERANK_K]
    context = build_context(selected)
    system_prompt = "You are a helpful assistant. Use the provided context delimited by <context> tags to answer. If the answer is not in context, say you don't know.\n<context>\n" + context + "\n</context>"
    content = chat_generate(system_prompt, [{"role": "user", "content": query}])
    return {
        "answer": content,
        "sources": [{"id": d["id"], "title": d["title"], "url": d.get("url","")} for d in selected],
    }
