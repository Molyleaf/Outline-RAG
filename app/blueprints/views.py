# app/blueprints/views.py
import re

# (ASYNC REFACTOR)
from database import AsyncSessionLocal
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import text
# ---

# (ASYNC REFACTOR)
views_router = APIRouter()

def get_current_user_optional(request: Request) -> dict | None:
    """依赖项：获取用户（如果已登录）"""
    return request.session.get("user")

async def get_db_session():
    """FastAPI 依赖项：获取异步数据库 session。"""
    async with AsyncSessionLocal() as session:
        yield session

# (ASYNC REFACTOR)
# index.html 现在由 FileResponse 提供
HTML_RESPONSE_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

@views_router.get("/")
async def chat_page(user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/chat/login")

    return FileResponse("static/index.html", headers=HTML_RESPONSE_HEADERS)

@views_router.get("/{conv_guid}")
async def chat_page_with_guid(
        conv_guid: str,
        user: dict = Depends(get_current_user_optional),
        session = Depends(get_db_session)
):
    if not user:
        return RedirectResponse("/chat/login")

    if not re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", conv_guid):
        resp = RedirectResponse("/chat")
        resp.set_cookie("chat_notice", "对话不存在", max_age=10, httponly=False, samesite="Lax")
        return resp

    # (ASYNC REFACTOR)
    async with session.begin():
        user_id = user.get("id")
        own = (await session.execute(
            text("SELECT 1 FROM conversations WHERE id=:id AND user_id=:u"),
            {"id": conv_guid, "u": user_id}
        )).scalar()

    if not own:
        resp = RedirectResponse("/chat")
        resp.set_cookie("chat_notice", "无权访问该对话", max_age=10, httponly=False, samesite="Lax")
        return resp

    return FileResponse("static/index.html", headers=HTML_RESPONSE_HEADERS)

# --- (已移除) 静态文件路由 ---
# (已在 main.py 中通过 app.mount("/chat/static", ...) 统一处理)