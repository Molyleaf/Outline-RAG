"""SiliconFlow OpenAI 兼容服务配置辅助函数。"""

from __future__ import annotations

from typing import Any


def normalize_siliconflow_base_url(base_url: str) -> str:
    clean_base_url = (base_url or "").rstrip("/")
    if not clean_base_url:
        return clean_base_url
    if clean_base_url.endswith("/v1"):
        return clean_base_url
    return f"{clean_base_url}/v1"


def build_siliconflow_binding(
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    return {
        "binding": "openai",
        "api_key": api_key,
        "host": normalize_siliconflow_base_url(base_url),
        "model": model,
    }
