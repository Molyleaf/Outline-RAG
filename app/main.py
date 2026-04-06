import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import config
import rag
from blueprints.api import api_router
from blueprints.auth import auth_router
from database import close_database, db_init, redis_client
from lightrag_runtime import get_runtime

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
logger = logging.getLogger("main")

runtime = get_runtime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI 应用启动...")

    if not config.SECRET_KEY:
        logger.critical("SECRET_KEY 未设置，拒绝启动。")
        sys.exit(1)

    if config.OUTLINE_WEBHOOK_SIGN and not config.OUTLINE_WEBHOOK_SECRET:
        logger.critical("OUTLINE_WEBHOOK_SIGN=true 但 OUTLINE_WEBHOOK_SECRET 为空，拒绝启动。")
        sys.exit(1)

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
app.include_router(api_router, prefix="/chat", tags=["Compatibility"])


@app.get("/chat", include_in_schema=False)
async def chat_entry(request: Request):
    if "user" not in (request.session or {}):
        return RedirectResponse("/chat/login", status_code=303)
    return RedirectResponse("/chat/", status_code=303)


app.mount("/chat", runtime.protected_app, name="lightrag")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/chat", status_code=303)


@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("未捕获异常 %s: %s", request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)},
    )
