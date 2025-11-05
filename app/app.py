# app/app.py
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta

import redis
import requests
import sys
from flask import Flask
# (新) 导入 Flask-Assets
from flask_assets import Environment, Bundle

# --- 应用初始化 (轻量级) ---
# 这一部分是 `flask assets build` 唯一会导入和执行的部分
app = Flask(__name__, static_folder="static", static_url_path="/chat/static")

# --- Flask-Assets 配置 ---
# (这一部分是“轻量级”的，可以在全局安全定义)

# (*** 修复1 ***) 不在此时传入 app，推迟初始化
assets = Environment()
# assets = Environment(app) # <--- 旧代码

app.config['ASSETS_AUTO_BUILD'] = app.config.get('DEBUG', False)
app.config['ASSETS_DEBUG'] = app.config.get('DEBUG', False)

js_bundle = Bundle(
    'js/core.js',
    'js/app.js',
    'js/main.js',
    filters='jsmin',
    output='script.min.js'
)
css_bundle = Bundle(
    'css/main.css',
    'css/sidebar.css',
    'css/topbar.css',
    'css/chat.css',
    'css/modals.css',
    filters='cssmin',
    output='style.min.css'
)
assets.register('js_all', js_bundle)
assets.register('css_all', css_bundle)
# --- Assets 配置结束 ---

def _startup_self_check():
    """在运行时执行的启动自检"""
    # 在函数内部导入 config
    import config
    services = [
        {"name": "Embedding", "url": config.EMBEDDING_API_URL, "token": config.EMBEDDING_API_TOKEN, "endpoint": "/v1/embeddings", "payload": {"model": config.EMBEDDING_MODEL, "input": ["ping"]}},
        {"name": "Reranker", "url": config.RERANKER_API_URL, "token": config.RERANKER_API_TOKEN, "endpoint": "/v1/rerank", "payload": {"model": config.RERANKER_MODEL, "query": "ping", "documents": ["a", "b"]}},
        {"name": "Chat", "url": config.CHAT_API_URL, "token": config.CHAT_API_TOKEN, "endpoint": "/v1/chat/completions", "payload": {"model": config.CHAT_MODEL, "messages": [{"role": "user", "content": "ping"}]}}
    ]
    errors = []
    logger = logging.getLogger("app") # 获取在 _init_runtime_app 中配置的 logger
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


def register_blueprints(app_instance):
    """在运行时注册蓝图的辅助函数"""
    from blueprints.api import api_bp
    from blueprints.auth import auth_bp
    from blueprints.views import views_bp

    app_instance.register_blueprint(views_bp, url_prefix='/chat')
    app_instance.register_blueprint(auth_bp, url_prefix='/chat')
    app_instance.register_blueprint(api_bp, url_prefix='/chat')


def archive_old_messages_task(days=90, batch_size=2000):
    """归档旧消息的任务，由后台工作线程执行。"""
    import config
    from database import engine
    from sqlalchemy import text
    logger = logging.getLogger("app")

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
    from database import redis_client
    logger = logging.getLogger("app")

    if redis_client:
        if redis_client.set("archive:lock", "1", ex=3600, nx=True):
            logger.info("将归档任务加入队列。")
            redis_client.lpush("task_queue", json.dumps({"task": "archive_old_messages"}))
    return "ok"


def task_worker():
    """后台任务处理器，从 Redis 队列中消费任务。"""
    import rag
    from database import redis_client
    logger = logging.getLogger("app")

    logger.info("后台任务处理器已启动。")
    while True:
        try:
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

        except redis.exceptions.ConnectionError as e:
            logger.error("Redis 连接错误，任务处理器暂停5秒: %s", e)
            time.sleep(5)
        except TypeError:
            continue
        except Exception as e:
            logger.exception("任务处理器发生未知错误: %s", e)
            time.sleep(1)

def webhook_watcher():
    """后台 Webhook 计时器监视器。"""
    from database import redis_client
    logger = logging.getLogger("app")

    logger.info("Webhook 监视器已启动。")
    while True:
        try:
            due_time_str = redis_client.get("webhook:refresh_timer_due")
            if due_time_str:
                due_time = int(due_time_str)
                if time.time() > due_time:
                    logger.info("Webhook 计时器到期，触发优雅刷新。")
                    if redis_client.set("webhook:trigger_lock", "1", ex=60, nx=True):
                        redis_client.delete("webhook:refresh_timer_due")
                        redis_client.lpush("task_queue", json.dumps({"task": "refresh_all"}))

        except redis.exceptions.ConnectionError as e:
            logger.error("Redis 连接错误，Webhook 监视器暂停5秒: %s", e)
            time.sleep(5)
        except Exception as e:
            logger.exception("Webhook 监视器发生未知错误: %s", e)

        time.sleep(5)

