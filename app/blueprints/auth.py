# app/blueprints/auth.py
# 处理用户登录、登出和 OIDC 回调逻辑
import base64
import hashlib
import json
import secrets
import time
import urllib.parse

import requests
from flask import Blueprint, request, session, redirect, url_for
from jose import jwt
from jose.exceptions import JOSEError
from requests.adapters import HTTPAdapter
from sqlalchemy import text
from urllib3.util.retry import Retry

import config
from database import engine, redis_client

auth_bp = Blueprint('auth', __name__)

# --- 创建带重试的 requests Session 辅助函数 ---
def _create_retry_session():
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"], raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    # session.mount("http://", adapter)
    return session

# --- OIDC Helpers (使用 requests 重构) ---
def oidc_discovery():
    """获取OIDC配置，优先从Redis缓存读取。"""
    cache_key = "oidc:discovery"
    if redis_client:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        session = _create_retry_session()
        resp = session.get(f"{config.GITLAB_URL}/.well-known/openid-configuration", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if redis_client:
            redis_client.set(cache_key, json.dumps(data), ex=43200) # 缓存12小时
        return data
    except requests.RequestException as e:
        # 在Web请求的上下文中，记录错误比让整个应用崩溃更好
        print(f"Error during OIDC discovery: {e}")
        return None


def _get_jwks(jwks_uri):
    """获取JWKS公钥集，优先从Redis缓存读取。"""
    cache_key = f"oidc:jwks:{jwks_uri}"
    if redis_client:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        session = _create_retry_session()
        resp = session.get(jwks_uri, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if redis_client:
            redis_client.set(cache_key, json.dumps(data), ex=43200) # 缓存12小时
        return data
    except requests.RequestException as e:
        print(f"Error fetching JWKS: {e}")
        return None

def _verify_jwt_rs256(id_token, expected_iss, expected_aud, expected_nonce=None):
    try:
        disc = oidc_discovery()
        if not disc: raise ValueError("Could not fetch OIDC discovery document.")
        jwks = _get_jwks(disc["jwks_uri"])
        if not jwks: raise ValueError("Could not fetch JWKS.")

        payload = jwt.decode(
            id_token, jwks, algorithms=["RS256"], audience=expected_aud,
            issuer=expected_iss, options={"require_exp": True}
        )
        if expected_nonce and payload.get("nonce") != expected_nonce:
            raise ValueError("ID Token nonce mismatch.")
        return payload
    except JOSEError as e:
        raise ValueError(f"Invalid ID token: {e}") from e

def oidc_build_auth_url(state, code_challenge):
    disc = oidc_discovery()
    if not disc: return "/chat" # 如果发现失败，则重定向到主页
    redirect_uri = config.OIDC_REDIRECT_URI or url_for("auth.oidc_callback", _external=True)
    params = urllib.parse.urlencode({
        "response_type": "code", "client_id": config.GITLAB_CLIENT_ID,
        "redirect_uri": redirect_uri, "scope": "openid profile email",
        "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256", "nonce": state.split(".")[0],
    })
    return f"{disc['authorization_endpoint']}?{params}"

def oidc_exchange_token(code, code_verifier):
    disc = oidc_discovery()
    if not disc: return None
    redirect_uri = config.OIDC_REDIRECT_URI or url_for("auth.oidc_callback", _external=True)
    data = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": config.GITLAB_CLIENT_ID, "client_secret": config.GITLAB_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }

    try:
        session = _create_retry_session()
        resp = session.post(disc["token_endpoint"], data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Error exchanging token: {e}")
        return None

# --- Routes ---
@auth_bp.route("/login")
def login():
    state = f"{secrets.token_urlsafe(16)}.{int(time.time())}.{secrets.token_urlsafe(8)}"
    code_verifier = secrets.token_urlsafe(64)
    session["oidc_state"] = state
    session["oidc_state_exp"] = int(time.time()) + 600
    session["code_verifier"] = code_verifier
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    auth_url = oidc_build_auth_url(state, challenge)
    return redirect(auth_url)

@auth_bp.route("/oidc/callback")
def oidc_callback():
    state, code = request.args.get("state"), request.args.get("code")
    sess_state, sess_exp = session.get("oidc_state"), int(session.get("oidc_state_exp") or 0)
    if not state or state != sess_state or int(time.time()) > sess_exp or not code:
        return "Invalid or expired state, or missing code", 400

    token = oidc_exchange_token(code, session.get("code_verifier"))
    if not token or "id_token" not in token:
        return "Failed to exchange token", 400

    try:
        idp = _verify_jwt_rs256(token["id_token"], config.GITLAB_URL, config.GITLAB_CLIENT_ID, state.split(".")[0])
    except ValueError as e:
        return f"ID Token validation failed: {e}", 400

    session.pop("oidc_state", None)
    session.pop("oidc_state_exp", None)
    session.pop("code_verifier", None)

    user_id = idp.get("sub")
    name = idp.get("name") or idp.get("preferred_username") or "user"
    avatar_url = idp.get("picture")

    session["user"] = {"id": user_id, "name": name, "avatar_url": avatar_url}
    # (Req 2) 将 Session 标记为永久（使用 app.config 中设置的 7 天有效期）
    session.permanent = True

    with engine.begin() as conn:
        conn.execute(text("""
                          INSERT INTO users (id, name, avatar_url) VALUES (:id, :name, :avatar)
                              ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, avatar_url=EXCLUDED.avatar_url
                          """), {"id": user_id, "name": name, "avatar": avatar_url})

    return redirect("/chat")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/chat")