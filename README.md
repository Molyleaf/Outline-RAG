# Outline LightRAG

一个基于 LightRAG 官方 WebUI 的 Outline 知识库问答服务。

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

所有配置统一位于 config/config.toml

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

参考 docker-compose.example.yml

- Compose 示例只使用预构建镜像，不包含 `build`。
- 使用前先替换 `outline-lightrag.image` 为你自己的镜像地址。
- 再按实际环境修改密码、域名和各类密钥。

## 本地开发

安装依赖：

```powershell
pip install -r requirements.txt
```

运行服务：

```powershell
uvicorn app.main:app --reload --port 8080
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
