# app/llm_services.py
import hashlib
import logging
from typing import Sequence, Any, List, Tuple

import httpx
import tiktoken
from httpx import Response
from httpx_retries import RetryTransport, Retry
from langchain.embeddings.cache import CacheBackedEmbeddings
from langchain_community.cache import AsyncRedisCache
from langchain_community.storage.sql import SQLStore, LangchainKeyValueStores
from langchain_core.documents import BaseDocumentCompressor
from langchain_core.documents import Document
from langchain_siliconflow.chat_models import ChatSiliconFlow
from langchain_siliconflow.embeddings import SiliconFlowEmbeddings
from sqlalchemy.dialects.postgresql import insert as pg_insert

import config
from database import async_engine, redis_client

logger = logging.getLogger(__name__)


class IdempotentSQLStore(SQLStore):
    """
    一个 SQLStore 子类，它重写 'amset' 方法
    以使用 'INSERT ... ON CONFLICT DO NOTHING'。

    这解决了在并发工作进程 (concurrent workers) 尝试
    为缓存写入相同 embedding key 时
    发生的 race condition (竞态条件) 和 UniqueViolation 错误。
    """

    def __init__(self, **kwargs: Any):
        # 1. 确保序列化器为 None，因为我们用于 bytes 存储
        #    (CacheBackedEmbeddings.from_bytes_store)
        #    SQLStore (v0.2.1+) 的 __init__ 不接受这些参数，
        #    所以我们必须在调用 super() 之前将它们移除。
        kwargs.pop('serializer', None)
        kwargs.pop('deserializer', None)

        # 2. pop 出 'value_serializer' (如果存在)，
        #    (这是从 EncoderBackedStore (rag.py) 错误复制来的)
        kwargs.pop('value_serializer', None)
        kwargs.pop('value_deserializer', None)

        # 3. 调用父类 __init__
        #    父类 (SQLStore 0.2.1+) 将收到 engine, namespace,
        #    并且不会收到意外的参数。
        super().__init__(**kwargs)

        # (注意：SQLStore 0.2.1+ 不会设置 self._table，这是正常的)

    async def amset(self, key_value_pairs: List[Tuple[str, Any]]) -> None:
        """
        异步设置键值对，安全地忽略主键冲突。
        """
        if not key_value_pairs:
            return

        try:
            # 'v' 已经是 bytes (来自 CacheBackedEmbeddings)
            serialized_pairs = [
                {
                    "key": k,
                    "value": v,  # 直接使用 v (bytes)
                    "namespace": self.namespace
                }
                for k, v in key_value_pairs
            ]

            # 不使用 self._table，而是使用从 langchain_community.storage.sql
            # 导入的 LangchainKeyValueStores ORM 模型类。
            stmt = pg_insert(LangchainKeyValueStores).values(serialized_pairs)

            safe_stmt = stmt.on_conflict_do_nothing(
                # 主键是 (key, namespace)
                index_elements=['key', 'namespace']
            )

            # self.engine 是由父类 SQLStore.__init__ 设置的
            async with self.engine.begin() as conn:
                await conn.execute(safe_stmt)

        except Exception as e:
            logger.warning(f"IdempotentSQLStore amset failed (non-fatal): {e}", exc_info=True)

    def mset(self, key_value_pairs: List[Tuple[str, Any]]) -> None:
        """
        同步 set (不应在 async 应用中调用)。
        """
        logger.warning("IdempotentSQLStore.mset (sync) was called. This should be avoided in an async app.")
        try:
            # 'v' 已经是 bytes。
            with self.engine.begin() as conn:
                for k, v in key_value_pairs:
                    # 同样，使用 LangchainKeyValueStores 模型类
                    stmt = pg_insert(LangchainKeyValueStores).values(
                        key=k, value=v, namespace=self.namespace  # 直接使用 v (bytes)
                    )
                    safe_stmt = stmt.on_conflict_do_nothing(
                        index_elements=['key', 'namespace']
                    )
                    conn.execute(safe_stmt)
        except Exception as e:
            logger.warning(f"IdempotentSQLStore mset (sync) failed (non-fatal): {e}", exc_info=True)


# 预加载 tiktoken tokenizer
try:
    logger.info("Pre-caching tiktoken tokenizer model (cl100k_base)...")
    tiktoken.get_encoding("cl100k_base")
    logger.info("Tiktoken model (cl100k_base) is cached.")
except Exception as e:
    logger.warning("Failed to pre-cache tiktoken model: %s", e)

_cache_prefix = f"emb:{config.EMBEDDING_MODEL}"


def _sha256_encoder(s: str) -> str:
    """
    将输入文本编码为 SHA-256 哈希，并附加模型特定的前缀。
    """
    hash_id = hashlib.sha256(s.encode()).hexdigest()
    return f"{_cache_prefix}:{hash_id}"


