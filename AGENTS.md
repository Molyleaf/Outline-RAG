# AGENTS.md

本文件约束任何在本仓库内工作的 AI Agent。目标是在现有 `Python/FastAPI/LightRAG` 结构上做最小、可验证、可维护的改动，而不是重新发明一套新的运行时。

## 1. 仓库事实

- 后端主栈：`FastAPI + LightRAG + OIDC + 可选 SQLAlchemy Async + 可选 Redis`
- 主应用入口：[`app/main.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/main.py)
- LightRAG 运行时适配：[`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py)
- `/chat` 兼容接口与 Outline 刷新入口：[`app/blueprints/api.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/blueprints/api.py)
- OIDC 登录流程：[`app/blueprints/auth.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/blueprints/auth.py)
- Outline 文档同步：[`app/rag.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/rag.py)
- 数据库初始化：[`app/database.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/database.py)
- 配置加载器：[`app/config.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/config.py)
- 配置源：[`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)
- 静态资源构建入口：[`app/app.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/app.py)
- 运行时 UI：LightRAG 官方 WebUI，挂载在 `/chat`
- 本地静态源码：
  - [`app/static/js/core.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/core.js)
  - [`app/static/js/app.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/app.js)
  - [`app/static/js/main.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/main.js)
  - 以上文件当前是占位 stub，仅用于保留静态资源构建链路
- 打包产物：
  - [`app/static/script.min.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/script.min.js)
  - [`app/static/style.min.css`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/style.min.css)

## 2. 不可破坏的边界

### 2.1 配置边界

- 所有可配置内容都应落在 [`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)。
- [`app/config.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/config.py) 只负责启动时读取、解析、导出兼容常量。
- 不要在业务代码里直接 `os.getenv()` 读取新增配置，除非是为了对接第三方库且必须在初始化前写入环境变量。

### 2.2 LightRAG 边界

- LightRAG 官方 app 的创建、`/chat` 子路径适配、WebUI 重写逻辑，统一放在 [`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py)。
- 不要在别的模块里重复创建第二个 LightRAG 实例。
- Outline 文档同步统一通过 [`app/rag.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/rag.py) 调用 LightRAG 核心对象。
- `/chat/api/ask` 是兼容层，不要把它重新做成独立的旧聊天系统。

### 2.3 模型服务边界

- [`app/siliconflow_services.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/siliconflow_services.py) 与 [`app/openai_services.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/openai_services.py) 现在只负责生成 OpenAI 兼容 provider 配置。
- 不要在业务代码里散落拼接 provider host / api key / model 的逻辑。
- 如果后续支持新的 OpenAI 兼容服务，优先沿用这一层做归一化。

### 2.4 前端产物边界

- 不要手改 `script.min.js` 和 `style.min.css`。
- 如需改动占位静态源码，只改 `app/static/js/*.js` 与 `app/static/css/*.css`。
- 改完后执行静态资源构建，保证仓库里的压缩产物同步更新。
- 运行时实际界面来自 LightRAG WebUI，不要再把旧原生前端逻辑恢复回来。

## 3. 最小改动原则

- 不要顺手重命名无关变量、移动文件、拆分模块。
- 不要把“功能改动”和“风格性大重排”混在一次改动里。
- 只有在逻辑被复用、或者边界明显时才新增 helper；否则直接内联。
- 优先维持当前结构：主应用壳、OIDC 路由、LightRAG 运行时适配、Outline 同步、兼容接口，各自职责清晰。

## 4. 后端规则

### 4.1 API 与数据库

- 用户敏感接口必须做会话校验。
- 数据库现在是可选依赖；新增表结构统一写入 [`app/database.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/database.py)。
- 不需要再兼容旧 LangChain 表结构，也不要把旧消息/会话表重新加回来。
- `AsyncSession` 上下文要短，避免长事务。

### 4.2 错误处理

- 优先返回明确的 `HTTPException` 或 `JSONResponse`。
- 同步 Outline 文档时，失败应更新刷新状态，而不是把任务卡死在运行中。
- 涉及会话与登录态时，不要让 `/chat` 子应用绕过 OIDC 保护。

### 4.3 私有数据

- API Key、Client Secret 等敏感配置只从服务端读取，不返回给前端。
- 不要把完整敏感信息写入日志。

## 5. 前端规则

### 5.1 当前状态

- 主界面已经是 LightRAG WebUI。
- 仓库内 `app/static/js/*` 与 `app/static/css/*` 仅用于保留构建链路与兼容产物。

### 5.2 可接受的改动

- 可以调整占位资源、构建逻辑、重定向页。
- 可以修改 [`app/lightrag_runtime.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/lightrag_runtime.py) 中对官方 WebUI 的 `/chat` 路径适配。
- 不要引入新的前端框架，也不要再维护一套平行聊天 UI。

## 6. 验证命令

完成改动后，至少执行：

```powershell
python -m compileall app
flask --app app/app.py assets build
```

如果改动触及主链，优先再补一次：

```powershell
python -m py_compile app/main.py app/database.py app/rag.py app/blueprints/api.py app/blueprints/auth.py app/lightrag_runtime.py app/siliconflow_services.py app/openai_services.py
```

如条件允许，建议再补一次 ASGI 路由冒烟，至少覆盖：

- `/chat`
- `/chat/`
- `/chat/login`
- `/chat/api/me`

## 7. 提交前自检

- 是否只改了与任务直接相关的文件
- 是否保持了 `/chat` 挂载和 OIDC 登录流程
- 是否没有手改压缩产物而忘记重新构建
- 是否没有把敏感配置暴露给前端或日志
- 是否避免了无必要的抽象和重构
