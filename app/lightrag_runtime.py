"""LightRAG runtime assembly for the OIDC-protected `/chat` mount."""

from __future__ import annotations

import logging
import os
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import config
from database import parse_database_url
from openai_services import build_openai_binding
from siliconflow_services import build_siliconflow_binding

from lightrag import LightRAG, __version__ as core_version
from lightrag.api import __api_version__ as api_version
from lightrag.api.auth import auth_handler
from lightrag.api.config import global_args
from lightrag.api.routers.document_routes import DocumentManager, create_document_routes
from lightrag.api.routers.graph_routes import create_graph_routes
from lightrag.api.routers.ollama_api import OllamaAPI
from lightrag.api.routers.query_routes import create_query_routes
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

logger = logging.getLogger(__name__)

_CHAT_PREFIX = "/chat"
_RUNTIME: "LightRAGRuntime | None" = None
_WEBUI_PATCH_STAMP = "chat-prefix-v2"


class WebUIStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]):
        response = await super().get_response(path, scope)

        is_html = path.endswith(".html") or response.media_type == "text/html"
        if is_html:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif "/assets/" in path:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

        if path.endswith(".js"):
            response.headers["Content-Type"] = "application/javascript"
        elif path.endswith(".css"):
            response.headers["Content-Type"] = "text/css"

        return response


@dataclass
class LightRAGRuntime:
    rag: LightRAG
    doc_manager: DocumentManager
    chat_app: FastAPI
    webui_dir: Path

    @asynccontextmanager
    async def lifespan(self):
        await self.rag.initialize_storages()
        try:
            await self.rag.check_and_migrate_data()
            yield
        finally:
            await self.rag.finalize_storages()


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
    raise ValueError(f"不支持的 OpenAI 兼容提供商: {provider}")


def _apply_storage_environment() -> None:
    postgres = parse_database_url()

    if not config.NEO4J_URI or not config.NEO4J_USERNAME or not config.NEO4J_PASSWORD:
        raise RuntimeError(
            "使用 Neo4JStorage 时必须配置 neo4j.uri / neo4j.username / neo4j.password。"
        )

    storage_env = {
        "POSTGRES_HOST": postgres["host"],
        "POSTGRES_PORT": postgres["port"],
        "POSTGRES_USER": postgres["user"],
        "POSTGRES_PASSWORD": postgres["password"],
        "POSTGRES_DATABASE": postgres["database"],
        "POSTGRES_WORKSPACE": config.LIGHTRAG_WORKSPACE,
        "POSTGRES_MAX_CONNECTIONS": str(config.DATABASE_MAX_CONNECTIONS),
        "POSTGRES_ENABLE_VECTOR": "true",
        "POSTGRES_VECTOR_INDEX_TYPE": config.LIGHTRAG_POSTGRES_VECTOR_INDEX_TYPE,
        "POSTGRES_HNSW_M": str(config.LIGHTRAG_POSTGRES_HNSW_M),
        "POSTGRES_HNSW_EF": str(config.LIGHTRAG_POSTGRES_HNSW_EF),
        "NEO4J_URI": config.NEO4J_URI,
        "NEO4J_USERNAME": config.NEO4J_USERNAME,
        "NEO4J_PASSWORD": config.NEO4J_PASSWORD,
        "NEO4J_DATABASE": config.NEO4J_DATABASE,
        "NEO4J_WORKSPACE": config.LIGHTRAG_WORKSPACE,
    }
    ssl_mode = config.DATABASE_SSL_MODE or postgres.get("sslmode", "")
    if ssl_mode:
        storage_env["POSTGRES_SSL_MODE"] = ssl_mode

    for key, value in storage_env.items():
        if value:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]


def _build_llm_kwargs(binding: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "base_url": binding["host"],
        "api_key": binding["api_key"],
        "temperature": config.LLM_TEMPERATURE,
        "top_p": config.LLM_TOP_P,
        "reasoning_effort": config.LLM_REASONING_EFFORT,
    }
    if config.LLM_MAX_COMPLETION_TOKENS is not None:
        kwargs["max_completion_tokens"] = config.LLM_MAX_COMPLETION_TOKENS
    if isinstance(config.LLM_EXTRA_BODY, dict) and config.LLM_EXTRA_BODY:
        kwargs["extra_body"] = config.LLM_EXTRA_BODY
    return kwargs