# --- 应用启动 (运行时) ---
def _init_runtime_app(app_instance):
    """辅助函数：在运行时加载配置、初始化数据库和后台任务"""

    # 1. 在运行时导入 config
    import config

    # 2. 在运行时配置日志
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s"
    )
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logger = logging.getLogger("app") # Get logger *after* config

    # 3. 在运行时执行配置检查
    if not config.SECRET_KEY:
        logger.critical("SECRET_KEY 未设置，拒绝启动。")
        raise SystemExit(1)
    if config.OUTLINE_WEBHOOK_SIGN and not config.OUTLINE_WEBHOOK_SECRET:
        logger.critical("OUTLINE_WEBHOOK_SIGN=true 但 OUTLINE_WEBHOOK_SECRET 为空，拒绝启动。")
        raise SystemExit(1)

    # 4. 在运行时设置 app 配置
    app_instance.secret_key = config.SECRET_KEY
    app_instance.config["JSON_AS_ASCII"] = False
    app_instance.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
    app_instance.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
    os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)
    os.makedirs(config.ARCHIVE_DIR, exist_ok=True)

    # (*** 修复1 ***)
    # 在所有 app.config 设置 *之后* 再初始化 assets
    assets.init_app(app_instance)

    # 5. 在运行时注册蓝图
    register_blueprints(app_instance)

    # 6. 在运行时初始化数据库和任务
    try:
        # (*** 修复2 ***)
        # 导入并应用 ProxyFix 中间件来解决 HTTPS 代理后的 mixed content
        from werkzeug.middleware.proxy_fix import ProxyFix
        # 信任来自上游代理 (x_for=1) 的标头
        app_instance.wsgi_app = ProxyFix(
            app_instance.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
        )

        from database import db_init, redis_client

        should_initialize = True
        if redis_client:
            if not redis_client.set("app:startup:lock", "1", ex=60, nx=True):
                should_initialize = False

        if should_initialize:
            db_init()
            _startup_self_check()
        else:
            logger.info(f"Worker (pid: {os.getpid()}) 等待主初始化完成...")
            time.sleep(5)

        if redis_client:
            threading.Thread(target=task_worker, daemon=True).start()
            threading.Thread(target=webhook_watcher, daemon=True).start()
        else:
            logger.warning("Redis 未配置，后台任务和 Webhook 计时器将不会启动。")

    except Exception as e:
        logger.exception("应用启动时初始化失败: %s", e)
        raise SystemExit(1)

if __name__ == "__main__":
    # 临时的 logger，因为配置尚未加载
    temp_logger = logging.getLogger("pre-init")
    temp_logger.setLevel(logging.INFO)
    temp_logger.info("This app is intended to be run with gunicorn...")

    app.config['DEBUG'] = True
    app.config['ASSETS_DEBUG'] = True
    app.config['ASSETS_AUTO_BUILD'] = True

    # 在本地运行时初始化所有配置和服务
    _init_runtime_app(app)

    # 使用在 _init_runtime_app 中配置的 logger
    logging.getLogger("app").info(f"Starting local server...")
    # (*** 已修改 ***) 从 config 导入 PORT，因为 config 此时已被加载
    import config
    app.run(host="0.0.0.0", port=config.PORT, use_reloader=True)
else:
    # Gunicorn 或 'flask' 命令导入时

    # (*** 关键修复 ***)
    # 检查我们是否在 'flask assets' 命令上下文中
    # 'flask' 命令会将 'flask' 作为 sys.argv[0] 的一部分
    # 并且子命令 (如 'assets') 会在 sys.argv[1]
    is_assets_command = False
    if 'flask' in sys.argv[0] and len(sys.argv) > 1 and sys.argv[1] == 'assets':
        is_assets_command = True

    # 仅当 *不是* 'assets' 命令时（即 Gunicorn 启动时）
    # 才执行完整的运行时初始化
    if not is_assets_command:
        _init_runtime_app(app)
    else:
        # 是 'flask assets build' 命令：
        # (*** 修复1 ***)
        # 'flask assets build' 命令也需要一个初始化的 assets 环境
        app.config['DEBUG'] = False # 确保 build 在 prod 模式下运行
        assets.init_app(app) # <--- 在此为 build 命令初始化