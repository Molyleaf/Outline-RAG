# app/llm_services.py
import logging
import urllib.parse
from typing import Sequence, Any
import hashlib

import redis
import httpx
from httpx import Response
from httpx_retries import RetryTransport, Retry
from langchain_community.storage import RedisStore
from langchain_classic.embeddings.cache import CacheBackedEmbeddings
from langchain_core.documents import Document
from langchain_core.documents import BaseDocumentCompressor
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

import config

logger = logging.getLogger(__name__)

# --- 缓存键配置 ---
_cache_prefix = f"emb:{config.EMBEDDING_MODEL}"

def _sha256_encoder(s: str) -> str:
    """
    将输入文本编码为 SHA-256 哈希，并附加模型特定的前缀。
    """
    hash_id = hashlib.sha256(s.encode()).hexdigest()
    return f"{_cache_prefix}:{hash_id}"

# --- 共享的 HTTP 客户端 (httpx) ---
def _create_retry_client() -> httpx.AsyncClient:
    """创建带 httpx-retries 的 AsyncClient"""

    # 1. 定义 Retry 策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )

    # 2. 定义要包装的底层 transport (默认)
    base_transport = httpx.AsyncHTTPTransport()

    # 3. 使用 'transport' 参数
    transport = RetryTransport(
        retry=retry_strategy,
        transport=base_transport
    )

    # 4. 创建客户端
    client = httpx.AsyncClient(transport=transport)
    return client

# --- 聊天模型 (LLM) ---
llm = ChatOpenAI(
    model=config.CHAT_MODEL,
    api_key=config.CHAT_API_TOKEN,
    base_url=f"{config.CHAT_API_URL}/v1",
)

# --- 嵌入模型 (Embedding) ---

# 3a. (同步) Redis 客户端 (仅用于 LangChain 缓存)
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
        )
    except Exception as e:
        logger.warning("无法为 LangChain 缓存连接到 Redis (decode=False, sync client): %s", e)
        _redis_cache_client = None

# 3b. 基础 Embedding API
_base_embeddings = OpenAIEmbeddings(
    model=config.EMBEDDING_MODEL,
    api_key=config.EMBEDDING_API_TOKEN,
    base_url=f"{config.EMBEDDING_API_URL}/v1",
    chunk_size=64
)

# 3c. 带缓存的 Embedding 模型
if _redis_cache_client:
    store = RedisStore(client=_redis_cache_client, namespace="embeddings")

    embeddings_model = CacheBackedEmbeddings.from_bytes_store(
        _base_embeddings,
        store,
        key_encoder=_sha256_encoder
    )
    logger.info("LangChain Embedding 缓存已启用 (Redis-SyncClient, SHA256+Prefix)")
else:
    embeddings_model = _base_embeddings
    logger.info("LangChain Embedding 缓存未启用")


# --- 重排模型 (Reranker) ---
class SiliconFlowReranker(BaseDocumentCompressor):
    """
    适配 SiliconFlow API 的异步 Reranker
    """
    model: str = config.RERANKER_MODEL
    api_url: str = f"{config.RERANKER_API_URL}/v1/rerank"
    api_token: str = config.RERANKER_API_TOKEN
    top_n: int = config.K

    client: httpx.AsyncClient = None
    logger: Any = None

    # 修复 PydanticSchemaGenerationError
    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = _create_retry_client()
        self.logger = logging.getLogger(self.__class__.__name__)

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

                # 检查 Reranker 返回的是 dict (如 {'text': '...'}) 还是 str
                doc_content_raw = res.get("document", doc_texts[original_index])
                if isinstance(doc_content_raw, dict):
                    page_content = doc_content_raw.get("text", "")
                else:
                    page_content = str(doc_content_raw)

                new_doc = Document(
                    page_content=page_content, # 使用修复后的 page_content
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

# 实例化 Reranker
reranker = SiliconFlowReranker()