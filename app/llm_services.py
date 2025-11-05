# app/llm_services.py
import logging
import requests
import urllib.parse
import redis
from typing import List, Sequence

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.documents import Document
from langchain.retrievers.document_compressors.base import BaseDocumentTransformer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from langchain.storage import RedisStore
from langchain.embeddings import CacheBackedEmbeddings

import config

logger = logging.getLogger(__name__)

# --- 1. 共享的 HTTP 客户端 ---
def _create_retry_session():
    """
    创建带重试的 requests.Session，复用自原 services.py
    """
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"], raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session

# --- 2. 聊天模型 (LLM) ---
llm = ChatOpenAI(
    model=config.CHAT_MODEL,
    api_key=config.CHAT_API_TOKEN,
    base_url=f"{config.CHAT_API_URL}/v1",
)

# --- 3. 嵌入模型 (Embedding) ---

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

        _redis_cache_client = redis.Redis(
            host=parsed_url.hostname,
            port=parsed_url.port,
            password=parsed_url.password,
            db=db_num,
            decode_responses=False # 必须为 False
        )
        _redis_cache_client.ping()
    except Exception as e:
        logger.warning("无法为 LangChain 缓存连接到 Redis (decode=False): %s", e)
        _redis_cache_client = None

# 3b. 基础 Embedding API (Qwen/Qwen3-Embedding-0.6B)
_base_embeddings = OpenAIEmbeddings(
    model=config.EMBEDDING_MODEL,
    api_key=config.EMBEDDING_API_TOKEN,
    base_url=f"{config.EMBEDDING_API_URL}/v1",
)

# 3c. 带缓存的 Embedding 模型
if _redis_cache_client:
    store = RedisStore(client=_redis_cache_client, namespace="embeddings")
    embeddings_model = CacheBackedEmbeddings.from_bytes_store(
        _base_embeddings, store, namespace=f"emb:{config.EMBEDDING_MODEL}"
    )
    logger.info("LangChain Embedding 缓存已启用 (Redis)")
else:
    embeddings_model = _base_embeddings
    logger.info("LangChain Embedding 缓存未启用")


# --- 4. 重排模型 (Reranker) ---
class SiliconFlowReranker(BaseDocumentTransformer):
    """
    自定义 LangChain Reranker，适配 SiliconFlow 的 API
    (Qwen/Qwen3-Reranker-0.6B)
    """
    model: str = config.RERANKER_MODEL
    api_url: str = f"{config.RERANKER_API_URL}/v1/rerank"
    api_token: str = config.RERANKER_API_TOKEN
    top_n: int = config.K

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = _create_retry_session()
        self.logger = logging.getLogger(self.__class__.__name__)

    def compress_documents(
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
            "return_documents": True # 确保 API 返回文档内容
        }
        headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}

        try:
            resp = self.client.post(self.api_url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self.logger.warning(f"SiliconFlowReranker API 调用失败: {e}")
            return []

        results = data.get("results")
        if not results:
            return []

        final_docs = []
        for res in sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True):
            original_index = res.get("index")
            if original_index is not None and 0 <= original_index < len(documents):
                # 从原始文档复制元数据
                new_doc = Document(
                    page_content=res.get("document", doc_texts[original_index]),
                    metadata=documents[original_index].metadata.copy()
                )
                # 添加 reranker 分数
                new_doc.metadata["relevance_score"] = res.get("relevance_score")
                final_docs.append(new_doc)

        return final_docs

# 实例化 Reranker
reranker = SiliconFlowReranker()