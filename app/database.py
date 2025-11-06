# app/database.py
import logging
import urllib.parse

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import config

logger = logging.getLogger(__name__)

if not config.DATABASE_URL:
    raise SystemExit("缺少 DATABASE_URL 环境变量")

# (*** 核心修改: 切换到 Psycopg 3 ***)
# 确保 URL 是 postgresql+psycopg
if not config.DATABASE_URL.startswith("postgresql+psycopg"):
    logger.warning("DATABASE_URL 不是 postgresql+psycopg，将尝试替换...")
    # 替换掉所有其他可能的驱动
    db_url = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://")
else:
    db_url = config.DATABASE_URL

# (*** 核心修改 ***)
# create_async_engine 现在会查找并使用 'psycopg' (Psycopg 3)
async_engine = create_async_engine(db_url, future=True)

# (以下代码保持不变)
AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# --- 异步 Redis 连接 (不变) ---
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

        redis_client = redis.Redis(
            host=parsed_url.hostname,
            port=parsed_url.port,
            password=parsed_url.password,
            db=db_num,
            decode_responses=True
        )
        logger.info("Redis (asyncio) 客户端已配置。")
    except Exception as e:
        logger.critical("Failed to configure async Redis: %s", e)
        redis_client = None
else:
    logger.warning("REDIS_URL not set, refresh task status will not be available.")

# --- DDL (不变) ---
PRE_TX_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"

TX_INIT_SQL = f"""
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
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# --- db_init (不变) ---
async def db_init():
    """异步初始化数据库"""

    async with async_engine.connect() as conn_lock:

        conn_ac = await conn_lock.execution_options(isolation_level="AUTOCOMMIT")
        await conn_ac.execute(text("SELECT pg_advisory_lock(9876543210)"))
        logger.info("数据库咨询锁已获取。")

        try:
            await conn_ac.execute(text(PRE_TX_SQL))

            async with async_engine.connect() as conn_tx:
                async with conn_tx.begin():
                    logger.info("数据库事务已开始，正在执行 INIT_SQL...")

                    commands = [cmd.strip() for cmd in TX_INIT_SQL.split(';') if cmd.strip()]

                    for sql_command in commands:
                        await conn_tx.execute(text(sql_command))

                    await conn_tx.execute(text("ANALYZE"))

            logger.info("数据库表结构初始化/检查完成 (异步)。")

        except Exception as e:
            logger.error(f"数据库初始化 (db_init) 失败: {e}", exc_info=True)
            raise

        finally:
            logger.info("释放数据库咨询锁...")
            await conn_ac.execute(text("SELECT pg_advisory_unlock(9876543210)"))