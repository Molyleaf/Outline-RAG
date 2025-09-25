import os
import json
import threading
from urllib.parse import urlparse
from wsgiref.simple_server import make_server
from app.server import app
from app.db import engine, run_alembic_upgrade

def on_startup():
    # Propagate embedding dim into DB session for alembic script
    emb_dim = int(os.getenv("EMBEDDING_DIM", "1024"))
    with engine.connect() as conn:
        conn.execute(sa.text("SELECT set_config('app.embedding_dim', :d, false)"), {"d": str(emb_dim)})
        conn.commit()
    run_alembic_upgrade()

if __name__ == "__main__":
    import sqlalchemy as sa
    on_startup()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    httpd = make_server(host, port, app)
    print(f"Server running at http://{host}:{port}/chat")
    httpd.serve_forever()
