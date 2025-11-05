# app/outline_client.py
# 封装了对 Outline API 的所有 HTTP 请求
import hashlib
import hmac
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)

# --- HTTP 辅助函数 (源自 services.py) ---
def _create_retry_session():
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"], raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session

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

# --- Outline API 函数 (源自 services.py) ---
def outline_headers():
    return {"Authorization": f"Bearer {config.OUTLINE_API_TOKEN}", "Content-Type": "application/json"}

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

# --- Webhook 验证 (源自 rag.py) ---
def verify_outline_signature(raw_body, signature_hex: str) -> bool:
    if not config.OUTLINE_WEBHOOK_SIGN: return True
    try:
        sig = (signature_hex or "").strip()
        if sig.lower().startswith("sha256="): sig = sig.split("=", 1)[1].strip()
        if sig.lower().startswith("bearer "): sig = sig.split(" ", 1)[1].strip()
        mac = hmac.new(config.OUTLINE_WEBHOOK_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), sig)
    except Exception as e:
        logger.warning("verify_outline_signature error: %s", e)
        return False