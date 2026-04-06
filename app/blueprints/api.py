"""兼容接口与 Outline 同步入口。"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

import config
import rag
from blueprints.auth import require_authenticated_user
from lightrag_runtime import get_runtime
from outline_client import verify_outline_signature

logger = logging.getLogger(__name__)
api_router = APIRouter()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Vary": "Cookie, Authorization",
}


class AskRequest(BaseModel):
    query: str = Field(min_length=1)
    conv_id: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    edit_source_message_id: int | None = None
    response_mode: str | None = "answer"
    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] | None = None


@api_router.get("/api/me")
async def api_me(user: dict[str, Any] = Depends(require_authenticated_user)):
    return JSONResponse(
        {
            "user": user,
            "auth_mode": "oidc",
            "runtime": {
                "provider": config.LLM_PROVIDER,
                "model": config.LLM_MODEL,
                "query_mode": config.LIGHTRAG_QUERY_MODE,
            },
        },
        headers=NO_CACHE_HEADERS,
    )


@api_router.post("/api/ask")
async def api_ask(
    body: AskRequest,
    _user: dict[str, Any] = Depends(require_authenticated_user),
):
    if (body.response_mode or "answer") != "answer":
        raise HTTPException(
            status_code=400,
            detail="LightRAG 迁移后不再支持 copy_prompt 等旧响应模式",
        )

    runtime = get_runtime()

    from lightrag.base import QueryParam

    query_param = QueryParam(
        mode=body.mode or config.LIGHTRAG_QUERY_MODE,
        stream=True,
        response_type="Multiple Paragraphs",
        top_k=config.LIGHTRAG_TOP_K,
        chunk_top_k=config.LIGHTRAG_CHUNK_TOP_K,
        max_total_tokens=config.LIGHTRAG_MAX_TOTAL_TOKENS,
        max_entity_tokens=config.LIGHTRAG_MAX_ENTITY_TOKENS,
        max_relation_tokens=config.LIGHTRAG_MAX_RELATION_TOKENS,
        conversation_history=[],
        include_references=True,
    )

    result = await runtime.rag.aquery_llm(body.query, param=query_param)
    llm_response = result.get("llm_response", {})
    response_iterator = llm_response.get("response_iterator")
    response_content = llm_response.get("content", "")
    model_name = body.model or config.LLM_MODEL

    async def generate():
        try:
            if response_iterator:
                async for chunk in response_iterator:
                    if not chunk:
                        continue
                    payload = {
                        "choices": [
                            {"delta": {"content": chunk, "thinking": ""}}
                        ],
                        "model": model_name,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                payload = {
                    "choices": [
                        {"delta": {"content": response_content or "", "thinking": ""}}
                    ],
                    "model": model_name,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # pragma: no cover
            logger.exception("兼容 /api/ask 流式输出失败: %s", exc)
            error_payload = {"error": str(exc)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@api_router.post("/update/all")
async def update_all(_user: dict[str, Any] = Depends(require_authenticated_user)):
    started = await rag.request_refresh_all()
    if not started:
        return JSONResponse({"ok": False, "error": "正在刷新中"}, status_code=429)
    return JSONResponse(
        {"ok": True, "message": "已开始全量刷新"},
        status_code=202,
    )


@api_router.get("/api/refresh/status")
async def refresh_status(_user: dict[str, Any] = Depends(require_authenticated_user)):
    return JSONResponse(rag.get_refresh_state(), headers=NO_CACHE_HEADERS)


@api_router.post("/update/webhook")
async def update_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get(
        "Authorization"
    )

    if config.OUTLINE_WEBHOOK_SIGN and not verify_outline_signature(raw, sig):
        return Response("invalid signature", status_code=401)

    await rag.schedule_webhook_refresh()
    return JSONResponse({"ok": True, "message": "Webhook timer refreshed"})
