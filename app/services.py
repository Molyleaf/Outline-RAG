# app/services.py
# 封装了对所有外部 API (Embedding, Reranker, Chat, Outline) 的 HTTP 请求
import hashlib
import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from database import redis_client

logger = logging.getLogger(__name__)

def _create_retry_session():
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"], raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    # session.mount("http://", adapter)
    return session

def http_post_json(url, payload, token, stream=False):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    timeout = (5, 60) if not stream else (5, 300)
    session_req = _create_retry_session()
    try:
        resp = session_req.post(url, json=payload, headers=headers, timeout=timeout, stream=stream)
        if not (200 <= resp.status_code < 300):
            logger.warning(f"http_post_json non-2xx: {resp.status_code} for URL {url}")
            return None
        return resp if stream else resp.json()
    except requests.RequestException as e:
        logger.warning(f"http_post_json error for URL {url}: {e}")
        return None

def create_embeddings(texts):
    if not redis_client:
        payload = {"model": config.EMBEDDING_MODEL, "input": texts}
        res = http_post_json(f"{config.EMBEDDING_API_URL}/v1/embeddings", payload, config.EMBEDDING_API_TOKEN)
        if not res: return [[] for _ in texts]
        return [item.get("embedding", []) for item in res.get("data", [])]
    hashes = [f"emb:{hashlib.sha256(t.encode()).hexdigest()}" for t in texts]
    cached_results = {h: json.loads(v) for h, v in zip(hashes, redis_client.mget(hashes)) if v}
    miss_indices, miss_texts = [], []
    for i, (text, h) in enumerate(zip(texts, hashes)):
        if h not in cached_results:
            miss_indices.append(i)
            miss_texts.append(text)
    final_embeddings = [[]] * len(texts)
    for i, h in enumerate(hashes):
        if h in cached_results:
            final_embeddings[i] = cached_results[h]
    if miss_texts:
        payload = {"model": config.EMBEDDING_MODEL, "input": miss_texts}
        res = http_post_json(f"{config.EMBEDDING_API_URL}/v1/embeddings", payload, config.EMBEDDING_API_TOKEN)
        new_embeddings = [item.get("embedding", []) for item in (res.get("data", []) if res else [])]
        if new_embeddings:
            cache_pipe = redis_client.pipeline()
            for i, emb in enumerate(new_embeddings):
                original_index = miss_indices[i]
                final_embeddings[original_index] = emb
                cache_pipe.set(hashes[original_index], json.dumps(emb), ex=604800)
            cache_pipe.execute()
    return final_embeddings

def rerank(query, passages, top_k=5):
    cache_key = None  # 修复：在此处初始化变量以消除 Linter 警告
    if redis_client:
        stable_input = json.dumps({"query": query, "documents": sorted(passages)}, ensure_ascii=False)
        cache_key = f"rerank:{hashlib.sha256(stable_input.encode()).hexdigest()}"
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    payload = {"model": config.RERANKER_MODEL, "query": query, "documents": passages, "top_n": top_k}
    res = http_post_json(f"{config.RERANKER_API_URL}/v1/rerank", payload, config.RERANKER_API_TOKEN)
    if not res: return []
    items = res.get("results") or res.get("data") or []
    sorted_items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    if redis_client and sorted_items:
        redis_client.set(cache_key, json.dumps(sorted_items), ex=604800)
    return sorted_items

def chat_completion_stream(messages, model, temperature=None, top_p=None):
    if config.SAFE_LOG_CHAT_INPUT:
        try:
            preview = json.dumps(messages, ensure_ascii=False)
            if len(preview) > config.MAX_LOG_INPUT_CHARS:
                preview = preview[:config.MAX_LOG_INPUT_CHARS] + "...(truncated)"
            logger.info("chat_completion_stream input preview(len=%s)", len(preview))
        except Exception: pass
    payload = {"model": model or config.CHAT_MODEL, "messages": messages, "stream": True}
    if temperature is not None: payload["temperature"] = temperature
    if top_p is not None: payload["top_p"] = top_p
    return http_post_json(f"{config.CHAT_API_URL}/v1/chat/completions", payload, config.CHAT_API_TOKEN, stream=True)

# (新增) 阻塞式的 Chat Completion，用于查询重写
def chat_completion_blocking(messages, model, temperature=None, top_p=None):
    """执行一次非流式的聊天补全，并返回文本结果。"""
    payload = {"model": model or config.CHAT_MODEL, "messages": messages, "stream": False}
    if temperature is not None: payload["temperature"] = temperature
    if top_p is not None: payload["top_p"] = top_p

    res = http_post_json(f"{config.CHAT_API_URL}/v1/chat/completions", payload, config.CHAT_API_TOKEN, stream=False)

    if not res:
        logger.warning("chat_completion_blocking: API call failed or returned empty.")
        return None
    try:
        # 提取响应内容
        content = res.get("choices", [{}])[0].get("message", {}).get("content")
        return content.strip() if content else None
    except (IndexError, AttributeError, TypeError) as e:
        logger.error(f"chat_completion_blocking: Failed to parse response: {e} | Response: {res}")
        return None

def outline_headers():
    return {"Authorization": f"Bearer {config.OUTLINE_API_TOKEN}", "Content-Type": "application/json"}

def http_post_json_raw(url, payload, headers=None, session=None):
    session_req = session or _create_retry_session()
    try:
        resp = session_req.post(
            url, json=payload, headers=headers or {"Content-Type":"application/json"}, timeout=60
        )
        if not (200 <= resp.status_code < 300):
            logger.warning(f"http_post_json_raw non-2xx: {resp.status_code} for URL {url} - Body: {resp.text}")
            return None
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"http_post_json_raw error for URL {url}: {e}")
        return None

def outline_list_collections(session):
    u = f"{config.OUTLINE_API_URL}/api/collections.list"
    data = http_post_json_raw(u, {"limit": 100}, headers=outline_headers(), session=session)
    if not data or not data.get("data"):
        logger.error("无法从 Outline 获取知识库列表。")
        return []
    return data["data"]

def outline_list_docs():
    session = _create_retry_session()
    collections = outline_list_collections(session=session)
    if not collections:
        logger.warning("未找到任何知识库，或无法获取知识库列表。将返回空文档列表。")
        return []

    all_docs = {}
    for collection in collections:
        collection_id = collection.get("id")
        if not collection_id:
            continue

        docs_in_collection = []
        limit, offset = 100, 0
        u = f"{config.OUTLINE_API_URL}/api/documents.list"

        while True:
            payload = {"collectionId": collection_id, "limit": limit, "offset": offset}
            data = http_post_json_raw(u, payload, headers=outline_headers(), session=session)

            if not data:
                logger.warning(f"获取知识库 '{collection.get('name')}' 的一页文档失败。")
                break

            docs = data.get("data", [])
            docs_in_collection.extend(docs)

            if len(docs) < limit:
                break
            offset += limit

        for doc in docs_in_collection:
            if doc.get("id"):
                all_docs[doc['id']] = doc

    total_docs_list = list(all_docs.values())
    logger.info(f"从Outline API获取到 {len(total_docs_list)} 篇不重复的文档。")
    return total_docs_list

def outline_get_doc(doc_id):
    u = f"{config.OUTLINE_API_URL}/api/documents.info"
    data = http_post_json_raw(u, {"id": doc_id}, headers=outline_headers())
    return data.get("data") if data else None
