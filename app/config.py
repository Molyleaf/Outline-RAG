# app/config.py
# 此文件集中管理所有从环境变量加载的配置项
import os

# --- 基本配置 ---
PORT = int(os.getenv("PORT", "8080"))
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "1024"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SECRET_KEY = os.getenv("SECRET_KEY", None)

# --- 数据库 ---
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

# --- Outline ---
OUTLINE_API_URL = os.getenv("OUTLINE_API_URL", "").rstrip("/")
OUTLINE_API_TOKEN = os.getenv("OUTLINE_API_TOKEN", "")
OUTLINE_WEBHOOK_SECRET = os.getenv("OUTLINE_WEBHOOK_SECRET", "").strip()
OUTLINE_WEBHOOK_SIGN = os.getenv("OUTLINE_WEBHOOK_SIGN", "true").lower() == "true"

# --- AI 服务 ---
EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "").rstrip("/")
EMBEDDING_API_TOKEN = os.getenv("EMBEDDING_API_TOKEN", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

RERANKER_API_URL = os.getenv("RERANKER_API_URL", "").rstrip("/")
RERANKER_API_TOKEN = os.getenv("RERANKER_API_TOKEN", "")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "bge-reranker-m2")

CHAT_API_URL = os.getenv("CHAT_API_URL", "").rstrip("/")
CHAT_API_TOKEN = os.getenv("CHAT_API_TOKEN", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "your-chat-model")

# --- System Prompt ---
DEFAULT_SYSTEM_PROMPT = """你是一个企业知识库助理。你正在回答RAG应用的问题。\n回答使用用户输入的语言。"""
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

# --- 多轮对话配置 ---
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20")) # 用于上下文的最大历史消息数 (用户+助手)

# 查询重写模板
DEFAULT_REWRITE_PROMPT_TEMPLATE = """根据下方提供的“对话历史”和“后续问题”，将“后续问题”改写为一个**完全独立、不依赖任何上下文**的完整问题。\n如果“后续问题”本身已经很完整，则直接返回它。\n\n对话历史:\n{history}\n\n后续问题:\n{query}\n\n重写后的独立问题:"""
REWRITE_PROMPT_TEMPLATE = os.getenv("REWRITE_PROMPT_TEMPLATE", DEFAULT_REWRITE_PROMPT_TEMPLATE)

# RAG 问答模板
DEFAULT_HISTORY_AWARE_PROMPT_TEMPLATE = """参考资料：\n{context}\n\n---\n请根据以上参考资料，并结合你的知识，回答以下问题：\n{query}"""
HISTORY_AWARE_PROMPT_TEMPLATE = os.getenv("HISTORY_AWARE_PROMPT_TEMPLATE", DEFAULT_HISTORY_AWARE_PROMPT_TEMPLATE)

# --- RAG/检索参数 ---
TOP_K = int(os.getenv("TOP_K", "12"))
K = int(os.getenv("K", "6"))
REFRESH_BATCH_SIZE = int(os.getenv("REFRESH_BATCH_SIZE", "100"))

# --- OIDC (GitLab) ---
GITLAB_CLIENT_ID = os.getenv("GITLAB_CLIENT_ID", "")
GITLAB_CLIENT_SECRET = os.getenv("GITLAB_CLIENT_SECRET", "")
GITLAB_URL = os.getenv("GITLAB_URL", "").rstrip("/")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")

# --- 功能开关与限制 ---
USE_JOSE_VERIFY = os.getenv("USE_JOSE_VERIFY", "true").lower() == "true"
SAFE_LOG_CHAT_INPUT = os.getenv("SAFE_LOG_CHAT_INPUT", "true").lower() == "true"
MAX_LOG_INPUT_CHARS = int(os.getenv("MAX_LOG_INPUT_CHARS", "4000"))
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "10485760"))  # 10MB
ALLOWED_FILE_EXTENSIONS = set([e.strip().lower() for e in os.getenv("ALLOWED_FILE_EXTENSIONS", "txt,md,pdf").split(",") if e.strip()])

# --- 持久化目录 ---
ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", "/app/data/attachments")
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/data/archive")
