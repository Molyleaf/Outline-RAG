from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "0001_init_pgvector_docs"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=True),
        sa.Column("collection_id", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", sa.types.UserDefinedType(), nullable=True),  # placeholder
    )
    # Convert embedding column to vector with dimension (runtime/env)
    # Using direct SQL because Alembic lacks pgvector bind by default
    op.execute("""
        DO $$
        DECLARE dim int := COALESCE(NULLIF(current_setting('app.embedding_dim', true), '')::int, 1024);
        BEGIN
            EXECUTE 'ALTER TABLE documents ALTER COLUMN embedding TYPE vector(' || dim || ')';
        END $$;
    """)

    op.create_index(
        "ix_documents_embedding_l2",
        "documents",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_l2_ops"}
    )

    op.create_index(
        "ix_documents_updated_at",
        "documents",
        ["updated_at"],
    )

def downgrade():
    op.drop_index("ix_documents_updated_at", table_name="documents")
    op.drop_index("ix_documents_embedding_l2", table_name="documents")
    op.drop_table("documents")
