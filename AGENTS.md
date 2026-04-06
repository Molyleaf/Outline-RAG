# AGENTS.md

本文件约束任何在本仓库内工作的 AI Agent。目标不是“做出更大的架构”，而是在现有 Python/FastAPI/RAG/原生前端结构上做最小、可验证、可维护的改动。

## 1. 仓库事实

- 后端主栈：`FastAPI + SQLAlchemy Async + Redis + LangChain`
- RAG 入口：[`app/blueprints/api.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/blueprints/api.py)
- 检索与索引：[`app/rag.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/rag.py)
- 数据库初始化：[`app/database.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/database.py)
- 配置加载器：[`app/config.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/config.py)
- 配置源：[`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)
- 前端源码：
  - 全局状态与工具函数：[`app/static/js/core.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/core.js)
  - 聊天流与消息渲染：[`app/static/js/app.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/app.js)
  - 顶栏、模型切换、交互控件：[`app/static/js/main.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/main.js)
- 打包产物：
  - [`app/static/script.min.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/script.min.js)
  - [`app/static/style.min.css`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/style.min.css)

## 2. 不可破坏的边界

### 2.1 配置边界

- 所有可配置内容都应落在 [`config/config.toml`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/config/config.toml)。
- [`app/config.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/config.py) 只负责启动时读取、解析、导出兼容常量。
- 不要在业务代码里直接 `os.getenv()` 读取新增配置，除非是在 `app/config.py` 内扩展加载逻辑。

### 2.2 模型服务边界

- `langchain_siliconflow` 只能在 [`app/siliconflow_services.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/siliconflow_services.py) 中引用。
- `langchain_openai` 只能在 [`app/openai_services.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/openai_services.py) 中引用。
- 查询重写、任务路由、Embedding、Reranker 始终走 SiliconFlow。
- 只有“最终回答阶段”允许切换到 OpenAI 兼容模型。

### 2.3 前端产物边界

- 不要手改 `script.min.js` 和 `style.min.css`。
- 改动前端时只编辑 `app/static/js/*.js` 与 `app/static/css/*.css` 源文件。
- 改完后执行静态资源构建，保证模板继续引用压缩产物。

## 3. 最小改动原则

- 不要顺手重命名无关变量、移动文件、拆分模块。
- 不要把“功能改动”和“大规模重构”混在一次提交里。
- 只有在逻辑被复用、或者边界明显时才新增 helper；否则直接内联。
- 保持现有风格：后端以直接函数和 SQL 为主，前端以原生 DOM 操作为主，不要引入新框架。

## 4. 后端规则

### 4.1 API 与数据库

- 用户敏感接口必须做会话所有权校验，参考 [`app/blueprints/api.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/blueprints/api.py) 现有模式。
- 新增表结构统一写入 [`app/database.py`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/database.py) 的初始化 SQL，不要额外引入迁移框架。
- 需要兼容旧库表时，优先补 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`。
- `AsyncSession` 上下文要短，避免先隐式开启事务、再嵌套 `session.begin()`。

### 4.2 错误处理

- 优先返回明确的 `HTTPException` 或 `JSONResponse`，不要既 `logger.error` 又把同一错误层层包装成看不懂的文本。
- 流式接口失败时，优先保证不会把会话写坏、不会越权写入别人的会话。
- 涉及用户私有配置时，不要把完整 API Key 返回给前端。

### 4.3 私有数据

- 用户私有模型配置必须按“仅当前用户可读写”处理。
- 这类配置如果已有加密存储路径，就沿用；不要回退到明文存储。

## 5. 前端规则

### 5.1 状态放置

- 全局状态放在 [`app/static/js/core.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/core.js)。
- 不要在 `app.js`、`main.js` 各自维护一套重复状态。

### 5.2 交互放置

- 聊天发送、流式解析、消息操作按钮放在 [`app/static/js/app.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/app.js)。
- 顶栏模型切换、模式切换、弹窗入口放在 [`app/static/js/main.js`](/D:/UserFiles/Documents/PyCharm/outline-rag-v2/app/static/js/main.js)。
- 通用样式优先补在已有 CSS 文件，不要无故新建大量样式文件。

### 5.3 UI 约束

- 保持现有 Shoelace + 原生 DOM 方案，不要引入 React/Vue。
- 优先复用已有弹窗、toast、mobile sheet 机制。
- 所有新增按钮都要考虑桌面端和移动端。

## 6. 验证命令

完成改动后，至少执行：

```powershell
python -m compileall app
flask --app app/app.py assets build
```

如果改动触及数据库或模型主链，优先再补一次：

```powershell
python -m py_compile app/main.py app/database.py app/rag.py app/blueprints/api.py app/siliconflow_services.py app/openai_services.py
```

## 7. 提交前自检

- 是否只改了与任务直接相关的文件
- 是否保持了 SiliconFlow 与 OpenAI 服务边界
- 是否没有手改压缩产物而忘记重新构建
- 是否没有把用户私有信息明文暴露给其他接口
- 是否同时检查了桌面端与移动端交互
- 是否避免了无必要的抽象和重构
