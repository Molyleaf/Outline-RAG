"""运行时配置加载器。

配置源统一放在仓库根目录的 `config/config.toml` 中。
本模块在启动时读取 TOML，并导出历史代码兼容的常量。
"""

from __future__ import annotations

import json
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
siliconflow_cfg = _section("siliconflow")
models_cfg = _section("models")
prompts_cfg = _section("prompts")
chat_cfg = _section("chat")
rag_cfg = _section("rag")
oidc_cfg = _section("oidc")
features_cfg = _section("features")
storage_cfg = _section("storage")


# --- 基本配置 ---
APP_NAME = str(app_cfg.get("name", "Pigeon Chat"))
PORT = int(app_cfg.get("port", 8080))
VECTOR_DIM = int(app_cfg.get("vector_dim", 1024))
LOG_LEVEL = str(app_cfg.get("log_level", "WARN")).upper()
SECRET_KEY = str(app_cfg.get("secret_key", ""))

# --- 数据库 ---
DATABASE_URL = str(database_cfg.get("url", ""))
REDIS_URL = str(database_cfg.get("redis_url", ""))

# --- Outline ---
OUTLINE_API_URL = str(outline_cfg.get("api_url", "")).rstrip("/")
OUTLINE_DISPLAY_URL = str(outline_cfg.get("display_url", "")).rstrip("/")
OUTLINE_API_TOKEN = str(outline_cfg.get("api_token", ""))
OUTLINE_WEBHOOK_SECRET = str(outline_cfg.get("webhook_secret", "123")).strip()
OUTLINE_WEBHOOK_SIGN = bool(outline_cfg.get("webhook_sign", True))

# --- SiliconFlow ---
SILICONFLOW_API_KEY = str(siliconflow_cfg.get("api_key", ""))
SILICONFLOW_BASE_URL = str(
    siliconflow_cfg.get("base_url", "https://api.siliconflow.cn/v1")
).rstrip("/")
EMBEDDING_MODEL = str(siliconflow_cfg.get("embedding_model", "BAAI/bge-m3"))
RERANKER_MODEL = str(siliconflow_cfg.get("reranker_model", "BAAI/bge-reranker-v2-m3"))
BASE_CHAT_MODEL = str(
    siliconflow_cfg.get("base_chat_model", "Qwen/Qwen3-Next-80B-A3B-Instruct")
)

# --- 模型列表配置 ---
CHAT_MODELS = list(models_cfg.get("chat_presets", []))
CHAT_MODELS_JSON = json.dumps(CHAT_MODELS, ensure_ascii=False)
BETA_AUTHORIZED_USER_IDS = list(models_cfg.get("beta_authorized_user_ids", []))
CUSTOM_OPENAI_MODEL_ID = str(models_cfg.get("custom_openai_model_id", "custom-openai"))
CUSTOM_OPENAI_DISPLAY_NAME = str(models_cfg.get("custom_openai_display_name", "自定义 OpenAI"))
CUSTOM_OPENAI_ICON = str(models_cfg.get("custom_openai_icon", "/chat/static/img/openai.svg"))
CUSTOM_OPENAI_DEFAULT_TEMP = float(models_cfg.get("custom_openai_default_temp", 0.7))
CUSTOM_OPENAI_DEFAULT_TOP_P = float(models_cfg.get("custom_openai_default_top_p", 1.0))

# --- 提示词配置 ---
DEFAULT_CORE_WORLDVIEW = str(prompts_cfg.get("default_core_worldview", ""))
CORE_WORLDVIEW = str(prompts_cfg.get("core_worldview") or DEFAULT_CORE_WORLDVIEW)
SYSTEM_PROMPT_QUERY = str(prompts_cfg.get("system_prompt_query_template", "")).format(
    core_worldview=CORE_WORLDVIEW
)
SYSTEM_PROMPT_CREATIVE = str(prompts_cfg.get("system_prompt_creative_template", "")).format(
    core_worldview=CORE_WORLDVIEW
)
SYSTEM_PROMPT_ROLEPLAY = str(prompts_cfg.get("system_prompt_roleplay_template", "")).format(
    core_worldview=CORE_WORLDVIEW
)
SYSTEM_PROMPT_GENERAL = str(prompts_cfg.get("system_prompt_general", "回答用户的问题。"))
CLASSIFIER_PROMPT_TEMPLATE = str(
    prompts_cfg.get("classifier_prompt_template", "")
).format(core_worldview=CORE_WORLDVIEW)
REWRITE_PROMPT_TEMPLATE = str(prompts_cfg.get("rewrite_prompt_template", ""))
HISTORY_AWARE_PROMPT_TEMPLATE = str(prompts_cfg.get("history_aware_prompt_template", ""))

# --- 多轮对话配置 ---
MAX_HISTORY_MESSAGES = int(chat_cfg.get("max_history_messages", 20))

# --- RAG/检索参数 ---
TOP_K = int(rag_cfg.get("top_k", 12))
K = int(rag_cfg.get("rerank_top_k", 3))
REFRESH_BATCH_SIZE = int(rag_cfg.get("refresh_batch_size", 100))

# --- OIDC (GitLab) ---
GITLAB_CLIENT_ID = str(oidc_cfg.get("gitlab_client_id", ""))
GITLAB_CLIENT_SECRET = str(oidc_cfg.get("gitlab_client_secret", "123"))
GITLAB_URL = str(oidc_cfg.get("gitlab_url", "")).rstrip("/")
OIDC_REDIRECT_URI = str(oidc_cfg.get("redirect_uri", ""))

# --- 功能开关与限制 ---
USE_JOSE_VERIFY = bool(features_cfg.get("use_jose_verify", True))
SAFE_LOG_CHAT_INPUT = bool(features_cfg.get("safe_log_chat_input", True))
MAX_LOG_INPUT_CHARS = int(features_cfg.get("max_log_input_chars", 4000))
MAX_CONTENT_LENGTH = int(features_cfg.get("max_content_length", 10485760))
ALLOWED_FILE_EXTENSIONS = {
    str(ext).strip().lower()
    for ext in features_cfg.get("allowed_file_extensions", ["txt", "md", "pdf"])
    if str(ext).strip()
}

# --- 持久化目录 ---
ATTACHMENTS_DIR = str(storage_cfg.get("attachments_dir", "/app/data/attachments"))
