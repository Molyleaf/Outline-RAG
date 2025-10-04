# app.py
import logging
import requests
import time
from datetime import datetime, timezone, timedelta
import json
import os
from flask import Flask, jsonify
import config
from database import db_init, engine
from blueprints.views import views_bp
from blueprints.auth import auth_bp
from blueprints.api import api_bp

# --- 日志配置 ---
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logger = logging.getLogger("app")

# --- 应用初始化与配置 ---
app = Flask(__name__, static_folder="static", static_url_path="/chat/static")

if not config.SECRET_KEY:
    logger.critical("SECRET_KEY 未设置，拒绝启动。")
    raise SystemExit(1)
if config.OUTLINE_WEBHOOK_SIGN and not config.OUTLINE_WEBHOOK_SECRET:
    logger.critical("OUTLINE_WEBHOOK_SIGN=true 但 OUTLINE_WEBHOOK_SECRET 为空，拒绝启动。")
    raise SystemExit(1)

app.secret_key = config.SECRET_KEY
app.config["JSON_AS_ASCII"] = False
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)
os.makedirs(config.ARCHIVE_DIR, exist_ok=True)


# --- 启动自检 ---
def _startup_self_check():
    services = [
        {"name": "Embedding", "url": config.EMBEDDING_API_URL, "token": config.EMBEDDING_API_TOKEN, "endpoint": "/v1/embeddings", "payload": {"model": config.EMBEDDING_MODEL, "input": ["ping"]}},
        {"name": "Reranker", "url": config.RERANKER_API_URL, "token": config.RERANKER_API_TOKEN, "endpoint": "/v1/rerank", "payload": {"model": config.RERANKER_MODEL, "query": "ping", "documents": ["a", "b"]}},
        {"name": "Chat", "url": config.CHAT_API_URL, "token": config.CHAT_API_TOKEN, "endpoint": "/v1/chat/completions", "payload": {"model": config.CHAT_MODEL, "messages": [{"role": "user", "content": "ping"}]}}
    ]
    errors = []
    for s in services:
        if not s["url"] or not s["token"]:
            errors.append(f"缺少 {s['name']} 服务的 API_URL 或 API_TOKEN")
            continue
        try:
            r = requests.post(f"{s['url']}{s['endpoint']}", json=s['payload'], headers={"Authorization": f"Bearer {s['token']}"}, timeout=10)
            if r.status_code >= 500: errors.append(f"{s['name']} 服务返回状态码 {r.status_code}")
        except requests.RequestException:
            errors.append(f"无法连通 {s['name']} 服务")

    if errors:
        for e in errors: logger.critical(f"[启动自检] {e}")
    else:
        logger.info("[启动自检] 所有外部服务连通性检查通过。")


# --- 蓝图注册 ---
app.register_blueprint(views_bp, url_prefix='/chat')
app.register_blueprint(auth_bp, url_prefix='/chat')
app.register_blueprint(api_bp, url_prefix='/chat')


# --- 健康检查与后台任务 ---
_last_archive_ts = 0

def archive_old_messages(days=90, batch_size=2000):
    from sqlalchemy import text
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    while True:
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT * FROM messages WHERE created_at < :cutoff ORDER BY id LIMIT :limit"),
                                {"cutoff": cutoff, "limit": batch_size}).mappings().all()
            if not rows: break
            ts = int(time.time())
            fname = os.path.join(config.ARCHIVE_DIR, f"messages_{ts}_{rows[0]['id']}_{rows[-1]['id']}.jsonl")
            with open(fname, "a", encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(dict(r), ensure_ascii=False, default=str) + "\n")
            conn.execute(text("DELETE FROM messages WHERE id = ANY(:ids)"), {"ids": [r["id"] for r in rows]})
    logger.info("旧消息归档任务完成。")

@app.route("/healthz")
def healthz():
    global _last_archive_ts
    now = time.time()
    if now - _last_archive_ts > 3600:
        try: archive_old_messages()
        except Exception as e: logger.error("归档任务失败: %s", e)
        _last_archive_ts = now
    return "ok"

# --- 应用启动 ---
if __name__ == "__main__":
    logger.info("This app is intended to be run with gunicorn, e.g.: gunicorn -w 2 -k gthread -b 0.0.0.0:%s app:app", config.PORT)
    app.run(host="0.0.0.0", port=config.PORT, use_reloader=False)
else:
    # 在 gunicorn 启动模式下执行初始化
    try:
        db_init()
        _startup_self_check()
    except Exception as e:
        logger.exception("应用启动时初始化失败: %s", e)
        raise SystemExit(1)