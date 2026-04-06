# Outline LightRAG

一个基于 **LightRAG 官方 WebUI** 的 Outline 知识库问答服务。

当前版本已经从 LangChain 全量迁移到 `lightrag-hku[api]`，运行时聊天界面挂载在 **`/chat`**，并保留原有 **OIDC** 登录流程与 `/chat/api/ask` 兼容接口。

## 当前架构

- Web UI: LightRAG 官方 WebUI，访问路径为 `/chat`
- RAG 引擎: LightRAG
- 文档同步: 从 Outline API 拉取文档并写入 LightRAG
- 鉴权: GitLab OIDC，会话 Cookie 保护 `/chat`
- 存储:
  - KV / 向量 / 文档状态: LightRAG 官方 `PGKVStorage + PGVectorStorage + PGDocStatusStorage`
  - 图存储: LightRAG 官方 `Neo4JStorage`
  - 应用侧附加表: `users`、`outline_sync_manifest`
  - 数据库驱动: `asyncpg`

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

## 运行前提

- PostgreSQL 已安装 `pgvector` 扩展
- Neo4j 可通过 Bolt 协议访问
- 已准备好 Outline API Token 与 GitLab OIDC 配置

## 配置

所有配置都放在 `config/config.toml`，文件内已经带中文注释。

最常用的环境变量：

```env
SECRET_KEY=replace-me

DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
NEO4J_URI=bolt://neo4j.example.com:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=replace-me
NEO4J_DATABASE=neo4j

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
REDIS_URL=redis://:password@host:6379/0
```

说明：

- `DATABASE_URL` 现在是必填项，必须指向启用 `pgvector` 的 Postgres。
- `NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD` 也是必填项。
- `working_dir` 与 `input_dir` 仍然保留，但主要用于 LightRAG 运行时缓存、上传和中间产物，不再是主数据源。
- 如果需要调整 PGVector 索引类型，可直接修改 `config/config.toml` 里的 `postgres_vector_index_type`、`postgres_hnsw_m`、`postgres_hnsw_ef`。

## Docker 示例

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    restart: always
    environment:
      POSTGRES_DB: outline_rag
      POSTGRES_USER: outline
      POSTGRES_PASSWORD: replace-me
    volumes:
      - ./data/postgres:/var/lib/postgresql/data

  neo4j:
    image: neo4j:5
    restart: always
    environment:
      NEO4J_AUTH: neo4j/replace-me
    volumes:
      - ./data/neo4j:/data

  outline-lightrag:
    build: .
    restart: always
    depends_on:
      - postgres
      - neo4j
    environment:
      PORT: 8080
      SECRET_KEY: ${SECRET_KEY}
      DATABASE_URL: postgresql+asyncpg://outline:replace-me@postgres:5432/outline_rag
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USERNAME: neo4j
      NEO4J_PASSWORD: replace-me
      NEO4J_DATABASE: neo4j
      OUTLINE_API_URL: https://outline.example.com
      OUTLINE_DISPLAY_URL: https://outline.example.com
      OUTLINE_API_TOKEN: ${OUTLINE_API_TOKEN}
      OUTLINE_WEBHOOK_SECRET: ${OUTLINE_WEBHOOK_SECRET}
      GITLAB_URL: https://gitlab.example.com
      GITLAB_CLIENT_ID: ${GITLAB_CLIENT_ID}
      GITLAB_CLIENT_SECRET: ${GITLAB_CLIENT_SECRET}
      OIDC_REDIRECT_URI: https://your-domain.example.com/chat/oidc/callback
      SILICONFLOW_API_KEY: ${SILICONFLOW_API_KEY}
      REDIS_URL: ${REDIS_URL:-}
      UVICORN_WORKERS: 1
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
