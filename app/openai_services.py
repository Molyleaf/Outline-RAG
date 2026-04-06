"""OpenAI 兼容服务配置辅助函数。"""

from __future__ import annotations

from typing import Any


def normalize_openai_base_url(base_url: str) -> str:
    return (base_url or "").rstrip("/")


def build_openai_binding(
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    return {
        "binding": "openai",
        "api_key": api_key,
        "host": normalize_openai_base_url(base_url),
        "model": model,
    }
