"""OIDC 保护下的应用侧接口与 Outline 同步入口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

import config
from .. import rag
from .auth import require_authenticated_user
from ..outline_client import verify_outline_signature

api_router = APIRouter()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Vary": "Cookie, Authorization",
}


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
