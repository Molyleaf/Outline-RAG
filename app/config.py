"""运行时配置加载器。

所有配置统一从仓库根目录的 `config/config.toml` 读取，并导出为模块常量。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Z0-9_]+)(?::([^}]*))?\}$")
_APP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _APP_DIR.parent


def _resolve_config_path() -> Path:
    raw_path = os.getenv("CONFIG_FILE", "config/config.toml")
    path = Path(raw_path)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _resolve_repo_path(raw_value: str, default: str) -> str:
    value = (raw_value or default).strip()
    path = Path(value)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return str(path)


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = _ENV_PLACEHOLDER_RE.fullmatch(value.strip())
        if match:
            env_name, default_value = match.groups()
            return os.getenv(env_name, default_value or "")
    return value


def _load_config() -> dict[str, Any]:
    config_path = _resolve_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with config_path.open("rb") as fh:
        loaded = tomllib.load(fh)
    return _resolve_env_placeholders(loaded)


_RAW_CONFIG = _load_config()
CONFIG_FILE_PATH = str(_resolve_config_path())


def _section(name: str) -> dict[str, Any]:
    return dict(_RAW_CONFIG.get(name, {}))


app_cfg = _section("app")
database_cfg = _section("database")
outline_cfg = _section("outline")
oidc_cfg = _section("oidc")
lightrag_cfg = _section("lightrag")
llm_cfg = _section("llm")
embedding_cfg = _section("embedding")
features_cfg = _section("features")


# --- 基本配置 ---
APP_NAME = str(app_cfg.get("name", "Outline LightRAG"))
PORT = int(app_cfg.get("port", 8080))
LOG_LEVEL = str(app_cfg.get("log_level", "INFO")).upper()
SECRET_KEY = str(app_cfg.get("secret_key", "")).strip()

# --- 数据库 / Redis ---
DATABASE_URL = str(database_cfg.get("url", "")).strip()
REDIS_URL = str(database_cfg.get("redis_url", "")).strip()

# --- Outline ---
OUTLINE_API_URL = str(outline_cfg.get("api_url", "")).rstrip("/")
OUTLINE_DISPLAY_URL = str(outline_cfg.get("display_url", "")).rstrip("/")
OUTLINE_API_TOKEN = str(outline_cfg.get("api_token", "")).strip()
OUTLINE_WEBHOOK_SECRET = str(outline_cfg.get("webhook_secret", "")).strip()
OUTLINE_WEBHOOK_SIGN = bool(outline_cfg.get("webhook_sign", True))
OUTLINE_WEBHOOK_DEBOUNCE_SECONDS = int(
    outline_cfg.get("webhook_debounce_seconds", 60)
)

# --- OIDC (GitLab) ---
GITLAB_CLIENT_ID = str(oidc_cfg.get("gitlab_client_id", "")).strip()
GITLAB_CLIENT_SECRET = str(oidc_cfg.get("gitlab_client_secret", "")).strip()
GITLAB_URL = str(oidc_cfg.get("gitlab_url", "")).rstrip("/")
OIDC_REDIRECT_URI = str(oidc_cfg.get("redirect_uri", "")).strip()

# --- LightRAG ---
LIGHTRAG_WORKING_DIR = _resolve_repo_path(
    str(lightrag_cfg.get("working_dir", "./data/lightrag")),
    "./data/lightrag",
)
LIGHTRAG_INPUT_DIR = _resolve_repo_path(
    str(lightrag_cfg.get("input_dir", "./data/lightrag_inputs")),
    "./data/lightrag_inputs",
)
LIGHTRAG_WORKSPACE = str(lightrag_cfg.get("workspace", "")).strip()
LIGHTRAG_QUERY_MODE = str(lightrag_cfg.get("query_mode", "mix")).strip() or "mix"
LIGHTRAG_HISTORY_TURNS = int(lightrag_cfg.get("history_turns", 3))
LIGHTRAG_TOP_K = int(lightrag_cfg.get("top_k", 10))
LIGHTRAG_CHUNK_TOP_K = int(lightrag_cfg.get("chunk_top_k", 20))
LIGHTRAG_MAX_ASYNC = int(lightrag_cfg.get("max_async", 4))
LIGHTRAG_MAX_PARALLEL_INSERT = int(lightrag_cfg.get("max_parallel_insert", 2))
LIGHTRAG_MAX_GRAPH_NODES = int(lightrag_cfg.get("max_graph_nodes", 1000))
LIGHTRAG_CHUNK_SIZE = int(lightrag_cfg.get("chunk_size", 1200))
LIGHTRAG_CHUNK_OVERLAP_SIZE = int(lightrag_cfg.get("chunk_overlap_size", 100))
LIGHTRAG_SUMMARY_LANGUAGE = str(
    lightrag_cfg.get("summary_language", "Chinese")
).strip()
LIGHTRAG_ENTITY_TYPES = [
    str(item).strip()
    for item in lightrag_cfg.get(
        "entity_types",
        ["organization", "person", "geo", "event"],
    )
    if str(item).strip()
]
LIGHTRAG_SUMMARY_MAX_TOKENS = int(lightrag_cfg.get("summary_max_tokens", 1200))
LIGHTRAG_SUMMARY_CONTEXT_SIZE = int(
    lightrag_cfg.get("summary_context_size", 10000)
)
LIGHTRAG_SUMMARY_LENGTH_RECOMMENDED = int(
    lightrag_cfg.get("summary_length_recommended", 600)
)
LIGHTRAG_MAX_TOTAL_TOKENS = int(lightrag_cfg.get("max_total_tokens", 30000))
LIGHTRAG_MAX_ENTITY_TOKENS = int(lightrag_cfg.get("max_entity_tokens", 12000))
LIGHTRAG_MAX_RELATION_TOKENS = int(
    lightrag_cfg.get("max_relation_tokens", 12000)
)
LIGHTRAG_RELATED_CHUNK_NUMBER = int(
    lightrag_cfg.get("related_chunk_number", 10)
)
LIGHTRAG_COSINE_THRESHOLD = float(lightrag_cfg.get("cosine_threshold", 0.2))
LIGHTRAG_KV_STORAGE = str(lightrag_cfg.get("kv_storage", "JsonKVStorage")).strip()
LIGHTRAG_DOC_STATUS_STORAGE = str(
    lightrag_cfg.get("doc_status_storage", "JsonDocStatusStorage")
).strip()
LIGHTRAG_GRAPH_STORAGE = str(
    lightrag_cfg.get("graph_storage", "NetworkXStorage")
).strip()
LIGHTRAG_VECTOR_STORAGE = str(
    lightrag_cfg.get("vector_storage", "NanoVectorDBStorage")
).strip()
LIGHTRAG_TOKEN_SECRET = (
    str(lightrag_cfg.get("token_secret", "")).strip() or SECRET_KEY
)
LIGHTRAG_TOKEN_EXPIRE_HOURS = float(
    lightrag_cfg.get("token_expire_hours", 48)
)
LIGHTRAG_GUEST_TOKEN_EXPIRE_HOURS = float(
    lightrag_cfg.get("guest_token_expire_hours", 24)
)
LIGHTRAG_JWT_ALGORITHM = str(lightrag_cfg.get("jwt_algorithm", "HS256")).strip()
LIGHTRAG_WEBUI_TITLE = str(
    lightrag_cfg.get("webui_title", APP_NAME)
).strip() or APP_NAME
LIGHTRAG_WEBUI_DESCRIPTION = str(
    lightrag_cfg.get("webui_description", "Outline knowledge base powered by LightRAG")
).strip()

# --- LLM ---
LLM_PROVIDER = str(llm_cfg.get("provider", "siliconflow")).strip().lower()
LLM_BASE_URL = str(llm_cfg.get("base_url", "https://api.siliconflow.cn/v1")).strip()
LLM_API_KEY = str(llm_cfg.get("api_key", "")).strip()
LLM_MODEL = str(llm_cfg.get("model", "")).strip()
LLM_TEMPERATURE = float(llm_cfg.get("temperature", 0.2))
LLM_TOP_P = float(llm_cfg.get("top_p", 1.0))
LLM_MAX_COMPLETION_TOKENS = llm_cfg.get("max_completion_tokens", 4096)
if LLM_MAX_COMPLETION_TOKENS is not None:
    LLM_MAX_COMPLETION_TOKENS = int(LLM_MAX_COMPLETION_TOKENS)
LLM_REASONING_EFFORT = str(llm_cfg.get("reasoning_effort", "medium")).strip()
LLM_EXTRA_BODY = llm_cfg.get("extra_body")

# --- Embedding ---
EMBEDDING_PROVIDER = str(
    embedding_cfg.get("provider", LLM_PROVIDER or "siliconflow")
).strip().lower()
EMBEDDING_BASE_URL = str(
    embedding_cfg.get("base_url", LLM_BASE_URL or "https://api.siliconflow.cn/v1")
).strip()
EMBEDDING_API_KEY = str(embedding_cfg.get("api_key", LLM_API_KEY)).strip()
EMBEDDING_MODEL = str(embedding_cfg.get("model", "")).strip()
EMBEDDING_DIM = int(embedding_cfg.get("dimension", 1024))
EMBEDDING_SEND_DIM = bool(embedding_cfg.get("send_dimension", False))

# --- 功能开关 ---
SAFE_LOG_CHAT_INPUT = bool(features_cfg.get("safe_log_chat_input", True))
MAX_LOG_INPUT_CHARS = int(features_cfg.get("max_log_input_chars", 4000))
