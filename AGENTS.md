# AGENTS.md

本文件约束任何在本仓库内工作的 AI Agent。目标是在现有 `Python/FastAPI/LightRAG` 结构上做最小、可验证、可维护的改动。

## 1. 仓库事实

- 后端主栈：`FastAPI + LightRAG + OIDC + asyncpg + 可选 Redis`
- 主应用入口：[`app/main.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/main.py)
- LightRAG 运行时适配：[`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py)
- 应用侧接口与 Outline 刷新入口：[`app/blueprints/api.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/blueprints/api.py)
- OIDC 登录流程：[`app/blueprints/auth.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/blueprints/auth.py)
- Outline 文档同步：[`app/rag.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/rag.py)
- 数据库初始化：[`app/database.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/database.py)
- 配置加载器：[`app/config.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/config.py)
- 配置源：[`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)
- 运行时 UI：LightRAG 官方 WebUI，经本地前缀补丁后运行在 `/chat/webui/*`
- 统一入口：`/chat`
- 默认存储后端：LightRAG 官方 `PGKVStorage + PGVectorStorage + PGDocStatusStorage + Neo4JStorage`
- 应用侧自建表：`users`

## 2. 不可破坏的边界

### 2.1 配置边界

- 所有可配置内容都应落在 [`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)。
- [`app/config.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/config.py) 只负责启动时读取、解析、导出兼容常量。
- 不要在业务代码里直接 `os.getenv()` 读取新增配置，除非是为了初始化第三方库必须写入环境变量。

### 2.2 LightRAG 边界

- LightRAG 实例只允许在 [`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py) 创建一次。
- 不要通过闭包变量名、反射或 monkey patch 提取 `rag` / `doc_manager`。
- 不要重写上游 HTML/CSS/JS 响应。
- `/chat/*` 路径适配、WebUI 本地补丁、官方 router 组装都集中在 [`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py)。
- `/chat/api/ask` 已下线，不要重新引入。

### 2.3 Outline 同步边界

- Outline 同步统一通过 [`app/rag.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/rag.py) 调用 LightRAG。
- 文档同步状态只允许写入 LightRAG 文档状态/元数据。
- 不要重新引入 `outline_sync_manifest` 或其他平行状态表。

### 2.4 前端边界

- 仓库中不再维护旧 Flask 占位前端，也不再存在静态占位构建链路。
- WebUI 运行时静态产物由 [`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py) 从已安装的 LightRAG 包复制并补丁到 `data/lightrag_webui/`。
- 不要手改 LightRAG 安装目录下的包文件。

## 3. 最小改动原则

- 不要顺手重命名无关变量、移动文件、拆分模块。
- 不要把“功能改动”和“风格性重排”混在同一次改动里。
- 只有在逻辑被复用、或者边界明显时才新增 helper。
- 优先保留当前结构：主应用壳、OIDC 路由、LightRAG 运行时适配、Outline 同步、应用侧接口。

## 4. 后端规则

### 4.1 API 与数据库

- 用户敏感接口必须做会话校验。
- `/chat/*` 是统一访问前缀。
- Postgres 与 Neo4j 是必选依赖。
- 应用侧新增表结构统一写入 [`app/database.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/database.py)。
- 不需要兼容旧 LangChain 表结构，也不要恢复旧消息/会话持久化表。
- `asyncpg` 连接和事务作用域要短。

### 4.2 错误处理

- 优先返回明确的 `HTTPException` 或 `JSONResponse`。
- Outline 同步失败时必须更新刷新状态，不能把任务卡死在 running。
- 不能让 LightRAG 子应用绕过 OIDC 保护。

### 4.3 私有数据

- API Key、Client Secret 等敏感配置只能由服务端读取。
- 不要把完整敏感信息写入日志或返回前端。

## 5. 非目标

- 不要重新引入 `/chat/api/ask`
- 不要重新引入旧 Flask 占位前端
- 不要重新引入 `outline_sync_manifest`
- 不要为兼容旧客户端继续接受无效聊天参数

## 6. 验证命令

完成改动后，至少执行：

```powershell
python -m compileall app
python -m py_compile app/main.py app/database.py app/rag.py app/blueprints/api.py app/blueprints/auth.py app/lightrag_runtime.py app/siliconflow_services.py app/openai_services.py
```

如条件允许，建议补一次 ASGI 路由冒烟，至少覆盖：

- `/chat`
- `/chat/webui/`
- `/chat/login`
- `/chat/api/me`

## 7. 提交前自检

- 是否只改了与任务直接相关的文件
- 是否保持了 `/chat` 前缀和 OIDC 登录流程
- 是否没有重新引入旧占位前端或 `/chat/api/ask`
- 是否没有重新引入 `outline_sync_manifest`
- 是否没有把敏感配置暴露给前端或日志
