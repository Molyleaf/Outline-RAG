# Outline LightRAG

一个基于 **LightRAG** 的 Outline 知识库问答服务。

当前版本已经从 LangChain 全量迁移到 `lightrag-hku[api]`，运行时界面直接使用 **LightRAG 官方 WebUI**，并适配到现有的 **`/chat`** 路径下。OIDC 登录流程保持不变。

## 当前架构

- Web UI: LightRAG 官方 WebUI，实际访问路径为 `/chat`
- RAG 引擎: LightRAG
- 文档同步: 从 Outline API 拉取文档并写入 LightRAG 文件存储
- 鉴权: GitLab OIDC，会话 Cookie 保护 `/chat`
- 存储:
  - LightRAG 主数据使用本地文件目录
  - 数据库仅用于可选的用户信息落库
  - 不再依赖 LangChain、pgvector、旧会话消息表

## 关键路径

- `/chat`: LightRAG WebUI
- `/chat/login`: OIDC 登录入口
- `/chat/logout`: OIDC 登出
- `/chat/oidc/callback`: OIDC 回调
- `/chat/update/all`: 手动触发 Outline 全量同步
- `/chat/api/refresh/status`: 查看同步状态
- `/chat/update/webhook`: Outline Webhook 入口
- `/chat/api/ask`: 旧流式聊天接口兼容层
- `/healthz`: 容器健康检查

## 配置

所有配置都放在 [`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)。
该文件已经补齐中文注释，直接按注释逐项填写即可。

最常用的环境变量：

```env
SECRET_KEY=replace-me

OUTLINE_API_URL=https://outline.example.com
OUTLINE_DISPLAY_URL=https://outline.example.com
OUTLINE_API_TOKEN=replace-me
OUTLINE_WEBHOOK_SECRET=replace-me

GITLAB_URL=https://gitlab.example.com
GITLAB_CLIENT_ID=replace-me
GITLAB_CLIENT_SECRET=replace-me
OIDC_REDIRECT_URI=https://your-domain.example.com/chat/oidc/callback

SILICONFLOW_API_KEY=replace-me

# 可选
DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname
REDIS_URL=redis://:password@host:6379/0
```

说明：

- `DATABASE_URL` 现在是可选项。未配置时，OIDC 用户信息仅保存在 Session Cookie 中。
- LightRAG 默认使用仓库内 `./data/lightrag` 与 `./data/lightrag_inputs` 作为工作目录。
- 由于当前使用本地文件存储，默认建议 `UVICORN_WORKERS=1`。
- 如果你需要调模型或检索参数，优先直接修改 `config/config.toml`，不要把新配置散落到业务代码里。

## Docker 示例

```yaml
services:
  outline-lightrag:
    build: .
    restart: always
    environment:
      PORT: 8080
      SECRET_KEY: ${SECRET_KEY}
      OUTLINE_API_URL: https://outline.example.com
      OUTLINE_DISPLAY_URL: https://outline.example.com
      OUTLINE_API_TOKEN: ${OUTLINE_API_TOKEN}
      OUTLINE_WEBHOOK_SECRET: ${OUTLINE_WEBHOOK_SECRET}
      GITLAB_URL: https://gitlab.example.com
      GITLAB_CLIENT_ID: ${GITLAB_CLIENT_ID}
      GITLAB_CLIENT_SECRET: ${GITLAB_CLIENT_SECRET}
      OIDC_REDIRECT_URI: https://your-domain.example.com/chat/oidc/callback
      SILICONFLOW_API_KEY: ${SILICONFLOW_API_KEY}
      UVICORN_WORKERS: 1
      DATABASE_URL: ${DATABASE_URL:-}
      REDIS_URL: ${REDIS_URL:-}
    volumes:
      - ./data/lightrag:/app/data/lightrag
      - ./data/lightrag_inputs:/app/data/lightrag_inputs
    ports:
      - "127.0.0.1:8033:8080"
```

## 反向代理

Nginx 至少需要把 `/chat` 全量转发给本服务：

```nginx
upstream outline_lightrag {
    server 127.0.0.1:8033;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    location ^~ /chat {
        proxy_pass http://outline_lightrag;
        proxy_buffering off;
    }
}
```

## Outline Webhook

建议在 Outline 侧把变更通知打到：

```text
POST https://your-domain.example.com/chat/update/webhook
```

服务端会做一个 60 秒的防抖，再触发一次全量同步。

## 本地开发

安装依赖：

```powershell
pip install -r requirements.txt
```

运行服务：

```powershell
cd app
uvicorn main:app --reload --port 8080
```

构建占位静态资源：

```powershell
flask --app app/app.py assets build
```

## 验证命令

```powershell
python -m compileall app
flask --app app/app.py assets build
python -m py_compile app/main.py app/database.py app/rag.py app/blueprints/api.py app/blueprints/auth.py app/lightrag_runtime.py app/siliconflow_services.py app/openai_services.py
```
