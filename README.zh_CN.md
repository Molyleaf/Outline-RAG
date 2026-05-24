# Outline-RAG (v9.0.2)

[![Docker Pulls](https://img.shields.io/docker/pulls/molyleaf/outline-rag?style=flat-square)](https://hub.docker.com/r/molyleaf/outline-rag)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.123+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-v1%20classic-green?style=flat-square)](https://github.com/langchain-ai/langchain)
[![Postgres](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-blue?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org)

**为您的 [Outline](https://github.com/outline/outline) 知识库带来由大语言模型（LLM）驱动的智能、情境化且沉浸式的问答能力。**

Outline-RAG 是专为开源知识库 Outline Wiki 设计的检索增强生成 (Retrieval-Augmented Generation, RAG) 系统。它将 Outline 中存储的所有文档和知识转化为可交互的智能对话体验，具备全异步流水线、高性能数据库缓存、智能意图分流路由器以及高端流光交互界面。

当前分支 (`legacy-langchain-9.0.2`) 代表了经过全面优化的、全异步生产级发布版本。该版本全面迁移到了 **FastAPI** 架构，引入了 Redis 异步任务队列、高并发幂等嵌入缓存以及双引擎智能意图路由器。

---

## 🚀 核心功能与架构提升

### 1. 高性能 FastAPI 异步引擎
* **全异步设计**：彻底移除了原有的同步 Flask 架构，采用现代化的 **FastAPI** 异步核心，实现了视图函数、数据库连接和 OIDC 中间件的全面非阻塞处理。
* **高效数据库交互**：结合 `sqlalchemy.ext.asyncio` 和 `psycopg3` 驱动，为 PostgreSQL 和 PGVector 提供高吞吐量、极速的数据库读写能力。

### 2. LangChain v1+ 与 `langchain_classic` 升级适配
* **平滑兼容**：升级到了 LangChain v1+ 标准生态（`langchain-core`、`langchain-community`、`langchain-postgres`），同时巧妙地引入 `langchain_classic` 作为向后兼容层，用来承载并稳定运行旧版的结构化模块（例如 `EncoderBackedStore`、`ContextualCompressionRetriever`、`DocumentCompressorPipeline` 和 `CacheBackedEmbeddings`）。
* **纯净依赖链**：在 `requirements.txt` 中规范并精简了依赖项，确保在 Python 3.13-slim 容器运行时中完美构建。

### 3. 高并发嵌入与 LLM 缓存优化
* **幂等 SQL 缓存**：定制了 `IdempotentSQLStore` 子类继承自 SQLStore，重写 `amset` 方法为 `INSERT ... ON CONFLICT DO NOTHING`。有效解决了在多 Worker 进程并发运行、尝试同时为缓存写入相同 embedding key 时可能触发的 `UniqueViolation`（主键冲突）竞态条件。
* **全局 LLM 缓存**：引入 `AsyncRedisCache` 并配置全局 TTL（3600秒），让知识库中高频重复提问能够被瞬间响应，降低大模型 API 消耗。
* **安全哈希防碰撞**：通过 SHA-256 编码并附带模型名前缀生成唯一缓存 Key，确保不同模型、不同文本的嵌入数据不会发生查询碰撞。

### 4. 智能双引擎 RAG 管道
* **异步 PGVector 存储**：利用 `AsyncPGVectorStore` 进行多维度元数据提取，支持在自定义元数据列（`source_id`、`title`、`url`、`outline_updated_at_str`）及通用 JSON `langchain_metadata` 列中建立索引。
* **情境融合的分块器**：使用 `RecursiveCharacterTextSplitter` 进行文档切割（分块大小 1024 字符，重叠度 100）。在切分时，动态地为每一个子块头部注入父文档标题上下文（例如 `文档标题: {parent_title}\n\n{chunk.page_content}`），极大地增强了语义向量检索的召回准确度。
* **自定义异步重排器 (Reranker)**：基于 `httpx.AsyncClient` 实现了 SiliconFlow 重排接口对 `BaseDocumentCompressor` 的异步适配。配备指数退避重试（`RetryTransport`），剔除冗余文档以减小网络传输包体，并在 HTTP 状态异常时解码获取详细的错误详情。

### 5. 智能提示词路由 (分类器)
* **核心世界观植入**：内置了针对游戏 *"余烬 (Embers)"*（由 *No Pigeon's Sky 工作室* 开发）的深度背景世界观，包括北方企业联合体、联合币、屏障粒子等设定。
* **四分流智能路由器**：由大模型驱动的 JSON 结构分类器自动分析用户的“新问题”与“对话历史”，将请求路由到最匹配的下游管道：
  * **Query (游戏知识库百科问答)**：检索 Outline 知识库，强制执行规范的引用标记规则（多个来源分开书写，例如 `[来源 1][来源 2]`，用词自然直接，杜绝合并书写和多余废话）。
  * **Creative (创意助手)**：辅助设计任务、剧情、设定以及取名，并严格遵循游戏设定框架。
  * **Roleplay (沉浸式角色扮演)**：将召回的知识库文档作为 NPC 的“记忆”和“常识”，开启人设扮演，对话中隐藏全部引用标记以保障沉浸感。
  * **General (通用无知识库任务)**：针对日常聊天、编程提问、语言翻译等非知识库内容，直接调用底座大模型快速响应。

### 6. 基于队列的异步同步与 Webhook 防抖
* **Redis 异步任务消费**：将繁重的 Outline 增量同步工作卸载到后台。当 Outline 发生文档新增或修改时，仅向 Redis 发送一条轻量级任务消息（队列 `task_queue`），由后台常驻异步协程 `task_worker` 批量消费执行。
* **智能 Webhook 防抖监视器**：在 Redis 中配置防抖计时器 `webhook:refresh_timer_due`。在连续大量修改文档时自动延迟触发，避免频繁全量更新对数据库造成的计算轰炸。

### 7. 安全 OIDC 单点登录与用户同步
* **GitLab OAuth 安全集成**：内建 OIDC 认证回调逻辑，支持 RS256 JWT ID 令牌校验。Discovery 配置与 JWKS（JSON 密钥集）均由 Redis 缓存 12 小时以减少外部请求网络时延。
* **自动用户 upsert 机制**：用户登录后，自动同步并更新 Postgres 中的用户头像与昵称（`ON CONFLICT (id) DO UPDATE SET ...`）。
* **严格的会话清理**：在用户登出时，彻底清除服务端 Session 状态，并强制使用 HTTP 响应头向浏览器删除 Session Cookie。

### 8. 精美极简的流光交互界面
* **流光边框动画**：输入框外围配备了精致流畅的水平移动流光层。聚焦（Focus）或编辑（Edit）状态下，流光的流动速度和色彩会自动产生细腻变化。
* **系统级深色模式适配**：全局 CSS 样式深度兼容操作系统和浏览器的 Dark Mode 设定。
* **完美移动端适配**：包含移动端专用的抽屉式导航栏遮罩层与交互平滑过渡效果。

---

## 📐 系统架构图

以下展示了 Outline Wiki、FastAPI 应用服务、Redis 队列以及 PostgreSQL 数据库之间的异步数据流与组件交互：

```mermaid
graph TD
    %% Clients & Entry
    User[用户浏览器] <-->|HTTP / WS / SSE| Nginx[Nginx 反向代理]
    Nginx <-->|Proxy Pass| Web[FastAPI Web 应用: main:app]
    
    %% Webhook & Outline Sync
    Outline[Outline 知识库] --->|Webhook 触发事件| Web
    Web --->|拉取文档元数据/内容| Outline
    
    %% Session & Queue (Redis)
    Web <-->|会话存储 & LLM 缓存| Redis[(Redis 缓存与队列)]
    Redis -.->|brpop task_queue| Worker[后台异步进程: task_worker]
    Worker --->|批量执行同步| RAG[RAG 管道核心: rag.py]
    
    %% Database Interaction
    Web <-->|用户与对话表| Postgres[(PostgreSQL + pgvector)]
    RAG <-->|嵌入向量幂等写入 & 向量检索| Postgres
    
    %% AI APIs
    RAG <-->|Embeddings / Chat / Rerank| SiliconFlow[硅基流动 API 网关]
```

---

## 📁 目录结构

```
outline-rag-v2/
├── app/
│   ├── blueprints/           # FastAPI 蓝图路由 (APIRouter)
│   │   ├── api.py            # 对话核心 API、RAG 检索、文件上传与 Webhook 路由
│   │   ├── auth.py           # OIDC / GitLab 认证登录登出流程
│   │   └── views.py          # 静态 HTML 视图渲染 (Jinja2)
│   ├── app.py                # 旧版 Flask 启动脚本
│   ├── config.py             # 集中化环境变量加载与全局 System Prompt 预设
│   ├── database.py           # SQLAlchemy 异步连接池 (psycopg3) 与表结构 DDL 检查
│   ├── entrypoint.sh         # 生产容器环境 Uvicorn 启动脚本
│   ├── llm_services.py       # 大模型、嵌入、重排实例初始化及 IdempotentSQLStore 缓存
│   ├── main.py               # 应用主入口，运行 lifespan 生命周期事件与异步后台消费 Worker
│   └── rag.py                # 向量化核心管道：数据切割、增量写入、废弃删除
├── data/
│   ├── archive/              # 可选：导出的历史文档存档
│   └── attachments/          # 用户上传的附件目录
├── static/                   # 前端 Jinja2 模板、流光 CSS 样式表以及前端 JavaScript
├── Dockerfile                # 高度优化的多阶段生产镜像构建脚本
├── requirements.txt          # 构建期全量 Python 依赖包清单
└── requirements-runtime.txt  # 运行时精简 Python 依赖包清单
```

---

## ⚙️ 环境变量配置说明

项目通过环境变量进行全面配置。所有配置在 `app/config.py` 中集中解析并提供给核心逻辑。

### 基础运行配置
| 环境变量 | 配置描述 | 默认值 | 是否必填 |
| :--- | :--- | :--- | :---: |
| `APP_NAME` | 网页端 UI 的标题名称。 | `Pigeon Chat` | ❌ |
| `PORT` | FastAPI 在容器内监听的本地端口。 | `8080` | ❌ |
| `SECRET_KEY` | 用于 Session 加密的 32 位随机密钥字符串。 | *(未设置时将自动随机生成)* | ❌ |
| `DATABASE_URL` | SQLAlchemy 异步连接 URL (`postgresql+psycopg://...`)。 | - | **是** |
| `REDIS_URL` | Redis 服务连接地址 (`redis://...`)。 | - | **是** |
| `LOG_LEVEL` | 日志输出级别 (`DEBUG`, `INFO`, `WARN`, `ERROR`)。 | `WARN` | ❌ |

### Outline 集成配置
| 环境变量 | 配置描述 | 默认值 | 是否必填 |
| :--- | :--- | :--- | :---: |
| `OUTLINE_API_URL` | Outline Wiki 实例的 API 基础访问地址。 | - | **是** |
| `OUTLINE_API_TOKEN` | 在 Outline 后台生成的 API Token 密钥。 | - | **是** |
| `OUTLINE_WEBHOOK_SECRET` | 验证 Outline 发送的 Webhook 请求的密钥。 | `123` | ❌ |
| `OUTLINE_WEBHOOK_SIGN` | 是否启用对 Webhook 的签名校验。 | `True` | ❌ |

### AI 模型配置 (以 SiliconFlow 硅基流动为例)
| 环境变量 | 配置描述 | 默认值 | 是否必填 |
| :--- | :--- | :--- | :---: |
| `SILICONFLOW_API_KEY` | 硅基流动平台的 API 鉴权 Token。 | - | **是** |
| `SILICONFLOW_BASE_URL` | 硅基流动的 OpenAI 兼容网关地址。 | `https://api.siliconflow.cn/v1` | ❌ |
| `EMBEDDING_MODEL` | 文本向量化嵌入模型。 | `BAAI/bge-m3` | ❌ |
| `RERANKER_MODEL` | 文档重排模型。 | `BAAI/bge-reranker-v2-m3` | ❌ |
| `BASE_CHAT_MODEL` | 用于内部任务（如问题改写、分类器）的基座大模型。 | `Qwen/Qwen3-Next-80B-A3B-Instruct` | ❌ |
| `CHAT_MODELS_JSON` | 可供用户切换的对话模型 JSON 数组定义。 | *(详见 `config.py` 中的预设列表)* | ❌ |

### RAG 调优参数
| 环境变量 | 配置描述 | 默认值 | 是否必填 |
| :--- | :--- | :--- | :---: |
| `TOP_K` | 向量数据库基础检索召回的子块数量。 | `12` | ❌ |
| `K` | 重排（Rerank）后输入大模型上下文的最终子块数量。 | `3` | ❌ |
| `REFRESH_BATCH_SIZE` | 全量更新时单批次分发的任务块大小。 | `100` | ❌ |
| `VECTOR_DIM` | 向量嵌入模型的维度空间。 | `1024` | ❌ |

### OIDC 单点登录配置
| 环境变量 | 配置描述 | 默认值 | 是否必填 |
| :--- | :--- | :--- | :---: |
| `GITLAB_URL` | GitLab SSO 单点登录的网关地址。 | - | **是** (若需登录功能) |
| `GITLAB_CLIENT_ID` | GitLab OAuth 应用程序的 Client ID。 | - | **是** (若需登录功能) |
| `GITLAB_CLIENT_SECRET` | GitLab OAuth 应用程序的 Client Secret。 | `123` | **是** (若需登录功能) |
| `OIDC_REDIRECT_URI` | 登录成功后的回调地址 (例如: `https://domain.com/chat/oidc/callback`)。 | *(未设置时将自动推导)* | ❌ |
| `USE_JOSE_VERIFY` | 是否使用 python-jose 对 ID 令牌进行 RS256 签名和时效校验。 | `True` | ❌ |

---

## 📦 生产环境部署指南

为了将 Outline-RAG 稳定部署至您的生产环境，我们推荐使用 Docker Compose 容器编排，并配合 Nginx 进行反向代理。

### 1. 编写 Docker Compose 配置文件

在服务器上创建并配置 `docker-compose.yml` 文件：

```yaml
version: '3.8'

services:
  # 1. Outline-RAG Web 主应用服务
  outline-rag-web:
    image: molyleaf/outline-rag:9.0.2
    container_name: outline-rag-web
    restart: always
    depends_on:
      outline-rag-db:
        condition: service_healthy
      outline-redis:
        condition: service_started
    environment:
      PORT: 8080
      LOG_LEVEL: INFO
      TOP_K: 12
      K: 6
      REFRESH_BATCH_SIZE: 50
      
      # 数据库与 Redis 缓存连接
      DATABASE_URL: postgresql+psycopg://outline-rag:your_secure_db_pass@outline-rag-db/outline-rag
      REDIS_URL: redis://:your_secure_redis_pass@outline-redis:6379/2
      
      # Outline Wiki 参数配置
      OUTLINE_API_URL: https://your-outline-domain.com
      OUTLINE_API_TOKEN: ot_your_outline_api_token_here
      OUTLINE_WEBHOOK_SECRET: your_webhook_secret_key
      OUTLINE_WEBHOOK_SIGN: "true"
      
      # AI 模型服务鉴权
      SILICONFLOW_API_KEY: sk-your_siliconflow_api_key_here
      EMBEDDING_MODEL: BAAI/bge-m3
      RERANKER_MODEL: BAAI/bge-reranker-v2-m3
      
      # GitLab 单点登录配置
      GITLAB_URL: https://your-gitlab-domain.com
      GITLAB_CLIENT_ID: gitlab_client_id_here
      GITLAB_CLIENT_SECRET: gitlab_client_secret_here
      OIDC_REDIRECT_URI: https://your-outline-domain.com/chat/oidc/callback
      
      SECRET_KEY: your_32_character_hex_secret_here
      TZ: Asia/Shanghai

    volumes:
      - ./attachments:/app/data/attachments
      - ./archive:/app/data/archive
    ports:
      - "127.0.0.1:8033:8080" # 仅监听本地地址，由 Nginx 进行外网代理
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 180s
      timeout: 5s
      retries: 5
    networks:
      - outline-network

  # 2. pgvector 向量扩展数据库服务
  outline-rag-db:
    image: pgvector/pgvector:pg16
    container_name: outline-rag-db
    restart: always
    environment:
      POSTGRES_DB: outline-rag
      POSTGRES_USER: outline-rag
      POSTGRES_PASSWORD: your_secure_db_pass
      TZ: Asia/Shanghai
    volumes:
      - ./outline-rag-db/data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 60s
      timeout: 5s
      retries: 10
    networks:
      - outline-network

  # 3. Redis 高速缓存与任务队列服务
  outline-redis:
    image: redis:7-alpine
    container_name: outline-redis
    restart: always
    command: redis-server --requirepass your_secure_redis_pass
    volumes:
      - ./redis/data:/data
    networks:
      - outline-network

networks:
  outline-network:
    driver: bridge
```

### 2. 配置 Nginx 反向代理

Nginx 负责接收所有的请求，除特定的 `/chat` 路径路由到 Outline-RAG 之外，其余请求都直接路由给标准的 Outline Wiki 服务。请注意：对于 API 请求，**必须关闭 `proxy_buffering`** 以支持 Server-Sent Events (SSE) 流式打字机响应。

```nginx
upstream outline-wiki {
    server 127.0.0.1:8030;
    keepalive 32;
}

upstream outline-rag {
    server 127.0.0.1:8033;
    keepalive 32;
}

# 静态缓存区
proxy_cache_path /var/cache/nginx/outline_cache levels=1:2 keys_zone=outline_cache:10m max_size=1g inactive=60m use_temp_path=off;

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL 证书配置
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    
    access_log /var/log/nginx/outline.access.log;
    error_log /var/log/nginx/outline.error.log;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # 规则 1: 拦截 Outline-RAG 的静态资源请求并开启高效缓存
    location ^~ /chat/static {
        proxy_pass http://outline-rag;
        proxy_cache outline_cache;
        proxy_cache_valid 200 304 12h;
        proxy_cache_key $uri$is_args$args;
        add_header X-Cache-Status $upstream_cache_status;
    }

    # 规则 2: 拦截 Outline-RAG 的 API 流式请求 (必须关闭代理缓冲和缓存)
    location ^~ /chat/api {
        proxy_pass http://outline-rag;
        proxy_buffering off;
        proxy_cache off;
    }

    # 规则 3: 将所有 /chat 路径的普通请求转发给 Outline-RAG
    location ^~ /chat {
        proxy_pass http://outline-rag;
    }

    # 规则 4: 拦截 Outline Wiki 的静态页面资源
    location ^~ /(static|fonts) {
        proxy_pass http://outline-wiki;
        proxy_cache outline_cache;
        proxy_cache_valid 200 304 12h;
        proxy_cache_key $uri$is_args$args;
        add_header X-Cache-Status $upstream_cache_status;
    }

    # 规则 5: 默认其他全部请求导向正常的 Outline Wiki 服务
    location / {
        proxy_pass http://outline-wiki;
    }
}
```

---

## 🛠️ 本地开发与调试指南

如果您希望在开发机上直接运行或调试 Outline-RAG，请参考以下指南：

### 环境准备
* 运行环境已安装 **Python 3.13**。
* 已安装并在本地运行 **PostgreSQL** 并激活了 `pgvector` 扩展。
* 已启动并可连接的 **Redis** 服务。

### 操作步骤

1. **拉取代码并检出分支**：
   ```bash
   git clone https://github.com/molyleaf/outline-rag.git
   cd outline-rag
   git checkout legacy-langchain-9.0.2
   ```

2. **创建并激活虚拟环境**：
   ```bash
   python -m venv .venv
   # Windows 环境:
   .venv\Scripts\activate
   # Linux / macOS 环境:
   source .venv/bin/activate
   ```

3. **安装依赖包**：
   ```bash
   pip install -r requirements.txt
   ```

4. **配置本地环境变量**：
   在项目根目录下创建一个 `.env` 文件并填入您自己的连接密钥：
   ```env
   SECRET_KEY="your_32_character_hex_secret_here"
   DATABASE_URL="postgresql+psycopg://outline-rag:password@localhost:5432/outline-rag"
   REDIS_URL="redis://localhost:6379/0"
   OUTLINE_API_URL="https://your-outline.com"
   OUTLINE_API_TOKEN="ot_your_outline_token"
   SILICONFLOW_API_KEY="sk-your_siliconflow_key"
   GITLAB_URL="https://gitlab.com"
   GITLAB_CLIENT_ID="gitlab_oauth_id"
   GITLAB_CLIENT_SECRET="gitlab_oauth_secret"
   ```

5. **编译静态资源**：
   运行 Flask Assets 命令行指令完成前端文件的打包与编译：
   ```bash
   flask assets build
   ```

6. **启动 FastAPI 异步服务器**：
   利用 Uvicorn 运行主应用并开启动态热重载：
   ```bash
   uvicorn main:app --reload --port 8080
   ```
   随后即可在浏览器中打开 `http://localhost:8080/chat` 查看运行效果。

---

## 🤝 贡献规范

我们热忱欢迎任何形式的贡献！如果您在运行中发现了 Bug，或者有更优越的功能想法，请随时开启 Issue 或提交 Pull Request。

在提交合并代码之前，请确保您的逻辑完全适配当前版本的异步运行范式与接口依赖层级，维持高并发下的稳定性。
