"""LightRAG 运行时集成。

此模块复用官方 FastAPI app，并在外层增加：
1. `/chat` 子路径适配
2. OIDC 会话保护
3. WebUI / Swagger 静态响应重写
4. 提取官方 app 内部的 `rag` 与 `doc_manager` 供同步任务复用
"""

from __future__ import annotations

import argparse
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse, RedirectResponse
from starlette.datastructures import MutableHeaders

import config
from openai_services import build_openai_binding
from siliconflow_services import build_siliconflow_binding

logger = logging.getLogger(__name__)

_CHAT_PREFIX = "/chat"
_runtime: "LightRAGRuntime | None" = None


def _header_value(scope: dict[str, Any], key: str) -> str:
    wanted = key.lower().encode("latin-1")
    for header_key, header_value in scope.get("headers", []):
        if header_key.lower() == wanted:
            return header_value.decode("latin-1")
    return ""


def _accepts_html(scope: dict[str, Any]) -> bool:
    accept = _header_value(scope, "accept").lower()
    return "text/html" in accept or "*/*" in accept or not accept


def _prefix_location(location: str) -> str:
    if not location.startswith("/") or location.startswith(f"{_CHAT_PREFIX}/"):
        return location
    return f"{_CHAT_PREFIX}{location}"


def _rewrite_text_body(body: bytes) -> bytes:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    replacements = (
        ('href="favicon.png"', 'href="/chat/webui/favicon.png"'),
        ("/webui/", "/chat/webui/"),
        ('bh=""', 'bh="/chat"'),
        ("url: '/openapi.json'", "url: '/chat/openapi.json'"),
        (
            "oauth2RedirectUrl: window.location.origin + '/docs/oauth2-redirect'",
            "oauth2RedirectUrl: window.location.origin + '/chat/docs/oauth2-redirect'",
        ),
        ('href="/static/', 'href="/chat/static/'),
        ('src="/static/', 'src="/chat/static/'),
        ('"/static/', '"/chat/static/'),
        ("'/static/", "'/chat/static/"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return text.encode("utf-8")


def _should_buffer_response(content_type: str) -> bool:
    lowered = (content_type or "").lower()
    return (
        "text/html" in lowered
        or "text/css" in lowered
        or "javascript" in lowered
    )


def _build_provider_binding(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    if provider == "siliconflow":
        return build_siliconflow_binding(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    if provider == "openai":
        return build_openai_binding(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    raise ValueError(f"不支持的提供商: {provider}")


def _build_lightrag_args() -> argparse.Namespace:
    llm_binding = _build_provider_binding(
        provider=config.LLM_PROVIDER,
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        model=config.LLM_MODEL,
    )
    embedding_binding = _build_provider_binding(
        provider=config.EMBEDDING_PROVIDER,
        api_key=config.EMBEDDING_API_KEY,
        base_url=config.EMBEDDING_BASE_URL,
        model=config.EMBEDDING_MODEL,
    )

    return argparse.Namespace(
        host="0.0.0.0",
        port=config.PORT,
        working_dir=config.LIGHTRAG_WORKING_DIR,
        input_dir=config.LIGHTRAG_INPUT_DIR,
        timeout=60,
        max_async=config.LIGHTRAG_MAX_ASYNC,
        summary_max_tokens=config.LIGHTRAG_SUMMARY_MAX_TOKENS,
        summary_context_size=config.LIGHTRAG_SUMMARY_CONTEXT_SIZE,
        summary_length_recommended=config.LIGHTRAG_SUMMARY_LENGTH_RECOMMENDED,
        log_level=config.LOG_LEVEL,
        verbose=False,
        key=None,
        ssl=False,
        ssl_certfile=None,
        ssl_keyfile=None,
        simulated_model_name="lightrag",
        simulated_model_tag="latest",
        workspace=config.LIGHTRAG_WORKSPACE,
        workers=1,
        llm_binding=llm_binding["binding"],
        embedding_binding=embedding_binding["binding"],
        rerank_binding="null",
        docling=False,
        kv_storage=config.LIGHTRAG_KV_STORAGE,
        doc_status_storage=config.LIGHTRAG_DOC_STATUS_STORAGE,
        graph_storage=config.LIGHTRAG_GRAPH_STORAGE,
        vector_storage=config.LIGHTRAG_VECTOR_STORAGE,
        max_parallel_insert=config.LIGHTRAG_MAX_PARALLEL_INSERT,
        max_graph_nodes=config.LIGHTRAG_MAX_GRAPH_NODES,
        ollama_num_ctx=32768,
        llm_binding_host=llm_binding["host"],
        embedding_binding_host=embedding_binding["host"],
        llm_binding_api_key=llm_binding["api_key"],
        embedding_binding_api_key=embedding_binding["api_key"],
        llm_model=llm_binding["model"],
        embedding_model=embedding_binding["model"],
        embedding_dim=config.EMBEDDING_DIM,
        embedding_send_dim=config.EMBEDDING_SEND_DIM,
        chunk_size=config.LIGHTRAG_CHUNK_SIZE,
        chunk_overlap_size=config.LIGHTRAG_CHUNK_OVERLAP_SIZE,
        enable_llm_cache_for_extract=False,
        enable_llm_cache=False,
        document_loading_engine="DEFAULT",
        pdf_decrypt_password=None,
        cors_origins="*",
        summary_language=config.LIGHTRAG_SUMMARY_LANGUAGE,
        entity_types=config.LIGHTRAG_ENTITY_TYPES,
        whitelist_paths="/health,/api/*",
        auth_accounts="",
        token_secret=config.LIGHTRAG_TOKEN_SECRET,
        token_expire_hours=config.LIGHTRAG_TOKEN_EXPIRE_HOURS,
        guest_token_expire_hours=config.LIGHTRAG_GUEST_TOKEN_EXPIRE_HOURS,
        jwt_algorithm=config.LIGHTRAG_JWT_ALGORITHM,
        token_auto_renew=True,
        token_renew_threshold=0.5,
        rerank_model=None,
        rerank_binding_host=None,
        rerank_binding_api_key=None,
        min_rerank_score=0.0,
        history_turns=config.LIGHTRAG_HISTORY_TURNS,
        top_k=config.LIGHTRAG_TOP_K,
        chunk_top_k=config.LIGHTRAG_CHUNK_TOP_K,
        max_entity_tokens=config.LIGHTRAG_MAX_ENTITY_TOKENS,
        max_relation_tokens=config.LIGHTRAG_MAX_RELATION_TOKENS,
        max_total_tokens=config.LIGHTRAG_MAX_TOTAL_TOKENS,
        cosine_threshold=config.LIGHTRAG_COSINE_THRESHOLD,
        related_chunk_number=config.LIGHTRAG_RELATED_CHUNK_NUMBER,
        force_llm_summary_on_merge=3,
        embedding_func_max_async=16,
        embedding_batch_num=32,
        embedding_token_limit=None,
        max_upload_size=104857600,
        openai_llm_frequency_penalty=0.0,
        openai_llm_max_completion_tokens=config.LLM_MAX_COMPLETION_TOKENS,
        openai_llm_presence_penalty=0.0,
        openai_llm_reasoning_effort=config.LLM_REASONING_EFFORT,
        openai_llm_safety_identifier="",
        openai_llm_service_tier="",
        openai_llm_stop=[],
        openai_llm_temperature=config.LLM_TEMPERATURE,
        openai_llm_top_p=config.LLM_TOP_P,
        openai_llm_max_tokens=None,
        openai_llm_extra_body=config.LLM_EXTRA_BODY,
    )


def _extract_closure_value(app: Any, variable_name: str) -> Any:
    for route in getattr(app, "routes", []):
        endpoint = getattr(route, "endpoint", None)
        closure = getattr(endpoint, "__closure__", None)
        if not endpoint or not closure:
            continue
        for name, cell in zip(endpoint.__code__.co_freevars, closure):
            if name == variable_name:
                return cell.cell_contents
    raise RuntimeError(f"无法从 LightRAG app 中提取 {variable_name}")


class ProtectedLightRAGApp:
    """给 LightRAG 官方 app 增加会话保护和响应重写。"""

    def __init__(self, inner_app: Any):
        self.inner_app = inner_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.inner_app(scope, receive, send)
            return

        session = scope.get("session") or {}
        if "user" not in session:
            response = (
                RedirectResponse(f"{_CHAT_PREFIX}/login", status_code=303)
                if scope.get("method") == "GET" and _accepts_html(scope)
                else JSONResponse(
                    {"detail": "Not authenticated"},
                    status_code=401,
                )
            )
            await response(scope, receive, send)
            return

        captured_start: dict[str, Any] | None = None
        buffered_body: list[bytes] = []
        should_buffer = False

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal captured_start, should_buffer

            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                location = headers.get("location")
                if location:
                    headers["location"] = _prefix_location(location)

                content_type = headers.get("content-type", "")
                should_buffer = _should_buffer_response(content_type)
                if should_buffer:
                    captured_start = {
                        "type": "http.response.start",
                        "status": message["status"],
                        "headers": list(headers.raw),
                    }
                    return

                await send(
                    {
                        "type": "http.response.start",
                        "status": message["status"],
                        "headers": list(headers.raw),
                    }
                )
                return

            if message["type"] == "http.response.body" and should_buffer:
                buffered_body.append(message.get("body", b""))
                if message.get("more_body", False):
                    return

                assert captured_start is not None
                patched_body = _rewrite_text_body(b"".join(buffered_body))
                headers = MutableHeaders(raw=captured_start["headers"])
                headers["content-length"] = str(len(patched_body))
                if "etag" in headers:
                    del headers["etag"]
                await send(
                    {
                        "type": "http.response.start",
                        "status": captured_start["status"],
                        "headers": list(headers.raw),
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": patched_body,
                        "more_body": False,
                    }
                )
                return

            await send(message)

        await self.inner_app(scope, receive, send_wrapper)


@dataclass
class LightRAGRuntime:
    args: argparse.Namespace
    app: Any
    rag: Any
    doc_manager: Any
    protected_app: ProtectedLightRAGApp

    @asynccontextmanager
    async def lifespan(self):
        async with self.app.router.lifespan_context(self.app):
            yield


def get_runtime() -> LightRAGRuntime:
    global _runtime

    if _runtime is not None:
        return _runtime

    os.environ["WEBUI_TITLE"] = config.LIGHTRAG_WEBUI_TITLE
    os.environ["WEBUI_DESCRIPTION"] = config.LIGHTRAG_WEBUI_DESCRIPTION

    args = _build_lightrag_args()

    from lightrag.api.config import initialize_config

    initialize_config(args, force=True)

    from lightrag.api.lightrag_server import get_application

    app = get_application(args)
    rag = _extract_closure_value(app, "rag")
    doc_manager = _extract_closure_value(app, "doc_manager")

    app.state.rag = rag
    app.state.doc_manager = doc_manager
    app.state.lightrag_args = args

    _runtime = LightRAGRuntime(
        args=args,
        app=app,
        rag=rag,
        doc_manager=doc_manager,
        protected_app=ProtectedLightRAGApp(app),
    )
    logger.info(
        "LightRAG 运行时已初始化: working_dir=%s input_dir=%s",
        args.working_dir,
        args.input_dir,
    )
    return _runtime
