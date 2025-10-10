# 处理所有服务于前端页面和静态资源的路由
import re

from flask import Blueprint, session, redirect, send_from_directory, current_app
from sqlalchemy import text

from database import engine

views_bp = Blueprint('views', __name__)

def _check_login_and_boot_id():
    """
    检查用户是否登录，并验证会话的 boot_id 是否与当前应用实例匹配。
    如果不匹配，则会话无效，应重定向到登录页。
    """
    if "user" not in session or session.get("boot_id") != current_app.config.get("BOOT_ID"):
        # 在重定向前清除可能无效的会话
        session.clear()
        return redirect("/chat/login")
    return None

def _serve_static_with_cache(filename, content_type, max_age=86400):
    resp = send_from_directory(current_app.static_folder, filename)
    resp.headers["Content-Type"] = f"{content_type}; charset=utf-8"
    resp.headers.setdefault("Cache-Control", f"public, max-age={max_age}")
    return resp

@views_bp.route("/")
def chat_page():
    # 修复：在返回页面前执行严格的登录检查
    redirect_response = _check_login_and_boot_id()
    if redirect_response:
        return redirect_response

    resp = send_from_directory(current_app.static_folder, "index.html")
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers.setdefault("Cache-Control", "public, max-age=300")
    return resp

@views_bp.route("/<string:conv_guid>")
def chat_page_with_guid(conv_guid: str):
    # 修复：在返回页面前执行严格的登录检查
    redirect_response = _check_login_and_boot_id()
    if redirect_response:
        return redirect_response

    if not re.fullmatch(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", conv_guid):
        resp = redirect("/chat")
        resp.set_cookie("chat_notice", "对话不存在", max_age=10, httponly=False, samesite="Lax")
        return resp
    with engine.begin() as conn:
        own = conn.execute(text("SELECT 1 FROM conversations WHERE id=:id AND user_id=:u"),
                           {"id": conv_guid, "u": session["user"]["id"]}).scalar()
    if not own:
        resp = redirect("/chat")
        resp.set_cookie("chat_notice", "无权访问该对话", max_age=10, httponly=False, samesite="Lax")
        return resp
    return chat_page()

@views_bp.route("/static/style.css")
def chat_static_style():
    return _serve_static_with_cache("style.css", "text/css", 3600)

@views_bp.route("/static/script.js")
def chat_static_script():
    return _serve_static_with_cache("script.js", "application/javascript")

@views_bp.route("/img/static/DeepSeek.svg")
def chat_static_deepseek_svg():
    return _serve_static_with_cache("DeepSeek.svg", "image/svg+xml")

@views_bp.route("/img/static/Tongyi.svg")
def chat_static_tongyi_svg():
    return _serve_static_with_cache("Tongyi.svg", "image/svg+xml")

@views_bp.route("/img/static/zhipu.svg")
def chat_static_zhipu_svg():
    return _serve_static_with_cache("zhipu.svg", "image/svg+xml")

@views_bp.route("/img/static/moonshotai_new.png")
def chat_static_kmoonshotai_new_png():
    return _serve_static_with_cache("moonshotai_new.png", "image/png")

@views_bp.route("/img/static/ling.png")
def chat_static_ling_png():
    return _serve_static_with_cache("ling.png", "image/png")

@views_bp.route("/img/static/openai.svg")
def chat_static_openai_svg():
    return _serve_static_with_cache("openai.svg", "image/svg+xml")

@views_bp.route("/img/static/thudm.svg")
def chat_static_thudm_svg():
    return _serve_static_with_cache("thudm.svg", "image/svg+xml")

@views_bp.route("/img/static/favicon.ico")
def chat_static_favicon_ico():
    return _serve_static_with_cache("favicon.ico", "image/x-icon")