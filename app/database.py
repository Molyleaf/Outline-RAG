# app/database.py
import logging
import urllib.parse

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine

import config

logger = logging.getLogger(__name__)

if not config.DATABASE_URL:
    raise SystemExit("缺少 DATABASE_URL 环境变量")

# --- 强制使用 asyncpg 驱动 ---
if not config.DATABASE_URL.startswith("postgresql+asyncpg"):
    logger.warning("DATABASE_URL 不是 postgresql+asyncpg，将尝试替换...")
    db_url = config.DATABASE_URL.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
else:
    db_url = config.DATABASE_URL

# 强制客户端编码 UTF8
if "client_encoding" not in db_url:
    connector = "&" if "?" in db_url else "?"
    db_url += f"{connector}client_encoding=utf8"

# --- 创建异步引擎 ---
async_engine = create_async_engine(db_url, future=True)

# --- 兼容 langchain_postgres (_pool.connect) 的包装 ---
class EngineCompatProxy(AsyncEngine):
    """兼容 langchain_postgres v0.0.16 使用 _pool.connect() 的包装"""
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def __getattr__(self, name):
        if name == "_pool":
            class _PoolShim:
                def __init__(self, engine):
                    self._engine = engine
                def connect(self):
                    return self._engine.connect()
            return _PoolShim(self._engine)
        return getattr(self._engine, name)

async_engine = EngineCompatProxy(async_engine)
logger.info("Wrapped async_engine with EngineCompatProxy for legacy _pool support.")

# --- Session 工厂 ---
AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# --- 异步 Redis 连接 ---
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

# --- 基础表结构 SQL ---
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

# --- 新增：PGVector 表结构 ---
# 使用 text-embedding-3-small (1024维)，可自行改成 3072 等
PGVECTOR_TABLE_SQL = """
                     CREATE TABLE IF NOT EXISTS langchain_pg_embedding (
                                                                           langchain_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                         collection_id UUID,
                         embedding vector(1024),
                         document TEXT,
                         cmetadata JSONB,
                         created_at TIMESTAMPTZ DEFAULT now()
                         ); \
                     """

# --- 异步数据库初始化 ---
async def db_init():
    """异步初始化数据库"""
    async with async_engine.connect() as conn_lock:
        conn_ac = await conn_lock.execution_options(isolation_level="AUTOCOMMIT")

        # 检查数据库编码
        encoding_row = await conn_ac.execute(text("SHOW SERVER_ENCODING"))
        encoding_val = encoding_row.scalar_one_or_none()
        if encoding_val and encoding_val.upper() != "UTF8":
            logger.warning(f"数据库编码为 {encoding_val}，建议使用 UTF8 以支持中文。")

        await conn_ac.execute(text("SELECT pg_advisory_lock(9876543210)"))
        logger.info("数据库咨询锁已获取。")

        try:
            # 启用 pgvector 扩展
            await conn_ac.execute(text(PRE_TX_SQL))

            async with async_engine.connect() as conn_tx:
                async with conn_tx.begin():
                    logger.info("数据库事务已开始，正在执行 INIT_SQL...")
                    commands = [cmd.strip() for cmd in TX_INIT_SQL.split(';') if cmd.strip()]
                    for sql_command in commands:
                        await conn_tx.execute(text(sql_command))

                    # 新增: 确保 PGVector 表存在
                    await conn_tx.execute(text(PGVECTOR_TABLE_SQL))
                    await conn_tx.execute(text("ANALYZE"))

            logger.info("数据库表结构初始化/检查完成 (异步)。")

        except Exception as e:
            logger.error(f"数据库初始化 (db_init) 失败: {e}", exc_info=True)
            raise

        finally:
            logger.info("释放数据库咨询锁...")
            await conn_ac.execute(text("SELECT pg_advisory_unlock(9876543210)"))