def _build_embedding_func(binding: dict[str, Any]) -> EmbeddingFunc:
    provider_max_token_size = (
        openai_embed.max_token_size if isinstance(openai_embed, EmbeddingFunc) else None
    )
    actual_func = openai_embed.func if isinstance(openai_embed, EmbeddingFunc) else openai_embed

    async def embedding_func(texts: list[str], embedding_dim: int | None = None):
        kwargs: dict[str, Any] = {
            "texts": texts,
            "base_url": binding["host"],
            "api_key": binding["api_key"],
        }
        if binding["model"]:
            kwargs["model"] = binding["model"]
        if embedding_dim is not None:
            kwargs["embedding_dim"] = embedding_dim
        return await actual_func(**kwargs)

    return EmbeddingFunc(
        embedding_dim=config.EMBEDDING_DIM,
        func=embedding_func,
        max_token_size=provider_max_token_size,
        send_dimensions=config.EMBEDDING_SEND_DIM,
        model_name=binding["model"] or None,
    )


def _build_rag() -> LightRAG:
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

    return LightRAG(
        working_dir=config.LIGHTRAG_WORKING_DIR,
        workspace=config.LIGHTRAG_WORKSPACE,
        llm_model_func=openai_complete_if_cache,
        llm_model_name=llm_binding["model"],
        llm_model_max_async=config.LIGHTRAG_MAX_ASYNC,
        llm_model_kwargs=_build_llm_kwargs(llm_binding),
        embedding_func=_build_embedding_func(embedding_binding),
        default_llm_timeout=180,
        default_embedding_timeout=30,
        kv_storage=config.LIGHTRAG_KV_STORAGE,
        graph_storage=config.LIGHTRAG_GRAPH_STORAGE,
        vector_storage=config.LIGHTRAG_VECTOR_STORAGE,
        doc_status_storage=config.LIGHTRAG_DOC_STATUS_STORAGE,
        vector_db_storage_cls_kwargs={
            "cosine_better_than_threshold": config.LIGHTRAG_COSINE_THRESHOLD
        },
        enable_llm_cache=False,
        enable_llm_cache_for_entity_extract=False,
        max_parallel_insert=config.LIGHTRAG_MAX_PARALLEL_INSERT,
        max_graph_nodes=config.LIGHTRAG_MAX_GRAPH_NODES,
        summary_max_tokens=config.LIGHTRAG_SUMMARY_MAX_TOKENS,
        summary_context_size=config.LIGHTRAG_SUMMARY_CONTEXT_SIZE,
        summary_length_recommended=config.LIGHTRAG_SUMMARY_LENGTH_RECOMMENDED,
        chunk_token_size=config.LIGHTRAG_CHUNK_SIZE,
        chunk_overlap_token_size=config.LIGHTRAG_CHUNK_OVERLAP_SIZE,
        addon_params={
            "language": config.LIGHTRAG_SUMMARY_LANGUAGE,
            "entity_types": config.LIGHTRAG_ENTITY_TYPES,
        },
        auto_manage_storages_states=False,
    )


def _replace_required(text: str, old: str, new: str, *, context: str) -> str:
    if old not in text:
        raise RuntimeError(f"无法在 {context} 中找到需要替换的片段: {old}")
    return text.replace(old, new)


def _prepare_patched_webui() -> Path:
    from lightrag.api import lightrag_server

    source_dir = Path(lightrag_server.__file__).resolve().parent / "webui"
    target_dir = Path(config.LIGHTRAG_WORKING_DIR).resolve().parent / "lightrag_webui"
    stamp_file = target_dir / ".patch-stamp"
    stamp_value = f"{core_version}|{_WEBUI_PATCH_STAMP}"

    if source_dir.exists() and target_dir.exists() and stamp_file.exists():
        if stamp_file.read_text(encoding="utf-8").strip() == stamp_value:
            return target_dir

    if not source_dir.exists():
        raise FileNotFoundError(f"LightRAG WebUI 目录不存在: {source_dir}")

    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)

    entry_js_patched = False
    for path in target_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".js" and 'Mj="/webui/"' in text:
            text = _replace_required(
                text,
                'bh=""',
                f'bh="{_CHAT_PREFIX}"',
                context=str(path),
            )
            entry_js_patched = True
        text = text.replace("/webui/", f"{_CHAT_PREFIX}/webui/")
        path.write_text(text, encoding="utf-8")

    if not entry_js_patched:
        raise RuntimeError("无法在 LightRAG WebUI 入口文件中找到 basename 常量")

    stamp_file.write_text(stamp_value, encoding="utf-8")
    return target_dir


def _mount_prefix(request: Request) -> str:
    return request.scope.get("root_path", "") or _CHAT_PREFIX


