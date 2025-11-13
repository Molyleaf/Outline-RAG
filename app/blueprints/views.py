# app/blueprints/views.py
import re

import config
from database import AsyncSessionLocal
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

views_router = APIRouter()
templates = Jinja2Templates(directory="static")

def get_current_user_optional(request: Request) -> dict | None:
    """依赖项：获取用户（如果已登录）"""
    return request.session.get("user")

async def get_db_session():
    """FastAPI 依赖项：获取异步数据库 session。"""
    async with AsyncSessionLocal() as session:
        yield session

# index.html 现在由 TemplateResponse 提供
HTML_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

@views_router.get("/")
async def chat_page(request: Request, user: dict = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/chat/login")

    # 使用 TemplateResponse 替换 FileResponse
    resp = templates.TemplateResponse("index.html", {
        "request": request,
        "app_name": config.APP_NAME
    })
    resp.headers.update(HTML_RESPONSE_HEADERS)
    return resp

@views_router.get("/{conv_guid}")
async def chat_page_with_guid(
        conv_guid: str,
        request: Request,
        user: dict = Depends(get_current_user_optional),
        session = Depends(get_db_session)
):
    if not user:
        return RedirectResponse("/chat/login")

    if not re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", conv_guid):
        resp = RedirectResponse("/chat")
        resp.set_cookie("chat_notice", "对话不存在", max_age=10, httponly=False, samesite="lax")
        return resp

    async with session.begin():
        user_id = user.get("id")
        own = (await session.execute(
            text("SELECT 1 FROM conversations WHERE id=:id AND user_id=:u"),
            {"id": conv_guid, "u": user_id}
        )).scalar()

    if not own:
        resp = RedirectResponse("/chat")
        resp.set_cookie("chat_notice", "无权访问该对话", max_age=10, httponly=False, samesite="lax")
        return resp

    # 使用 TemplateResponse 替换 FileResponse
    resp = templates.TemplateResponse("index.html", {
        "request": request,
        "app_name": config.APP_NAME
    })
    resp.headers.update(HTML_RESPONSE_HEADERS)
    return resp