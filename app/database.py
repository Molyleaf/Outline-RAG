# app/database.py
import logging
import urllib.parse

# (ASYNC REFACTOR) 导入 redis.asyncio
import redis.asyncio as redis
# (*** 修复 ***) 导入 text
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

# --- (*** 修复 ***) 分离 DDL ---
# 1. 必须在事务外 (AUTOCOMMIT 模式) 执行的命令
PRE_TX_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"

# 2. 应该在事务内执行的命令
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
  created_at TIMESTAMTz NOT NULL DEFAULT NOW()
);
"""

# (ASYNC REFACTOR) (*** 最终修复 ***)
async def db_init():
    """异步初始化数据库"""

    # 1. 从池中获取一个连接
    async with async_engine.connect() as conn:

        # 2. (AUTOCOMMIT) 获取咨询锁
        # (*** 修复 ***)
        # 派生一个 AUTOCOMMIT connection wrapper (conn_ac)
        conn_ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn_ac.execute(text("SELECT pg_advisory_lock(9876543210)"))
        logger.info("数据库咨询锁已获取。")

        try:
            # 3. (AUTOCOMMIT) 创建扩展
            # (*** 修复 ***)
            # 重用 'conn_ac' (AUTOCOMMIT 连接)
            await conn_ac.execute(text(PRE_TX_SQL))

            # (*** 修复 ***)
            # 在尝试使用 'conn.begin()' 之前，必须显式关闭
            # 'conn_ac' wrapper，以将父 'conn' 的状态重置。
            await conn_ac.close()

            # 4. (TRANSACTIONAL) 执行所有 DDL
            # 'conn' (父连接) 现在是干净的，可以安全地启动事务
            async with conn.begin():
                logger.info("数据库事务已开始，正在执行 INIT_SQL...")
                # 运行同步代码块 (因为 TX_INIT_SQL 是一个大字符串)
                await conn.run_sync(lambda sync_conn: sync_conn.execute(text(TX_INIT_SQL)))
                await conn.run_sync(lambda sync_conn: sync_conn.execute(text("ANALYZE")))

            logger.info("数据库表结构初始化/检查完成 (异步)。")

        except Exception as e:
            # (关键) 捕获并记录 *真正* 的初始化错误
            logger.error(f"数据库初始化 (db_init) 失败: {e}", exc_info=True)
            # 重新抛出异常，以便 main.py 知道启动失败
            raise

        finally:
            # 5. (AUTOCOMMIT) 释放锁
            logger.info("释放数据库咨询锁...")
            # (*** 修复 ***)
            # 不要重用 'conn_ac' (它可能已关闭或状态错误)。
            # 派生一个 *新* 的 AUTOCOMMIT wrapper 来安全地释放锁。
            conn_ac_final = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn_ac_final.execute(text("SELECT pg_advisory_unlock(9876543210)"))
            # (*** 修复 ***)
            # 关闭这个 final wrapper
            await conn_ac_final.close()