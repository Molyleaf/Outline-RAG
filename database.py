# database.py
# 负责数据库连接引擎的创建和表结构的初始化
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging
import config
import redis

logger = logging.getLogger(__name__)

if not config.DATABASE_URL:
    raise SystemExit("缺少 DATABASE_URL 环境变量")

engine = create_engine(config.DATABASE_URL, future=True)

Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Redis 连接 ---
redis_client = None
if config.REDIS_URL:
    try:
        # decode_responses=True 确保从 Redis 获取的是字符串而不是字节
        redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except redis.exceptions.ConnectionError as e:
        logger.critical("Failed to connect to Redis: %s", e)
        redis_client = None
else:
    logger.warning("REDIS_URL not set, refresh task status will not be available.")

INIT_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id BIGSERIAL PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding vector({config.VECTOR_DIM}) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops);

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
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

CREATE TABLE IF NOT EXISTS attachments (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

def db_init():
    with engine.begin() as conn:
        conn.exec_driver_sql("SELECT pg_advisory_lock(9876543210)")
        try:
            conn.exec_driver_sql(INIT_SQL)
            conn.exec_driver_sql("ANALYZE")
            logger.info("数据库表结构初始化/检查完成。")
        finally:
            conn.exec_driver_sql("SELECT pg_advisory_unlock(9876543210)")