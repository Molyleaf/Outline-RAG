# app/main.py
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
# (修复) 导入 Starlette 的 ASGI 兼容中间件
from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
# (移除) 不再使用 Werkzeug (WSGI) 的中间件
# from werkzeug.middleware.proxy_fix import ProxyFix

# 导入配置
import config
# 导入异步任务
import rag
# 导入新的异步蓝图 (APIRouter)
from blueprints.api import api_router
from blueprints.auth import auth_router
from blueprints.views import views_router
# 导入异步数据库
from database import db_init, redis_client, async_engine


# --- 2. 配置日志 (在 Gunicorn/Uvicorn 启动时) ---
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logger = logging.getLogger("main")

# --- 6. 后台任务 (异步) ---

async def task_worker():
    """后台任务处理器，从 Redis 队列中消费任务。"""
    logger.info("后台任务处理器已启动 (异步)。")
    while True:
        try:
            _queue, task_json = await redis_client.brpop("task_queue", timeout=0)
            task_data = json.loads(task_json)
            task_name = task_data.get("task")
            logger.info("接收到新任务: %s", task_name)

            if task_name == "refresh_all":
                await rag.refresh_all_task()
            elif task_name == "process_doc_batch":
                await rag.process_doc_batch_task(task_data.get("doc_ids", []))
            else:
                logger.warning("未知任务类型: %s", task_name)

        except (redis.ConnectionError, asyncio.CancelledError) as e:
            logger.error("Redis 连接错误或任务取消，任务处理器暂停5秒: %s", e)
            await asyncio.sleep(5)
        except TypeError:
            continue
        except Exception as e:
            logger.exception("任务处理器发生未知错误: %s", e)
            await asyncio.sleep(1)


async def webhook_watcher():
    """后台 Webhook 计时器监视器 (异步)。"""
    logger.info("Webhook 监视器已启动 (异步)。")
    while True:
        try:
            due_time_str = await redis_client.get("webhook:refresh_timer_due")
            if due_time_str:
                due_time = int(due_time_str)
                if time.time() > due_time:
                    logger.info("Webhook 计时器到期，触发优雅刷新。")
                    if await redis_client.set("webhook:trigger_lock", "1", ex=60, nx=True):
                        await redis_client.delete("webhook:refresh_timer_due")
                        await redis_client.lpush("task_queue", json.dumps({"task": "refresh_all"}))

        except (redis.ConnectionError, asyncio.CancelledError) as e:
            logger.error("Redis 连接错误或任务取消，Webhook 监视器暂停5秒: %s", e)
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception("Webhook 监视器发生未知错误: %s", e)

        await asyncio.sleep(5)


# --- 7. 启动和关闭事件 (使用 Lifespan) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭事件"""
    logger.info("FastAPI 应用启动...")

    # --- Startup ---
    # 1. 配置检查
    if not config.SECRET_KEY:
        logger.critical("SECRET_KEY 未设置，拒绝启动。")
        sys.exit(1)
    if config.OUTLINE_WEBHOOK_SIGN and not config.OUTLINE_WEBHOOK_SECRET:
        logger.critical("OUTLINE_WEBHOOK_SIGN=true 但 OUTLINE_WEBHOOK_SECRET 为空，拒绝启动。")
        sys.exit(1)

    # 2. 创建目录
    os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)

    # 3. 初始化数据库
    try:
        should_initialize = True
        if redis_client:
            if not await redis_client.set("app:startup:lock", "1", ex=60, nx=True):
                should_initialize = False

        if should_initialize:
            logger.info(f"Worker (pid: {os.getpid()}) 正在执行主初始化...")
            await db_init()
            logger.info("[启动自检] 异步启动，跳过同步 HTTP 自检。")
        else:
            logger.info(f"Worker (pid: {os.getpid()}) 等待主初始化完成...")
            await asyncio.sleep(5)

        # 4. 启动后台任务
        if redis_client:
            asyncio.create_task(task_worker())
            asyncio.create_task(webhook_watcher())
        else:
            logger.warning("Redis 未配置，后台任务和 Webhook 计时器将不会启动。")

    except Exception as e:
        logger.exception("应用启动时初始化失败: %s", e)
        sys.exit(1)

    yield

    # --- Shutdown ---
    logger.info("FastAPI 应用关闭...")
    if async_engine:
        await async_engine.dispose()
    if redis_client:
        await redis_client.close()
    logger.info("资源已释放。")


# --- 1. FastAPI 应用初始化 ---
app = FastAPI(
    title="Outline RAG API",
    version="1.0",
    docs_url=None, # 禁用 /docs
    redoc_url=None, # 禁用 /redoc
    lifespan=lifespan
)

# --- 3. 注册中间件 ---

# 3a. 修复代理后的 HTTPS (mixed content)
# (修复) 使用 Starlette/FastAPI 兼容的 ProxyHeadersMiddleware
# trusted_hosts="*" 表示信任来自任何上游代理的 X-Forwarded-* 头
# 即使 IDE 报错，此行在运行时也是正确的
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# 3b. Session 中间件
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    session_cookie="session",
    max_age=int(timedelta(days=7).total_seconds()), # 7 天
    https_only=False, # 设为 False, ProxyHeadersMiddleware 会处理 proto
    same_site="lax",
)

# --- 4. 注册路由 (APIRouter) ---
app.include_router(views_router, prefix="/chat", tags=["Views"])
app.include_router(auth_router, prefix="/chat", tags=["Auth"])
app.include_router(api_router, prefix="/chat", tags=["API"])


# --- 5. 挂载静态文件 ---
app.mount("/chat/static", StaticFiles(directory="static"), name="static")


# --- 8. 健康检查 ---
@app.get("/healthz", tags=["Health"])
async def healthz():
    """健康检查。"""
    return "ok"

# --- 9. 全局异常处理 ---
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"未捕获的异常在 {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)},
    )