def _create_retry_client() -> httpx.AsyncClient:
    """创建带 httpx-retries 的 AsyncClient"""
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
    )
    base_transport = httpx.AsyncHTTPTransport()
    transport = RetryTransport(
        retry=retry_strategy,
        transport=base_transport
    )
    client = httpx.AsyncClient(transport=transport)
    return client


# --- 聊天模型 (LLM) ---

# [--- 更改：显式传递 Chat Model 参数 ---]
# 依赖环境变量的 `default_factory` 在 Gunicorn/Uvicorn
# 启动时不可靠。我们必须显式传递参数。
llm = ChatSiliconFlow(
    model=config.CHAT_MODEL,
    api_key=config.SILICONFLOW_API_KEY,
    base_url=f"{config.SILICONFLOW_BASE_URL.rstrip('/')}/v1"
)
# [--- 更改结束 ---]


# --- 启用 LLM 异步缓存 ---
if redis_client:
    try:
        # 你可以根据需要调整 ttl (Time-To-Live)，单位为秒
        # 例如：ttl=3600 表示缓存 1 小时
        llm_cache = AsyncRedisCache(
            redis_=redis_client,
            ttl=3600
        )
        llm.cache = llm_cache
        logger.info("LLM 异步缓存已启用 (AsyncRedisCache, TTL=3600s)。")
    except Exception as e:
        logger.warning(f"无法配置 AsyncRedisCache: {e}", exc_info=True)
else:
    logger.info("Redis 未配置，LLM 缓存未启用。")

# --- 嵌入模型 (Embedding) ---
# [--- 显式传递 Embedding Model 参数 ---]
# `SiliconFlowEmbeddings` 的 Pydantic 验证器 (v0.1.3) 会在模型初始化前
# 运行 `utils.validate_environment`。
# 此函数会读取 'base_url' 或 'SILICONFLOW_BASE_URL' 环境变量
# 来 *重新创建* 'client' 和 'async_client'。
#
# 为了确保在 Gunicorn/Uvicorn 等环境中正确使用 .cn 地址，
# 我们 *必须* 显式地将 `base_url` 传递给构造函数。
# 这样验证器就会使用我们传入的 `base_url`，而不是
# 尝试读取可能不可靠的环境变量。
#
# (这与 ChatSiliconFlow 不同，ChatSiliconFlow 的验证器
# 不会自动添加 /v1，但 SiliconFlowEmbeddings 的验证器会。)

# 从 config.py 中读取标准变量
_siliconflow_api_key = config.SILICONFLOW_API_KEY
# 我们传递 *不带* /v1 的 base_url，
# 因为 `utils.validate_environment` 会自动为我们添加 /v1。
_siliconflow_base_url_for_embeddings = config.SILICONFLOW_BASE_URL.rstrip('/')

# [--- 更改开始 ---]
# 删除手动创建的 `_embedding_client` 和 `_embedding_async_client`

# 将 `base_url` 显式注入 SiliconFlowEmbeddings 构造函数
_base_embeddings = SiliconFlowEmbeddings(
    model=config.EMBEDDING_MODEL,
    # 显式传递 base_url 和 api_key
    base_url=_siliconflow_base_url_for_embeddings, # type: ignore
    siliconflow_api_key=_siliconflow_api_key
    # 验证器将使用这些值自动创建
    # 正确的 'client' 和 'async_client'
) # type: ignore

store = None
try:
    if not async_engine:
        raise ValueError("database.py 中的 async_engine 不可用")

    store = IdempotentSQLStore(
        engine=async_engine,
        namespace="embedding_cache",
    )

    embeddings_model = CacheBackedEmbeddings.from_bytes_store(
        _base_embeddings,
        store,
        key_encoder=_sha256_encoder
    )

    embeddings_model.key_encoder = _sha256_encoder

    logger.info("LangChain Embedding 缓存已启用 (SQLStore-Async, SHA256+Prefix, namespace='embedding_cache')")

except Exception as e:
    logger.warning("无法为 LangChain 缓存配置 SQLStore: %s", e, exc_info=True)
    embeddings_model = _base_embeddings
    logger.info("LangChain Embedding 缓存未启用 (SQLStore 初始化失败)")


# --- 重排模型 (Reranker) ---
class SiliconFlowReranker(BaseDocumentCompressor):
    """
    适配 SiliconFlow API 的异步 Reranker
    """
    model: str = config.RERANKER_MODEL
    # 使用新的标准环境变量
    api_url: str = f"{config.SILICONFLOW_BASE_URL.rstrip('/')}/v1/rerank"
    api_token: str = config.SILICONFLOW_API_KEY
    top_n: int = config.K

    client: httpx.AsyncClient = None
    logger: Any = None

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
                doc_content_raw = res.get("document", doc_texts[original_index])
                if isinstance(doc_content_raw, dict):
                    page_content = doc_content_raw.get("text", "")
                else:
                    page_content = str(doc_content_raw)

                new_doc = Document(
                    page_content=page_content,
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


reranker = SiliconFlowReranker()