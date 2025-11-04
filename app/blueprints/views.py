# app/blueprints/views.py
# 处理所有服务于前端页面和静态资源的路由
import re

from flask import Blueprint, session, redirect, send_from_directory, current_app
from sqlalchemy import text

from database import engine

views_bp = Blueprint('views', __name__)

def _serve_static_with_cache(filename, content_type, max_age=86400):
    resp = send_from_directory(current_app.static_folder, filename)
    resp.headers["Content-Type"] = f"{content_type}; charset=utf-8"
    resp.headers.setdefault("Cache-Control", f"public, max-age={max_age}")
    return resp

@views_bp.route("/")
def chat_page():
    # 恢复：在返回页面前执行简单的登录检查
    if "user" not in session:
        return redirect("/chat/login")

    resp = send_from_directory(current_app.static_folder, "index.html")
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # 为作为应用入口的HTML页面设置禁止缓存的响应头，这依然是好的实践
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@views_bp.route("/<string:conv_guid>")
def chat_page_with_guid(conv_guid: str):
    # 恢复：在返回页面前执行简单的登录检查
    if "user" not in session:
        return redirect("/chat/login")

    if not re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", conv_guid):
        resp = redirect("/chat")
        resp.set_cookie("chat_notice", "对话不存在", max_age=10, httponly=False, samesite="Lax")
        return resp
    with engine.begin() as conn:
        user_id = (session.get("user") or {}).get("id")
        if not user_id:
            return redirect("/chat/login")

        own = conn.execute(text("SELECT 1 FROM conversations WHERE id=:id AND user_id=:u"),
                           {"id": conv_guid, "u": user_id}).scalar()
    if not own:
        resp = redirect("/chat")
        resp.set_cookie("chat_notice", "无权访问该对话", max_age=10, httponly=False, samesite="Lax")
        return resp
    return chat_page()

@views_bp.route("/static/img/DeepSeek.svg")
def chat_static_deepseek_svg():
    return _serve_static_with_cache("img/DeepSeek.svg", "image/svg+xml")

@views_bp.route("/static/img/Tongyi.svg")
def chat_static_tongyi_svg():
    return _serve_static_with_cache("img/Tongyi.svg", "image/svg+xml")

@views_bp.route("/static/img/zhipu.svg")
def chat_static_zhipu_svg():
    return _serve_static_with_cache("img/zhipu.svg", "image/svg+xml")

@views_bp.route("/static/img/moonshotai_new.png")
def chat_static_moonshotai_new_png():
    return _serve_static_with_cache("img/moonshotai_new.png", "image/png")

@views_bp.route("/static/img/ling.png")
def chat_static_ling_png():
    return _serve_static_with_cache("img/ling.png", "image/png")

@views_bp.route("/static/img/openai.svg")
def chat_static_openai_svg():
    return _serve_static_with_cache("img/openai.svg", "image/svg+xml")

@views_bp.route("/static/img/thudm.svg")
def chat_static_thudm_svg():
    return _serve_static_with_cache("img/thudm.svg", "image/svg+xml")

@views_bp.route("/static/img/favicon.ico")
def chat_static_favicon_ico():
    return _serve_static_with_cache("img/favicon.ico", "image/x-icon")

@views_bp.route("/static/img/favicon.svg")
def chat_static_favicon_svg():
    return _serve_static_with_cache("img/favicon.svg", "image/svg+xml")