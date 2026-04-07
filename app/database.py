"""应用侧 Postgres 与 Redis 初始化。"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg
import redis.asyncio as redis

from . import config

logger = logging.getLogger(__name__)

_db_pool: asyncpg.Pool | None = None
_db_pool_lock = asyncio.Lock()

APP_SCHEMA_SQL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      name TEXT,
      avatar_url TEXT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "DROP TABLE IF EXISTS outline_sync_manifest",
]


def normalize_database_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL 未配置，当前架构要求 Postgres 为必选依赖。")
    if value.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL 不再支持 psycopg DSN，请改为 postgresql+asyncpg:// 或 postgresql://。")
    if value.startswith("postgresql+asyncpg://"):
        return "postgresql://" + value.removeprefix("postgresql+asyncpg://")
    return value


def parse_database_url(raw_url: str | None = None) -> dict[str, str]:
    normalized = normalize_database_url(raw_url or config.DATABASE_URL)
    parsed = urllib.parse.urlparse(normalized)
    database = urllib.parse.unquote(parsed.path.lstrip("/"))

    if not parsed.hostname or parsed.username is None or not database:
        raise RuntimeError("DATABASE_URL 缺少 host / username / database，无法初始化 Postgres。")

    query = urllib.parse.parse_qs(parsed.query)
    return {
        "dsn": normalized,
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": urllib.parse.unquote(parsed.username),
        "password": urllib.parse.unquote(parsed.password or ""),
        "database": database,
        "sslmode": query.get("sslmode", [""])[0],
    }


async def get_db_pool() -> asyncpg.Pool:
    global _db_pool

    if _db_pool is not None:
        return _db_pool

    async with _db_pool_lock:
        if _db_pool is None:
            _db_pool = await asyncpg.create_pool(
                dsn=parse_database_url()["dsn"],
                min_size=1,
                max_size=max(config.DATABASE_MAX_CONNECTIONS, 1),
                command_timeout=60,
            )
            logger.info("应用侧 asyncpg 连接池已初始化。")
    return _db_pool


@asynccontextmanager
async def postgres_connection() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        yield conn


async def fetch_all(sql: str, *params: Any) -> list[dict[str, Any]]:
    async with postgres_connection() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(row) for row in rows]


async def fetch_one(sql: str, *params: Any) -> dict[str, Any] | None:
    async with postgres_connection() as conn:
        row = await conn.fetchrow(sql, *params)
    return dict(row) if row else None


async def execute(sql: str, *params: Any) -> None:
    async with postgres_connection() as conn:
        await conn.execute(sql, *params)


async def executemany(sql: str, params_seq: list[tuple[Any, ...]]) -> None:
    if not params_seq:
        return
    async with postgres_connection() as conn:
        async with conn.transaction():
            await conn.executemany(sql, params_seq)


async def db_init() -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for statement in APP_SCHEMA_SQL:
                await conn.execute(statement)
    logger.info("应用侧 Postgres 表结构初始化完成。")


async def close_database() -> None:
    global _db_pool

    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        logger.info("应用侧 asyncpg 连接池已关闭。")


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
