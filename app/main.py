import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from . import config, rag
from .blueprints import api_router, auth_router
from .database import close_database, db_init, redis_client
from .lightrag_runtime import get_runtime

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
logger = logging.getLogger("main")

_PUBLIC_CHAT_PATHS = {
    "/chat/login",
    "/chat/logout",
    "/chat/oidc/callback",
    "/chat/update/webhook",
}


def _validate_required_settings() -> None:
    required_settings = {
        "SECRET_KEY": config.SECRET_KEY,
        "DATABASE_URL": config.DATABASE_URL,
        "NEO4J_URI": config.NEO4J_URI,
        "NEO4J_USERNAME": config.NEO4J_USERNAME,
        "NEO4J_PASSWORD": config.NEO4J_PASSWORD,
        "OUTLINE_API_URL": config.OUTLINE_API_URL,
        "OUTLINE_API_TOKEN": config.OUTLINE_API_TOKEN,
        "GITLAB_URL": config.GITLAB_URL,
        "GITLAB_CLIENT_ID": config.GITLAB_CLIENT_ID,
        "GITLAB_CLIENT_SECRET": config.GITLAB_CLIENT_SECRET,
        "LLM_API_KEY": config.LLM_API_KEY,
        "LLM_MODEL": config.LLM_MODEL,
        "EMBEDDING_API_KEY": config.EMBEDDING_API_KEY,
        "EMBEDDING_MODEL": config.EMBEDDING_MODEL,
    }
    missing = [name for name, value in required_settings.items() if not str(value).strip()]

    if config.OUTLINE_WEBHOOK_SIGN and not config.OUTLINE_WEBHOOK_SECRET:
        missing.append("OUTLINE_WEBHOOK_SECRET")

    if missing:
        raise RuntimeError(f"缺少必要配置: {', '.join(sorted(set(missing)))}")


def create_app() -> FastAPI:
    _validate_required_settings()
    runtime = get_runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("FastAPI 应用启动...")

        os.makedirs(config.LIGHTRAG_WORKING_DIR, exist_ok=True)
        os.makedirs(config.LIGHTRAG_INPUT_DIR, exist_ok=True)

        try:
            await db_init()
            async with runtime.lifespan():
                yield
        except Exception as exc:
            logger.exception("应用启动失败: %s", exc)
            raise
        finally:
            logger.info("FastAPI 应用关闭...")
            await rag.shutdown_background_tasks()
            await close_database()
            if redis_client:
                await redis_client.close()
            logger.info("资源已释放。")

    app = FastAPI(
        title=config.APP_NAME,
        version="2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")  # type: ignore[arg-type]
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie="session",
        max_age=int(timedelta(days=7).total_seconds()),
        https_only=False,
        same_site="lax",
    )

    app.include_router(auth_router, prefix="/chat", tags=["Auth"])
    app.include_router(api_router, prefix="/chat", tags=["API"])

    @app.middleware("http")
    async def require_chat_session(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/chat") or path in _PUBLIC_CHAT_PATHS:
            return await call_next(request)

        if request.session.get("user"):
            return await call_next(request)

        accept = request.headers.get("accept", "").lower()
        if request.method == "GET" and "text/html" in accept:
            return RedirectResponse("/chat/login", status_code=303)

        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    @app.get("/chat", include_in_schema=False)
    async def chat_entry():
        return RedirectResponse("/chat/webui/", status_code=303)

    app.mount("/chat", runtime.chat_app, name="lightrag")

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error("未捕获异常 %s: %s", request.url, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "服务器内部错误"},
        )

    return app


app = create_app()
