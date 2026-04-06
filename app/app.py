# app/app.py
import logging

from flask import Flask
from flask_assets import Environment, Bundle

# 该 Flask app 仅用于保留 `flask assets build` 工作流。
# 运行时界面由 LightRAG WebUI 直接提供，不再消费这些静态资源。
app = Flask(__name__, static_folder="static", static_url_path="/chat/static")

# --- 2. Flask-Assets 配置 ---
assets = Environment()

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
assets.init_app(app)
# --- Assets 配置结束 ---

# --- 4. 命令行执行逻辑 ---
if __name__ == "__main__":
    # (此逻辑仅用于本地开发 `python app/app.py`)
    print("This file (app.py) is now ONLY for 'flask assets build' or local dev assets.")
    print("Run 'uvicorn main:app --reload' for the main server.")

    # 临时的 logger
    logging.basicConfig(level=logging.INFO)

    app.config['DEBUG'] = True
    app.config['ASSETS_DEBUG'] = True
    app.config['ASSETS_AUTO_BUILD'] = True

    logging.getLogger("app").info(f"Starting local *assets* server...")
    # 仅用于测试 assets，不启动完整应用
    app.run(host="0.0.0.0", port=8081, use_reloader=True)

else:
    # 导入时仅保留一个最小可用的 Flask-Assets 环境。
    app.config['DEBUG'] = False