def _configure_guest_auth() -> None:
    auth_handler.secret = config.LIGHTRAG_TOKEN_SECRET
    auth_handler.algorithm = config.LIGHTRAG_JWT_ALGORITHM
    auth_handler.expire_hours = config.LIGHTRAG_TOKEN_EXPIRE_HOURS
    auth_handler.guest_expire_hours = config.LIGHTRAG_GUEST_TOKEN_EXPIRE_HOURS
    auth_handler.accounts = {}

    global_args.token_secret = config.LIGHTRAG_TOKEN_SECRET
    global_args.jwt_algorithm = config.LIGHTRAG_JWT_ALGORITHM
    global_args.token_expire_hours = config.LIGHTRAG_TOKEN_EXPIRE_HOURS
    global_args.guest_token_expire_hours = config.LIGHTRAG_GUEST_TOKEN_EXPIRE_HOURS
    global_args.token_auto_renew = True
    global_args.token_renew_threshold = 0.5


def _build_chat_app(rag: LightRAG, doc_manager: DocumentManager, webui_dir: Path) -> FastAPI:
    app = FastAPI(
        title=f"{config.APP_NAME} Chat",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/", include_in_schema=False)
    async def chat_root(request: Request):
        return RedirectResponse(f"{_mount_prefix(request)}/webui/", status_code=307)

    @app.get("/webui", include_in_schema=False)
    async def chat_webui_root(request: Request):
        return RedirectResponse(f"{_mount_prefix(request)}/webui/", status_code=307)

    @app.get("/webui/login", include_in_schema=False)
    @app.get("/webui/login/", include_in_schema=False)
    async def chat_webui_login(request: Request):
        return RedirectResponse(f"{_mount_prefix(request)}/login", status_code=307)

    @app.get("/auth-status")
    async def auth_status():
        guest_token = auth_handler.create_token(
            username="guest",
            role="guest",
            metadata={"auth_mode": "oidc"},
        )
        return JSONResponse(
            {
                "auth_configured": False,
                "access_token": guest_token,
                "token_type": "bearer",
                "auth_mode": "oidc",
                "message": "OIDC session is active.",
                "core_version": core_version,
                "api_version": api_version,
                "webui_title": config.LIGHTRAG_WEBUI_TITLE,
                "webui_description": config.LIGHTRAG_WEBUI_DESCRIPTION,
            }
        )

    @app.get("/health")
    async def health():
        return JSONResponse(
            {
                "status": "healthy",
                "webui_available": True,
                "working_directory": config.LIGHTRAG_WORKING_DIR,
                "input_directory": config.LIGHTRAG_INPUT_DIR,
                "configuration": {
                    "llm_binding": "openai",
                    "llm_model": config.LLM_MODEL,
                    "embedding_binding": "openai",
                    "embedding_model": config.EMBEDDING_MODEL,
                    "workspace": config.LIGHTRAG_WORKSPACE,
                },
                "auth_mode": "oidc",
                "pipeline_busy": False,
                "core_version": core_version,
                "api_version": api_version,
            }
        )

    app.include_router(create_document_routes(rag, doc_manager, api_key=None))
    app.include_router(create_query_routes(rag, api_key=None, top_k=config.LIGHTRAG_TOP_K))
    app.include_router(create_graph_routes(rag, api_key=None))
    app.include_router(OllamaAPI(rag, top_k=config.LIGHTRAG_TOP_K, api_key=None).router, prefix="/api")

    app.mount(
        "/webui",
        WebUIStaticFiles(directory=webui_dir, html=True, check_dir=True),
        name="webui",
    )

    app.state.rag = rag
    app.state.doc_manager = doc_manager
    app.state.webui_dir = str(webui_dir)
    return app


def get_runtime() -> LightRAGRuntime:
    global _RUNTIME

    if _RUNTIME is not None:
        return _RUNTIME

    _apply_storage_environment()
    _configure_guest_auth()

    rag = _build_rag()
    doc_manager = DocumentManager(
        config.LIGHTRAG_INPUT_DIR,
        workspace=config.LIGHTRAG_WORKSPACE,
    )
    webui_dir = _prepare_patched_webui()
    chat_app = _build_chat_app(rag, doc_manager, webui_dir)

    _RUNTIME = LightRAGRuntime(
        rag=rag,
        doc_manager=doc_manager,
        chat_app=chat_app,
        webui_dir=webui_dir,
    )
    logger.info(
        "LightRAG runtime initialized: working_dir=%s input_dir=%s webui_dir=%s",
        config.LIGHTRAG_WORKING_DIR,
        config.LIGHTRAG_INPUT_DIR,
        webui_dir,
    )
    return _RUNTIME
