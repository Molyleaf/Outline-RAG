# app/app.py
import logging
import os
import sys

# (修改) 不再导入 redis 或 requests
from flask import Flask
from flask_assets import Environment, Bundle

# --- 1. 应用初始化 (Flask) ---
# (重要) 这个 'app' 变量现在只被 'flask assets build' 命令使用
app = Flask(__name__, static_folder="static", static_url_path="/chat/static")

# --- 2. Flask-Assets 配置 ---
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

# --- 3. (已移除) archive_old_messages_task ---


# --- (已移除) _startup_self_check ---
# --- (已移除) register_blueprints ---
# --- (已移除) healthz ---
# --- (已移除) task_worker ---
# --- (已移除) webhook_watcher ---
# --- (已移除) _init_runtime_app ---


# --- 4. 命令行执行逻辑 ---
if __name__ == "__main__":
    # (此逻辑仅用于本地开发 `python app/app.py`)
    print("This file (app.py) is now ONLY for 'flask assets build' or local dev assets.")
    print("Run 'uvicorn app.main:app --reload' for the main server.")

    # 临时的 logger
    logging.basicConfig(level=logging.INFO)

    app.config['DEBUG'] = True
    app.config['ASSETS_DEBUG'] = True
    app.config['ASSETS_AUTO_BUILD'] = True

    # (修改) 只初始化 assets
    assets.init_app(app)

    logging.getLogger("app").info(f"Starting local *assets* server...")
    # (修改) 仅用于测试 assets，不启动完整应用
    app.run(host="0.0.0.0", port=8081, use_reloader=True)

else:
    # Gunicorn 或 'flask' 命令导入时

    # (*** 关键修复 ***)
    # (不变) 检查我们是否在 'flask assets' 命令上下文中
    is_assets_command = False
    if 'flask' in sys.argv[0] and len(sys.argv) > 1 and sys.argv[1] == 'assets':
        is_assets_command = True

    # 仅当 *是* 'assets' 命令时
    if is_assets_command:
        # (修改) 'flask assets build' 命令也需要一个初始化的 assets 环境
        app.config['DEBUG'] = False # 确保 build 在 prod 模式下运行
        assets.init_app(app) # <--- 在此为 build 命令初始化
    else:
        # (修改) 如果被 Gunicorn (或其他) 导入，则什么也不做
        # Gunicorn 应该启动 main:app
        pass