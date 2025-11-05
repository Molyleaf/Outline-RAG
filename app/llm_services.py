# app/llm_services.py
import logging
import urllib.parse
from typing import Sequence, Any
import hashlib

import redis
import redis.asyncio as aredis
import httpx
from httpx import Response
from langchain_community.storage import RedisStore
from langchain_classic.embeddings.cache import CacheBackedEmbeddings
from langchain_core.documents import Document
from langchain_core.documents import BaseDocumentCompressor
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)

# (*** 关键修复 ***)
# 将 namespace 移入 key_encoder 中
# 1. 定义缓存键的前缀（之前在 'namespace' 参数中）
_cache_prefix = f"emb:{config.EMBEDDING_MODEL}"

def _sha256_encoder(s: str) -> str:
    """
    将输入文本编码为 SHA-256 哈希，并附加模型特定的前缀。
    """
    # 1. 计算文本内容的哈希
    hash_id = hashlib.sha256(s.encode()).hexdigest()
    # 2. 返回 命名空间前缀:哈希值 作为最终的键
    return f"{_cache_prefix}:{hash_id}"
# (*** 修复结束 ***)

# --- 1. 共享的 HTTP 客户端 (httpx) ---
def _create_retry_client() -> httpx.AsyncClient:
    """创建带重试的 httpx.AsyncClient"""
    retry_strategy = httpx.Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )
    transport = httpx.AsyncHTTPTransport(retries=retry_strategy)
    client = httpx.AsyncClient(transport=transport)
    return client

# --- 2. 聊天模型 (LLM) ---
llm = ChatOpenAI(
    model=config.CHAT_MODEL,
    api_key=config.CHAT_API_TOKEN,
    base_url=f"{config.CHAT_API_URL}/v1",
)

# --- 3. 嵌入模型 (Embedding) ---

# 3a. ... (不变) ...
_redis_cache_client = None
if config.REDIS_URL:
    try:
        parsed_url = urllib.parse.urlparse(config.REDIS_URL)
        db_num = 0
        if parsed_url.path and parsed_url.path.startswith('/'):
            try:
                db_num = int(parsed_url.path[1:])
            except (ValueError, IndexError):
                db_num = 0

        _redis_cache_client = redis.Redis(
            host=parsed_url.hostname,
            port=parsed_url.port,
            password=parsed_url.password,
            db=db_num,
            decode_responses=False
        )
    except Exception as e:
        logger.warning("无法为 LangChain 缓存连接到 Redis (decode=False, sync client): %s", e)
        _redis_cache_client = None

# 3b. ... (不变) ...
_base_embeddings = OpenAIEmbeddings(
    model=config.EMBEDDING_MODEL,
    api_key=config.EMBEDDING_API_TOKEN,
    base_url=f"{config.EMBEDDING_API_URL}/v1",
)

# 3c. 带缓存的 Embedding 模型
if _redis_cache_client:
    # 'store' 仍然可以使用它自己的 'namespace'（例如 "embeddings"）
    # 这与 CacheBackedEmbeddings 的键是分开的。
    store = RedisStore(client=_redis_cache_client, namespace="embeddings")

    embeddings_model = CacheBackedEmbeddings.from_bytes_store(
        _base_embeddings,
        store,
        # (*** 关键修复 ***)
        # 移除 'namespace' 参数，因为它现在已包含在 'key_encoder' 中
        key_encoder=_sha256_encoder
    )
    logger.info("LangChain Embedding 缓存已启用 (Redis-SyncClient, SHA256+Prefix)")
else:
    embeddings_model = _base_embeddings
    logger.info("LangChain Embedding 缓存未启用")


# --- 4. 重排模型 (Reranker) ---
class SiliconFlowReranker(BaseDocumentCompressor):
    model: str = config.RERANKER_MODEL
    api_url: str = f"{config.RERANKER_API_URL}/v1/rerank"
    api_token: str = config.RERANKER_API_TOKEN
    top_n: int = config.K

    client: httpx.AsyncClient = None
    logger: Any = None

    # (修复 Pydantic 错误 - 保持不变)
    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = _create_retry_client()
        self.logger = logging.getLogger(self.__class__.__name__)

    # ... (SiliconFlowReranker 的其余部分保持不变) ...
    async def acompress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks=None,
    ) -> Sequence[Document]:

        if not documents:
            return []

        doc_texts = [doc.page_content for doc in documents]

        payload = {
            "model": self.model,
            "query": query,
            "documents": doc_texts,
            "top_n": self.top_n,
            "return_documents": True
        }
        headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}

        try:
            resp: Response = await self.client.post(self.api_url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            self.logger.warning(f"SiliconFlowReranker API (async) 调用失败: {e}")
            return []

        results = data.get("results")
        if not results:
            return []

        final_docs = []
        for res in sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True):
            original_index = res.get("index")
            if original_index is not None and 0 <= original_index < len(documents):
                new_doc = Document(
                    page_content=res.get("document", doc_texts[original_index]),
                    metadata=documents[original_index].metadata.copy()
                )
                new_doc.metadata["relevance_score"] = res.get("relevance_score")
                final_docs.append(new_doc)

        return final_docs

    def compress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks=None,
    ) -> Sequence[Document]:
        self.logger.warning("SiliconFlowReranker.compress_documents (同步) 被调用，这不应该发生。")
        return []

# 实例化 Reranker (现在是异步感知的)
reranker = SiliconFlowReranker()