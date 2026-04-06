"""OpenAI 兼容聊天服务。

此模块仅负责通过 `langchain_openai` 对接 OpenAI 兼容接口，
避免其他模块直接依赖具体 SDK。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI


def build_openai_chat_model(
    *,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    top_p: float,
) -> ChatOpenAI:
    kwargs = {
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
    }
    clean_base_url = (base_url or "").rstrip("/")
    if clean_base_url:
        kwargs["base_url"] = clean_base_url
    return ChatOpenAI(**kwargs)
