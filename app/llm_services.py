# app/llm_services.py
import hashlib
import logging
from typing import Sequence, Any, List, Tuple

import httpx
from httpx import Response
from httpx_retries import RetryTransport, Retry
from langchain_classic.embeddings.cache import CacheBackedEmbeddings
from langchain_community.storage import SQLStore
from langchain_core.documents import BaseDocumentCompressor
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
import tiktoken
from sqlalchemy.dialects.postgresql import insert as pg_insert

import config
from database import async_engine

logger = logging.getLogger(__name__)

# --- (新增) 修复：并发安全的 SQLStore ---
class IdempotentSQLStore(SQLStore):
    """
    一个 SQLStore 子类，它重写 'amset' 方法
    以使用 'INSERT ... ON CONFLICT DO NOTHING'。

    这解决了在并发工作进程 (concurrent workers) 尝试
    为缓存写入相同 embedding key 时
    发生的 race condition (竞态条件) 和 UniqueViolation 错误。
    """

    # (*** 修复 ***)
    # 显式添加 __init__ 以确保父类 SQLStore 的 __init__ 被调用，
    # 它负责设置 self._serializer 和 self._deserializer。
    #
    # 尽管 Python 应该在子类没有 __init__ 的情况下自动调用
    # 父类的 __init__，但我们在这里显式添加它以修复
    # 'AttributeError: ... has no attribute '_serializer'' 错误。
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

    async def amset(self, key_value_pairs: List[Tuple[str, Any]]) -> None:
        """
        异步设置键值对，安全地忽略主键冲突。
        """
        if not key_value_pairs:
            return

        try:
            # 序列化值
            serialized_pairs = [
                {
                    "key": k,
                    "value": self._serializer(v), # self._serializer 在 SQLStore 中定义
                    "namespace": self.namespace
                }
                for k, v in key_value_pairs
            ]

            # 创建 'INSERT ...' 语句 (self.table 在 SQLStore __init__ 中定义)
            stmt = pg_insert(self.table).values(serialized_pairs)

            # 添加 'ON CONFLICT (key, namespace) DO NOTHING'
            # 这依赖于 database.py 中定义的复合主键
            safe_stmt = stmt.on_conflict_do_nothing(
                index_elements=['key', 'namespace']
            )

            async with self.engine.begin() as conn:
                await conn.execute(safe_stmt)

        except Exception as e:
            # 这是一个缓存写入，记录错误但不要让整个 RAG 链失败
            logger.warning(f"IdempotentSQLStore amset failed (non-fatal): {e}", exc_info=True)

    def mset(self, key_value_pairs: List[Tuple[str, Any]]) -> None:
        """
        同步 set (不应在 async 应用中调用)。
        """
        logger.warning("IdempotentSQLStore.mset (sync) was called. This should be avoided in an async app.")
        try:
            with self.engine.begin() as conn:
                for k, v in key_value_pairs:
                    stmt = pg_insert(self.table).values(
                        key=k, value=self._serializer(v), namespace=self.namespace
                    )
                    safe_stmt = stmt.on_conflict_do_nothing(
                        index_elements=['key', 'namespace']
                    )
                    conn.execute(safe_stmt)
        except Exception as e:
            logger.warning(f"IdempotentSQLStore mset (sync) failed (non-fatal): {e}", exc_info=True)
# --- 修复结束 ---


# 预加载 tiktoken tokenizer
# OpenAIEmbeddings 会在 *首次* 异步调用时 *同步* 下载
# cl100k_base.tiktoken，这会导致在 asyncio 事件循环中
# 发生阻塞 I/O，引发死锁。
# 我们在模块加载时 (Uvicorn worker 启动时) 强制
# 同步下载它，以避免在异步任务中触发此问题。
try:
    logger.info("Pre-caching tiktoken tokenizer model (cl100k_base)...")
    tiktoken.get_encoding("cl100k_base")
    logger.info("Tiktoken model (cl100k_base) is cached.")
except Exception as e:
    logger.warning("Failed to pre-cache tiktoken model: %s", e)

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

# 3b. 基础 Embedding API
_base_embeddings = OpenAIEmbeddings(
    model=config.EMBEDDING_MODEL,
    api_key=config.EMBEDDING_API_TOKEN,
    base_url=f"{config.EMBEDDING_API_URL}/v1",
    chunk_size=64
)

# 3c. 带缓存的 Embedding 模型
# 3c. 带缓存的 Embedding 模型 (*** 修复 ***)
# 使用 SQLStore 替换 RedisStore 来解决 sync/async 冲突
store = None
try:
    if not async_engine:
        raise ValueError("database.py 中的 async_engine 不可用")

    # 1. 实例化 (并发安全的) IdempotentSQLStore，用于 Embedding 缓存
    #    我们重用 database.py 中定义的 'langchain_key_value_stores' 表
    #    但使用一个唯一的 namespace。
    store = IdempotentSQLStore(
        engine=async_engine,
        namespace="embedding_cache", # <--- 为 embedding cache 使用一个唯一的 namespace
    )

    # 2. 创建带缓存的模型
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