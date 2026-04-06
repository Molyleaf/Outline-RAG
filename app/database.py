"""数据库与 Redis 初始化。

LightRAG 主数据改为文件存储；数据库仅用于可选的用户信息落库。
"""

from __future__ import annotations

import logging
import urllib.parse

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import config

logger = logging.getLogger(__name__)


async_engine: AsyncEngine | None = None
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None

if config.DATABASE_URL:
    async_engine = create_async_engine(
        config.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    AsyncSessionLocal = async_sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info("AsyncEngine 已配置。")
else:
    logger.warning("DATABASE_URL 未配置，用户信息将仅保存在会话 Cookie 中。")


redis_client = None
if config.REDIS_URL:
    try:
        parsed_url = urllib.parse.urlparse(config.REDIS_URL)
        db_num = 0
        if parsed_url.path and parsed_url.path.startswith("/"):
            try:
                db_num = int(parsed_url.path[1:])
            except (ValueError, IndexError):
                db_num = 0

        redis_client = redis.Redis(
            host=parsed_url.hostname,
            port=parsed_url.port,
            password=parsed_url.password,
            db=db_num,
            decode_responses=True,
        )
        logger.info("Redis 客户端已配置。")
    except Exception as exc:  # pragma: no cover
        logger.critical("Redis 配置失败: %s", exc)
        redis_client = None
else:
    logger.info("REDIS_URL 未配置，OIDC 元数据缓存将退化为进程内请求。")


TX_INIT_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT,
  avatar_url TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def db_init() -> None:
    """初始化最小数据库结构。"""
    if not async_engine:
        return

    async with async_engine.connect() as conn_lock:
        conn_ac = await conn_lock.execution_options(isolation_level="AUTOCOMMIT")
        await conn_ac.execute(text("SELECT pg_advisory_lock(9876543210)"))
        logger.info("数据库咨询锁已获取。")

        try:
            async with async_engine.begin() as conn_tx:
                commands = [cmd.strip() for cmd in TX_INIT_SQL.split(";") if cmd.strip()]
                for sql_command in commands:
                    await conn_tx.execute(text(sql_command))
            logger.info("数据库表结构初始化完成。")
        finally:
            await conn_ac.execute(text("SELECT pg_advisory_unlock(9876543210)"))
            logger.info("数据库咨询锁已释放。")
