# app/blueprints/auth.py
import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.parse

import config
import httpx
from database import AsyncSessionLocal, redis_client
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, Response
from httpx_retries import RetryTransport, Retry
from jose import jwt
from jose.exceptions import JOSEError
from sqlalchemy import text

auth_router = APIRouter()
logger = logging.getLogger(__name__)

# --- 创建带重试的 httpx Client ---
def _create_retry_client() -> httpx.AsyncClient:
    """创建带 httpx-retries 的 AsyncClient"""

    # 1. 定义 Retry 策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )

    # 2. 定义要包装的底层 transport (默认)
    base_transport = httpx.AsyncHTTPTransport()

    # 3. 使用 'transport' 参数
    transport = RetryTransport(
        retry=retry_strategy,
        transport=base_transport
    )

    # 4. 创建客户端 (OIDC 超时时间短)
    client = httpx.AsyncClient(transport=transport, timeout=10)
    return client

# --- OIDC Helpers ---
async def oidc_discovery(client: httpx.AsyncClient):
    """异步获取OIDC配置"""
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
        logger.warning(f"Error during OIDC discovery (async): {e}")
        return None

async def _get_jwks(client: httpx.AsyncClient, jwks_uri: str):
    """异步获取JWKS"""
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
        logger.warning(f"Error fetching JWKS (async): {e}")
        return None

async def _verify_jwt_rs256(client: httpx.AsyncClient, id_token, expected_iss, expected_aud, expected_nonce=None):
    """异步验证JWT"""
    try:
        disc = await oidc_discovery(client)
        if not disc: raise ValueError("Could not fetch OIDC discovery document.")
        jwks = await _get_jwks(client, disc["jwks_uri"])
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

async def oidc_build_auth_url(request: Request, client: httpx.AsyncClient, state, code_challenge):
    disc = await oidc_discovery(client)
    if not disc: return "/chat"

    redirect_uri = config.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))

    params = urllib.parse.urlencode({
        "response_type": "code", "client_id": config.GITLAB_CLIENT_ID,
        "redirect_uri": redirect_uri, "scope": "openid profile email",
        "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256", "nonce": state.split(".")[0],
    })
    return f"{disc['authorization_endpoint']}?{params}"

async def oidc_exchange_token(request: Request, client: httpx.AsyncClient, code, code_verifier):
    disc = await oidc_discovery(client)
    if not disc: return None

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
        logger.warning(f"Error exchanging token (async): {e}")
        return None

# --- FastAPI 依赖注入 OIDC 客户端 ---
def get_oidc_client():
    return _create_retry_client()


# --- Routes ---
@auth_router.get("/login")
async def login(request: Request, client: httpx.AsyncClient = Depends(get_oidc_client)):
    state = f"{secrets.token_urlsafe(16)}.{int(time.time())}.{secrets.token_urlsafe(8)}"
    code_verifier = secrets.token_urlsafe(64)

    request.session["oidc_state"] = state
    request.session["oidc_state_exp"] = int(time.time()) + 600
    request.session["code_verifier"] = code_verifier

    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    auth_url = await oidc_build_auth_url(request, client, state, challenge)

    await client.aclose()
    return RedirectResponse(auth_url)

@auth_router.get("/oidc/callback")
async def oidc_callback(request: Request, state: str = None, code: str = None, client: httpx.AsyncClient = Depends(get_oidc_client)):
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

    request.session.pop("oidc_state", None)
    request.session.pop("oidc_state_exp", None)
    request.session.pop("code_verifier", None)

    user_id = idp.get("sub")
    name = idp.get("name") or idp.get("preferred_username") or "user"
    avatar_url = idp.get("picture")

    request.session["user"] = {"id": user_id, "name": name, "avatar_url": avatar_url}

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