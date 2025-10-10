# app.py
# 应用主入口
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask
import config
import rag
from blueprints.api import api_bp
from blueprints.auth import auth_bp
from blueprints.views import views_bp
from database import db_init, engine, redis_client

# --- 日志配置 ---
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logger = logging.getLogger("app")

# --- 应用初始化与配置 ---
app = Flask(__name__, static_folder="static", static_url_path="/chat/static")

# 新增: 应用实例启动ID，用于会话验证
BOOT_ID = str(uuid.uuid4())
app.config['BOOT_ID'] = BOOT_ID
logger.info("当前应用实例 Boot ID: %s", BOOT_ID)

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
def archive_old_messages_task(days=90, batch_size=2000):
    """归档旧消息的任务，由后台工作线程执行。"""
    from sqlalchemy import text
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logger.info("开始归档 %s 天前的旧消息...", days)
    processed_count = 0
    while True:
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT * FROM messages WHERE created_at < :cutoff ORDER BY id LIMIT :limit"),
                                {"cutoff": cutoff, "limit": batch_size}).mappings().all()
            if not rows: break
            processed_count += len(rows)
            ts = int(time.time())
            fname = os.path.join(config.ARCHIVE_DIR, f"messages_{ts}_{rows[0]['id']}_{rows[-1]['id']}.jsonl")
            with open(fname, "a", encoding="utf-8") as f:
                for r in rows: f.write(json.dumps(dict(r), ensure_ascii=False, default=str) + "\n")
            conn.execute(text("DELETE FROM messages WHERE id = ANY(:ids)"), {"ids": [r["id"] for r in rows]})
    logger.info("旧消息归档任务完成，共处理 %d 条消息。", processed_count)

@app.route("/healthz")
def healthz():
    """健康检查，并周期性地将归档任务加入队列。"""
    if redis_client:
        # 每小时触发一次归档任务
        if redis_client.set("archive:lock", "1", ex=3600, nx=True):
            logger.info("将归档任务加入队列。")
            redis_client.lpush("task_queue", json.dumps({"task": "archive_old_messages"}))
    return "ok"

# --- 后台工作线程 ---
def task_worker():
    """后台任务处理器，从 Redis 队列中消费任务。"""
    logger.info("后台任务处理器已启动。")
    while True:
        try:
            # 使用阻塞式弹出，高效等待任务
            _queue, task_json = redis_client.brpop("task_queue", timeout=0)
            task_data = json.loads(task_json)
            task_name = task_data.get("task")
            logger.info("接收到新任务: %s", task_name)

            if task_name == "refresh_all":
                rag.refresh_all_task()
            elif task_name == "process_doc_batch":
                rag.process_doc_batch_task(task_data.get("doc_ids", []))
            elif task_name == "archive_old_messages":
                archive_old_messages_task()
            else:
                logger.warning("未知任务类型: %s", task_name)

        except redis_client.exceptions.ConnectionError as e:
            logger.error("Redis 连接错误，任务处理器暂停5秒: %s", e)
            time.sleep(5)
        except TypeError: # brpop 在超时时返回 None
            continue
        except Exception as e:
            logger.exception("任务处理器发生未知错误: %s", e)
            time.sleep(1)

def webhook_watcher():
    """后台 Webhook 计时器监视器。"""
    logger.info("Webhook 监视器已启动。")
    while True:
        try:
            due_time_str = redis_client.get("webhook:refresh_timer_due")
            if due_time_str:
                due_time = int(due_time_str)
                if time.time() > due_time:
                    logger.info("Webhook 计时器到期，触发优雅刷新。")
                    # 使用锁确保只有一个 worker 实例能触发
                    if redis_client.set("webhook:trigger_lock", "1", ex=60, nx=True):
                        redis_client.delete("webhook:refresh_timer_due")
                        # 触发一个优雅刷新任务
                        redis_client.lpush("task_queue", json.dumps({"task": "refresh_all"}))

        except redis_client.exceptions.ConnectionError as e:
            logger.error("Redis 连接错误，Webhook 监视器暂停5秒: %s", e)
            time.sleep(5)
        except Exception as e:
            logger.exception("Webhook 监视器发生未知错误: %s", e)

        time.sleep(5) # 每5秒检查一次

# --- 应用启动 ---
if __name__ == "__main__":
    logger.info("This app is intended to be run with gunicorn, e.g.: gunicorn -w 2 -k gthread -b 0.0.0.0:%s app:app", config.PORT)
    app.run(host="0.0.0.0", port=config.PORT, use_reloader=False)
else:
    # 在 gunicorn 启动模式下执行初始化
    try:
        db_init()
        _startup_self_check()
        # 启动后台任务处理器
        if redis_client:
            threading.Thread(target=task_worker, daemon=True).start()
            threading.Thread(target=webhook_watcher, daemon=True).start()
        else:
            logger.warning("Redis 未配置，后台任务和 Webhook 计时器将不会启动。")
    except Exception as e:
        logger.exception("应用启动时初始化失败: %s", e)
        raise SystemExit(1)
