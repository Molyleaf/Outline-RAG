# app/outline_client.py
import hashlib
import hmac
import logging

import httpx
from httpx import Response
from httpx_retries import RetryTransport, Retry

import config

logger = logging.getLogger(__name__)

# --- HTTP 辅助函数 (httpx) ---
def _create_retry_client() -> httpx.AsyncClient:
    """创建带重试的 httpx.AsyncClient"""

    # 1. 定义 Retry 策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )

    # 2. 定义要包装的底层 transport (保留 http2)
    base_transport = httpx.AsyncHTTPTransport(http2=True)

    # 3. 使用 'transport' 参数
    transport = RetryTransport(
        retry=retry_strategy,
        transport=base_transport
    )

    # 4. 创建客户端
    client = httpx.AsyncClient(transport=transport, timeout=60)
    return client

async def http_post_json_raw(url, payload, headers=None, client: httpx.AsyncClient = None):
    """异步 POST"""
    should_close = False
    if client is None:
        client = _create_retry_client()
        should_close = True

    try:
        resp: Response = await client.post(
            url, json=payload, headers=headers or {"Content-Type":"application/json"}
        )
        if not (200 <= resp.status_code < 300):
            logger.warning(f"http_post_json_raw (async) non-2xx: {resp.status_code} for URL {url} - Body: {resp.text}")
            return None
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"http_post_json_raw (async) error for URL {url}: {e}")
        return None
    finally:
        if should_close:
            await client.aclose()

# --- Outline API 函数 ---
def outline_headers():
    return {"Authorization": f"Bearer {config.OUTLINE_API_TOKEN}", "Content-Type": "application/json"}

async def outline_list_collections(client: httpx.AsyncClient):
    u = f"{config.OUTLINE_API_URL}/api/collections.list"
    data = await http_post_json_raw(u, {"limit": 100}, headers=outline_headers(), client=client)
    if not data or not data.get("data"):
        logger.error("无法从 Outline 获取知识库列表。")
        return []
    return data["data"]

async def outline_list_docs():
    client = _create_retry_client()
    try:
        collections = await outline_list_collections(client=client)
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
                data = await http_post_json_raw(u, payload, headers=outline_headers(), client=client)

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
    finally:
        await client.aclose()


async def outline_get_doc(doc_id):
    u = f"{config.OUTLINE_API_URL}/api/documents.info"
    data = await http_post_json_raw(u, {"id": doc_id}, headers=outline_headers())
    return data.get("data") if data else None

# --- Webhook 验证 ---
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