# services.py
# 封装了对所有外部 API (Embedding, Reranker, Chat, Outline) 的 HTTP 请求
import json
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib.request
import config

logger = logging.getLogger(__name__)

# --- OpenAI 兼容服务调用 ---
def http_post_json(url, payload, token, stream=False):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    timeout = (5, 60) if not stream else (5, 300)
    session_req = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"], raise_on_status=False,
    )
    session_req.mount("https://", HTTPAdapter(max_retries=retry))
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
    payload = {"model": config.EMBEDDING_MODEL, "input": texts}
    res = http_post_json(f"{config.EMBEDDING_API_URL}/v1/embeddings", payload, config.EMBEDDING_API_TOKEN)
    if not res: return [[] for _ in texts]
    return [item.get("embedding", []) for item in res.get("data", [])]

def rerank(query, passages, top_k=5):
    payload = {"model": config.RERANKER_MODEL, "query": query, "documents": passages, "top_n": top_k}
    res = http_post_json(f"{config.RERANKER_API_URL}/v1/rerank", payload, config.RERANKER_API_TOKEN)
    if not res: return []
    items = res.get("results") or res.get("data") or []
    return sorted(items, key=lambda x: x.get("score", 0), reverse=True)

def chat_completion_stream(messages, temperature=0.2):
    if config.SAFE_LOG_CHAT_INPUT:
        try:
            preview = json.dumps(messages, ensure_ascii=False)
            if len(preview) > config.MAX_LOG_INPUT_CHARS:
                preview = preview[:config.MAX_LOG_INPUT_CHARS] + "...(truncated)"
            logger.info("chat_completion_stream input preview(len=%s)", len(preview))
        except Exception: pass
    payload = {"model": config.CHAT_MODEL, "messages": messages, "temperature": temperature, "stream": True}
    return http_post_json(f"{config.CHAT_API_URL}/v1/chat/completions", payload, config.CHAT_API_TOKEN, stream=True)

# --- Outline API 调用 ---
def outline_headers():
    return {"Authorization": f"Bearer {config.OUTLINE_API_TOKEN}", "Content-Type":"application/json"}

def http_post_json_raw(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers or {"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning(f"http_post_json_raw error for URL {url}: {e}")
        return None

def outline_list_docs():
    results = []
    limit, offset = 100, 0
    while True:
        u = f"{config.OUTLINE_API_URL}/api/documents.list?limit={limit}&offset={offset}"
        data = http_post_json_raw(u, {}, headers=outline_headers())
        if not data: break
        docs = data.get("data", [])
        results.extend(docs)
        if len(docs) < limit: break
        offset += limit
    return results

def outline_get_doc(doc_id):
    u = f"{config.OUTLINE_API_URL}/api/documents.info"
    data = http_post_json_raw(u, {"id": doc_id}, headers=outline_headers())
    return data.get("data") if data else None