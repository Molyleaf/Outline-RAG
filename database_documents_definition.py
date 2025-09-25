from __future__ import annotations
import os
import datetime as dt
from sqlalchemy import Table, Column, String, Text, DateTime, MetaData
from sqlalchemy.sql import text as sql_text

metadata = MetaData()

# embedding column managed via raw SQL due to pgvector
documents = Table(
    "documents",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("title", Text, nullable=False),
    Column("slug", Text),
    Column("collection_id", String(64)),
    Column("updated_at", DateTime(timezone=True)),
    Column("url", Text),
    Column("content", Text, nullable=False),
    # "embedding" exists but not declared here to avoid dialect issues; use raw SQL for read/write
)

def embedding_dim():
    return int(os.getenv("EMBEDDING_DIM", "1024"))
