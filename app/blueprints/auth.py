"""OIDC 登录与会话辅助。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.parse
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from httpx_retries import Retry, RetryTransport
from jose import jwt
from jose.exceptions import JOSEError

from .. import config
from ..database import execute, redis_client

auth_router = APIRouter()
logger = logging.getLogger(__name__)


def get_current_user_optional(request: Request) -> dict[str, Any] | None:
    return request.session.get("user")


def require_authenticated_user(request: Request) -> dict[str, Any]:
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _create_retry_client() -> httpx.AsyncClient:
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    return httpx.AsyncClient(
        transport=RetryTransport(
            retry=retry_strategy,
            transport=httpx.AsyncHTTPTransport(),
        ),
        timeout=10,
    )


async def oidc_discovery(client: httpx.AsyncClient) -> dict[str, Any] | None:
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
            await redis_client.set(cache_key, json.dumps(data), ex=43200)
        return data
    except httpx.HTTPError as exc:
        logger.warning("OIDC discovery 失败: %s", exc)
        return None


async def _get_jwks(client: httpx.AsyncClient, jwks_uri: str) -> dict[str, Any] | None:
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
            await redis_client.set(cache_key, json.dumps(data), ex=43200)
        return data
    except httpx.HTTPError as exc:
        logger.warning("OIDC JWKS 获取失败: %s", exc)
        return None


async def _verify_jwt_rs256(
    client: httpx.AsyncClient,
    id_token: str,
    expected_iss: str,
    expected_aud: str,
    expected_nonce: str | None = None,
) -> dict[str, Any]:
    try:
        discovery = await oidc_discovery(client)
        if not discovery:
            raise ValueError("无法获取 OIDC Discovery 文档")
        jwks = await _get_jwks(client, discovery["jwks_uri"])
        if not jwks:
            raise ValueError("无法获取 OIDC JWKS")

        payload = jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=expected_aud,
            issuer=expected_iss,
            options={"require_exp": True},
        )
        if expected_nonce and payload.get("nonce") != expected_nonce:
            raise ValueError("ID Token nonce 不匹配")
        return payload
    except JOSEError as exc:
        raise ValueError(f"无效的 ID Token: {exc}") from exc


async def oidc_build_auth_url(
    request: Request,
    client: httpx.AsyncClient,
    state: str,
    code_challenge: str,
) -> str:
    discovery = await oidc_discovery(client)
    if not discovery:
        return "/chat"

    redirect_uri = config.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))
    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": config.GITLAB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "nonce": state.split(".")[0],
        }
    )
    return f"{discovery['authorization_endpoint']}?{params}"


async def oidc_exchange_token(
    request: Request,
    client: httpx.AsyncClient,
    code: str,
    code_verifier: str | None,
) -> dict[str, Any] | None:
    discovery = await oidc_discovery(client)
    if not discovery:
        return None

    redirect_uri = config.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.GITLAB_CLIENT_ID,
        "client_secret": config.GITLAB_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }

    try:
        resp = await client.post(discovery["token_endpoint"], data=data)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("OIDC Token 交换失败: %s", exc)
        return None


def get_oidc_client() -> httpx.AsyncClient:
    return _create_retry_client()


async def _upsert_user(user_id: str, name: str, avatar_url: str | None) -> None:
    try:
        await execute(
            """
            INSERT INTO users (id, name, avatar_url, updated_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                avatar_url = EXCLUDED.avatar_url,
                updated_at = CURRENT_TIMESTAMP
            """,
            user_id,
            name,
            avatar_url,
        )
    except Exception as exc:  # pragma: no cover
        logger.error("更新用户表失败: %s", exc, exc_info=True)


@auth_router.get("/login")
async def login(
    request: Request,
    client: httpx.AsyncClient = Depends(get_oidc_client),
):
    if not config.GITLAB_URL or not config.GITLAB_CLIENT_ID:
        await client.aclose()
        return Response("OIDC 未配置", status_code=503)

    state = f"{secrets.token_urlsafe(16)}.{int(time.time())}.{secrets.token_urlsafe(8)}"
    code_verifier = secrets.token_urlsafe(64)

    request.session["oidc_state"] = state
    request.session["oidc_state_exp"] = int(time.time()) + 600
    request.session["code_verifier"] = code_verifier

    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    auth_url = await oidc_build_auth_url(request, client, state, challenge)

    await client.aclose()
    return RedirectResponse(auth_url)


@auth_router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    client: httpx.AsyncClient = Depends(get_oidc_client),
):
    sess_state = request.session.get("oidc_state")
    sess_exp = int(request.session.get("oidc_state_exp") or 0)

    if not state or state != sess_state or int(time.time()) > sess_exp or not code:
        await client.aclose()
        return Response("Invalid or expired state, or missing code", status_code=400)

    token = await oidc_exchange_token(
        request,
        client,
        code,
        request.session.get("code_verifier"),
    )
    if not token or "id_token" not in token:
        await client.aclose()
        return Response("Failed to exchange token", status_code=400)

    try:
        idp = await _verify_jwt_rs256(
            client,
            token["id_token"],
            config.GITLAB_URL,
            config.GITLAB_CLIENT_ID,
            state.split(".")[0],
        )
    except ValueError as exc:
        return Response(f"ID Token validation failed: {exc}", status_code=400)
    finally:
        await client.aclose()

    request.session.clear()

    user_id = idp.get("sub")
    name = idp.get("name") or idp.get("preferred_username") or "user"
    avatar_url = idp.get("picture")

    request.session["sid"] = secrets.token_urlsafe(16)
    request.session["user"] = {
        "id": user_id,
        "name": name,
        "avatar_url": avatar_url,
    }

    if user_id:
        await _upsert_user(user_id, name, avatar_url)

    return RedirectResponse("/chat", status_code=303)


@auth_router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse("/chat", status_code=303)
    response.delete_cookie(key="session", path="/")
    return response
