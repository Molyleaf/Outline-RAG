# Outline LightRAG

一个基于 LightRAG 官方 WebUI 的 Outline 知识库问答服务。

当前实现已经收敛到 `FastAPI + LightRAG + OIDC + Outline Sync`：

- `/chat` 是统一入口，已登录后跳转到 `/chat/webui/`
- `/chat/webui/*` 提供 LightRAG 官方 WebUI
- `/chat/login` / `/chat/logout` / `/chat/oidc/callback` 保留 GitLab OIDC 登录流程
- `/chat/update/all` / `/chat/update/webhook` 负责 Outline 刷新
- 已移除 `/chat/api/ask`
- 已移除 `outline_sync_manifest`，Outline 同步状态直接写入 LightRAG 文档元数据

## 当前架构

- WebUI: LightRAG 官方 WebUI，运行时以 `/chat` 前缀提供
- RAG 引擎: LightRAG 单实例
- 文档同步: Outline API -> LightRAG
- 鉴权: GitLab OIDC 会话保护 `/chat/*`
- 存储:
  - KV / 向量 / 文档状态: LightRAG 官方 `PGKVStorage + PGVectorStorage + PGDocStatusStorage`
  - 图存储: LightRAG 官方 `Neo4JStorage`
  - 应用侧表: `users`

## 关键路径

- `/chat`
- `/chat/webui/`
- `/chat/login`
- `/chat/logout`
- `/chat/oidc/callback`
- `/chat/api/me`
- `/chat/api/refresh/status`
- `/chat/update/all`
- `/chat/update/webhook`
- `/chat/health`

## 运行前提

- PostgreSQL 已安装 `pgvector` 扩展
- Neo4j 可通过 Bolt 协议访问
- 已配置 Outline API Token 与 GitLab OIDC

## 配置

所有配置统一位于 [`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)。

常用环境变量：

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

# optional
REDIS_URL=redis://:password@host:6379/0
```

说明：

- `DATABASE_URL`、`NEO4J_*` 为必填。
- `working_dir` 与 `input_dir` 仍然保留给 LightRAG 运行时和文档接口使用。
- 官方 WebUI 会在启动时复制并补丁到 `data/lightrag_webui/`，不需要额外前端构建步骤。

## Docker

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

## 验证命令

```powershell
python -m compileall app
python -m py_compile app/main.py app/database.py app/rag.py app/blueprints/api.py app/blueprints/auth.py app/lightrag_runtime.py app/siliconflow_services.py app/openai_services.py
```

如环境可用，建议再做一次路由冒烟：

- `/chat`
- `/chat/webui/`
- `/chat/login`
- `/chat/api/me`
