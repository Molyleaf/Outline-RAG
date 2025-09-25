import os
import datetime as dt
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

def get_db_url():
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    db = os.getenv("PGDATABASE", "ragdb")
    user = os.getenv("PGUSER", "raguser")
    pwd = os.getenv("PGPASSWORD", "ragpassword")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"

engine = create_engine(get_db_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

def run_alembic_upgrade():
    # Inline alembic upgrade (programmatic)
    from alembic import command
    from alembic.config import Config
    import os
    cfg = Config(os.path.join(os.getcwd(), "alembic.ini"))
    command.upgrade(cfg, "head")

@contextmanager
def session_scope():
    from sqlalchemy.orm import Session
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

def ensure_vector_extension():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
