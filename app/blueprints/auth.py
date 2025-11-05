# app/blueprints/auth.py
import base64
import hashlib
import json
import secrets
import time
import urllib.parse

import config
# (ASYNC REFACTOR)
import httpx
from database import AsyncSessionLocal, redis_client
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
# ---
from jose import jwt
from jose.exceptions import JOSEError
from sqlalchemy import text

# (ASYNC REFACTOR)
auth_router = APIRouter()

# --- (ASYNC REFACTOR) 创建带重试的 httpx Client ---
def _create_retry_client() -> httpx.AsyncClient:
    """创建带重试的 httpx.AsyncClient"""
    retry_strategy = httpx.Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    transport = httpx.AsyncHTTPTransport(retries=retry_strategy)
    # (ASYNC REFACTOR) OIDC 客户端使用单独的 client，超时时间短
    client = httpx.AsyncClient(transport=transport, timeout=10)
    return client

# --- OIDC Helpers (ASYNC REFACTOR) ---
async def oidc_discovery(client: httpx.AsyncClient):
    """(ASYNC REFACTOR) 异步获取OIDC配置"""
    cache_key = "oidc:discovery"
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    try:
        resp = await client.get(f"{config.GITLAB_URL}/.well-known/openid-configuration")
        resp.raise_for_status()
        data = resp.json()
        if redis_client:
            await redis_client.set(cache_key, json.dumps(data), ex=43200) # 缓存12小时
        return data
    except httpx.HTTPError as e:
        print(f"Error during OIDC discovery (async): {e}")
        return None

async def _get_jwks(client: httpx.AsyncClient, jwks_uri: str):
    """(ASYNC REFACTOR) 异步获取JWKS"""
    cache_key = f"oidc:jwks:{jwks_uri}"
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    try:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        data = resp.json()
        if redis_client:
            await redis_client.set(cache_key, json.dumps(data), ex=43200) # 缓存12小时
        return data
    except httpx.HTTPError as e:
        print(f"Error fetching JWKS (async): {e}")
        return None

async def _verify_jwt_rs256(client: httpx.AsyncClient, id_token, expected_iss, expected_aud, expected_nonce=None):
    """(ASYNC REFACTOR) 异步验证JWT"""
    try:
        disc = await oidc_discovery(client)
        if not disc: raise ValueError("Could not fetch OIDC discovery document.")
        jwks = await _get_jwks(client, disc["jwks_uri"])
        if not jwks: raise ValueError("Could not fetch JWKS.")

        # jwt.decode 是 CPU 密集型，同步运行即可
        payload = jwt.decode(
            id_token, jwks, algorithms=["RS256"], audience=expected_aud,
            issuer=expected_iss, options={"require_exp": True}
        )
        if expected_nonce and payload.get("nonce") != expected_nonce:
            raise ValueError("ID Token nonce mismatch.")
        return payload
    except JOSEError as e:
        raise ValueError(f"Invalid ID token: {e}") from e

async def oidc_build_auth_url(request: Request, client: httpx.AsyncClient, state, code_challenge):
    """(ASYNC REFACTOR)"""
    disc = await oidc_discovery(client)
    if not disc: return "/chat" # 如果发现失败，则重定向到主页

    # (ASYNC REFACTOR) 使用 request.url_for
    redirect_uri = config.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))

    params = urllib.parse.urlencode({
        "response_type": "code", "client_id": config.GITLAB_CLIENT_ID,
        "redirect_uri": redirect_uri, "scope": "openid profile email",
        "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256", "nonce": state.split(".")[0],
    })
    return f"{disc['authorization_endpoint']}?{params}"

async def oidc_exchange_token(request: Request, client: httpx.AsyncClient, code, code_verifier):
    """(ASYNC REFACTOR)"""
    disc = await oidc_discovery(client)
    if not disc: return None

    # (ASYNC REFACTOR) 使用 request.url_for
    redirect_uri = config.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))

    data = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": config.GITLAB_CLIENT_ID, "client_secret": config.GITLAB_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }

    try:
        resp = await client.post(disc["token_endpoint"], data=data)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        print(f"Error exchanging token (async): {e}")
        return None

# --- (ASYNC REFACTOR) FastAPI 依赖注入 OIDC 客户端 ---
def get_oidc_client():
    return _create_retry_client()


# --- Routes (ASYNC REFACTOR) ---
@auth_router.get("/login")
async def login(request: Request, client: httpx.AsyncClient = Depends(get_oidc_client)):
    state = f"{secrets.token_urlsafe(16)}.{int(time.time())}.{secrets.token_urlsafe(8)}"
    code_verifier = secrets.token_urlsafe(64)

    # (ASYNC REFACTOR) 使用 request.session
    request.session["oidc_state"] = state
    request.session["oidc_state_exp"] = int(time.time()) + 600
    request.session["code_verifier"] = code_verifier

    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    auth_url = await oidc_build_auth_url(request, client, state, challenge)

    await client.aclose()
    return RedirectResponse(auth_url)

@auth_router.get("/oidc/callback")
async def oidc_callback(request: Request, state: str = None, code: str = None, client: httpx.AsyncClient = Depends(get_oidc_client)):
    # (ASYNC REFACTOR) 使用 request.session
    sess_state = request.session.get("oidc_state")
    sess_exp = int(request.session.get("oidc_state_exp") or 0)

    if not state or state != sess_state or int(time.time()) > sess_exp or not code:
        return Response("Invalid or expired state, or missing code", status_code=400)

    token = await oidc_exchange_token(request, client, code, request.session.get("code_verifier"))
    if not token or "id_token" not in token:
        return Response("Failed to exchange token", status_code=400)

    try:
        idp = await _verify_jwt_rs256(client, token["id_token"], config.GITLAB_URL, config.GITLAB_CLIENT_ID, state.split(".")[0])
    except ValueError as e:
        return Response(f"ID Token validation failed: {e}", status_code=400)
    finally:
        await client.aclose()

    # (ASYNC REFACTOR)
    request.session.pop("oidc_state", None)
    request.session.pop("oidc_state_exp", None)
    request.session.pop("code_verifier", None)

    user_id = idp.get("sub")
    name = idp.get("name") or idp.get("preferred_username") or "user"
    avatar_url = idp.get("picture")

    request.session["user"] = {"id": user_id, "name": name, "avatar_url": avatar_url}
    # (ASYNC REFACTOR) SessionMiddleware 会处理 session 的持久化 (max_age)

    # (*** 这是对 Error 2 的核心修复 ***)
    # (ASYNC REFACTOR) 使用异步 session
    try:
        async with AsyncSessionLocal.begin() as session:
            await session.execute(text("""
                                       INSERT INTO users (id, name, avatar_url) VALUES (:id, :name, :avatar)
                                           ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, avatar_url=EXCLUDED.avatar_url
                                       """), {"id": user_id, "name": name, "avatar": avatar_url})
    except Exception as e:
        logger.error(f"Failed to upsert user {user_id} during OIDC callback: {e}", exc_info=True)
        return Response(f"Failed to update user database: {e}", status_code=500)

    return RedirectResponse("/chat")

@auth_router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/chat")