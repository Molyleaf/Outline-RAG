# app/database.py
import logging
import urllib.parse

# (ASYNC REFACTOR) 导入 redis.asyncio
import redis.asyncio as redis
# (*** 修复 1 ***) 导入 text
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import config

logger = logging.getLogger(__name__)

if not config.DATABASE_URL:
    raise SystemExit("缺少 DATABASE_URL 环境变量")

# (ASYNC REFACTOR) 确保 URL 是 asyncpg
if not config.DATABASE_URL.startswith("postgresql+asyncpg"):
    logger.warning("DATABASE_URL 不是 postgresql+asyncpg，将尝试替换...")
    db_url = config.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
else:
    db_url = config.DATABASE_URL

# (ASYNC REFACTOR) 创建异步引擎
async_engine = create_async_engine(db_url, future=True)

# (ASYNC REFACTOR) 创建异步 Session
AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# --- (ASYNC REFACTOR) 异步 Redis 连接 ---
redis_client = None
if config.REDIS_URL:
    try:
        parsed_url = urllib.parse.urlparse(config.REDIS_URL)
        db_num = 0
        if parsed_url.path and parsed_url.path.startswith('/'):
            try:
                db_num = int(parsed_url.path[1:])
            except (ValueError, IndexError):
                db_num = 0

        # (ASYNC REFACTOR) 使用 redis.asyncio.Redis
        redis_client = redis.Redis(
            host=parsed_url.hostname,
            port=parsed_url.port,
            password=parsed_url.password,
            db=db_num,
            decode_responses=True
        )
        # (ASYNC REFACTOR) ping() 现在是异步的，在 main.py 的 startup 中检查
        logger.info("Redis (asyncio) 客户端已配置。")
    except Exception as e:
        logger.critical("Failed to configure async Redis: %s", e)
        redis_client = None
else:
    logger.warning("REDIS_URL not set, refresh task status will not be available.")

# --- (不变) 初始化 SQL ---
# (注意：database.py 中的 INIT_SQL 和 db_init() 是同步的)
# (我们将修改 db_init() 为异步)
INIT_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT,
  avatar_url TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conversations_user_created_at_desc ON conversations(user_id, created_at DESC) INCLUDE (title);

CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  model TEXT,
  temperature REAL,
  top_p REAL
);

CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_conv_id_id_asc ON messages(conv_id, id ASC);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);

CREATE TABLE IF NOT EXISTS attachments (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMTz NOT NULL DEFAULT NOW()
);
"""

# (ASYNC REFACTOR)
async def db_init():
    """异步初始化数据库"""
    async with async_engine.begin() as conn:
        # 使用 run_sync 在异步连接上执行同步 DDL
        # (*** 修复 1 ***) 将所有原始字符串 SQL 用 text() 包裹
        await conn.run_sync(lambda sync_conn: sync_conn.execute(text(f"SELECT pg_advisory_lock(9876543210)")))
        try:
            await conn.run_sync(lambda sync_conn: sync_conn.execute(text(INIT_SQL)))
            await conn.run_sync(lambda sync_conn: sync_conn.execute(text("ANALYZE")))
            logger.info("数据库表结构初始化/检查完成 (异步)。")
        finally:
            await conn.run_sync(lambda sync_conn: sync_conn.execute(text("SELECT pg_advisory_unlock(9876543210)")))