# app/llm_services.py
import logging
import urllib.parse
from typing import Sequence, Any

import redis # 导入 *同步* redis 库
# ---
import httpx
from httpx import Response
from langchain_community.storage import RedisStore
from langchain_classic.embeddings.cache import CacheBackedEmbeddings
from langchain_core.documents import Document
from langchain_core.documents import BaseDocumentCompressor
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

import config

logger = logging.getLogger(__name__)

# --- (ASYNC REFACTOR) 1. 共享的 HTTP 客户端 (httpx) ---
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

# --- (不变) 2. 聊天模型 (LLM) ---
# (ChatOpenAI 自动支持 ainvoke/astream)
llm = ChatOpenAI(
    model=config.CHAT_MODEL,
    api_key=config.CHAT_API_TOKEN,
    base_url=f"{config.CHAT_API_URL}/v1",
)

# --- (ASYNC REFACTOR) 3. 嵌入模型 (Embedding) ---

# 3a. LangChain 缓存需要一个 *不* 解码响应 (decode_responses=False) 的 Redis 客户端
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

        # (*** 关键修复 ***)
        # LangChain 的 RedisStore 需要一个 *同步* 客户端实例。
        _redis_cache_client = redis.Redis(
            host=parsed_url.hostname,
            port=parsed_url.port,
            password=parsed_url.password,
            db=db_num,
            decode_responses=False # 缓存需要原始字节
        )
        # (*** 修复结束 ***)
    except Exception as e:
        logger.warning("无法为 LangChain 缓存连接到 Redis (decode=False, sync client): %s", e)
        _redis_cache_client = None

# 3b. 基础 Embedding API (不变)
# (OpenAIEmbeddings 自动支持 aembed_documents/aembed_query)
_base_embeddings = OpenAIEmbeddings(
    model=config.EMBEDDING_MODEL,
    api_key=config.EMBEDDING_API_TOKEN,
    base_url=f"{config.EMBEDDING_API_URL}/v1",
)

# 3c. 带缓存的 Embedding 模型
if _redis_cache_client:
    # (修改) RedisStore 现在接收一个同步客户端，这是它所期望的
    store = RedisStore(client=_redis_cache_client, namespace="embeddings")
    embeddings_model = CacheBackedEmbeddings.from_bytes_store(
        _base_embeddings, store, namespace=f"emb:{config.EMBEDDING_MODEL}"
    )
    logger.info("LangChain Embedding 缓存已启用 (Redis-SyncClient)")
else:
    embeddings_model = _base_embeddings
    logger.info("LangChain Embedding 缓存未启用")


# --- (ASYNC REFACTOR) 4. 重排模型 (Reranker) ---
class SiliconFlowReranker(BaseDocumentCompressor):
    """
    (ASYNC REFACTOR) 适配 SiliconFlow API 的异步 Reranker
    """
    model: str = config.RERANKER_MODEL
    api_url: str = f"{config.RERANKER_API_URL}/v1/rerank"
    api_token: str = config.RERANKER_API_TOKEN
    top_n: int = config.K

    client: httpx.AsyncClient = None
    logger: Any = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # (ASYNC REFACTOR)
        self.client = _create_retry_client()
        self.logger = logging.getLogger(self.__class__.__name__)

    # (ASYNC REFACTOR) 实现 acompress_documents
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
            # (ASYNC REFACTOR)
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

    # (保留) 同步方法，以防万一被调用（尽管我们不打算使用它）
    def compress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks=None,
    ) -> Sequence[Document]:
        self.logger.warning("SiliconFlowReranker.compress_documents (同步) 被调用，这不应该发生。")
        # 这是一个 hack，但在 RAG 链中不应发生
        # 在 FastAPI 中，我们不能轻易地从异步代码中调用同步 IO
        return []


# 实例化 Reranker (现在是异步感知的)
reranker = SiliconFlowReranker()