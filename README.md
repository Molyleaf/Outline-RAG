# Outline-RAG

[GPL 3.0](https://opensource.org/license/gpl-3-0)

**为您的 [Outline](https://github.com/outline/outline) 知识库带来由大语言模型（LLM）驱动的智能问答能力。**

Outline-RAG 是一个基于 **检索增强生成 (Retrieval-Augmented Generation, RAG)** 技术的应用程序，专为开源知识库 Outline Wiki 设计。它能够将您在 Outline 中存储的所有文档和知识转化为一个可对话的智能知识库。用户可以通过自然语言提问，并获得基于知识库内容的精准、可靠的回答。

## ✨ 主要功能

* **智能问答**: 基于知识库内容，通过对话方式获取信息，而非手动搜索。
* **与 Outline 无缝集成**: 通过 Outline 的 API 和 Webhook 实时同步文档，确保问答知识的及时性。
* **支持附件问答**: 可上传 PDF、Markdown、TXT 等格式的本地文件，并针对其内容进行提问。
* **高度可配置**: 支持自定义 Embedding、Reranker 和 Chat 模型，可接入各类商业或开源的 LLM 服务。
* **企业级准备**: 集成 OIDC 单点登录，方便与现有身份认证体系（如 GitLab, Keycloak）对接。
* **数据私有化**: 所有知识库数据、向量索引和应用服务均可私有化部署，确保数据安全。

## 🚀 部署指南

我们推荐使用 Docker Compose 配合 Nginx 作为反向代理进行部署。这种方式能够将 Outline Wiki 和 Outline-RAG 两个服务整合在同一个域名下，并轻松实现 SSL 加密。

### 先决条件

* 一台安装了 Docker 和 Docker Compose 的服务器。
* 一个域名，并已正确解析到您的服务器 IP。
* 安装 Nginx 并准备好 SSL 证书。

### 1\. 准备目录和文件

首先，创建一个工作目录，并在其中创建以下文件和子目录：

```bash
mkdir outline-app && cd outline-app

# 为 Outline-RAG 的数据创建目录
mkdir -p ./attachments
mkdir -p ./archive
mkdir -p ./outline-rag-db/data
mkdir -p ./outline-rag-db/socket

# 为 Outline Wiki 的数据创建目录
mkdir -p ./pigeon-data
mkdir -p ./pigeon-wiki-redis/data
mkdir -p ./pigeon-wiki-redis/logs

# 创建 Docker Compose 文件
touch docker-compose.yml

# 创建 Nginx 配置文件 (可选，可在 Nginx 配置目录中创建)
touch nginx.conf
```

### 2\. 配置 Docker Compose

将以下内容复制到 `docker-compose.yml` 文件中。此模板整合了 Outline-RAG、Outline Wiki、一个带 pgvector 扩展的 PostgreSQL 数据库以及一个 Redis 服务。

**请仔细阅读并替换所有 `<...>` 占位符为您的实际配置。**

```yaml
# docker-compose.yml
version: '3.8'

services:
  # 1. Outline-RAG 应用服务
  outline-rag-web:
    image: molyleaf/outline-rag:latest # 建议使用具体的版本号
    container_name: outline-rag-web
    restart: always
    depends_on:
      outline-rag-db:
        condition: service_healthy
      pigeon-wiki:
        condition: service_started
      pigeon-wiki-redis:
        condition: service_started
    environment:
      # --- 基础配置 ---
      TZ: Asia/Shanghai
      PORT: 8080
      LOG_LEVEL: INFO
      SECRET_KEY: <请生成一个32位的随机字符串> # 例如: openssl rand -hex 16
      
      # --- 数据库与Redis ---
      DATABASE_URL: postgresql+psycopg2://outline-rag:<YOUR_RAG_DB_PASSWORD>@/outline-rag?host=/var/run/postgresql
      REDIS_URL: redis://:<YOUR_OUTLINE_REDIS_PASSWORD>@pigeon-wiki-redis:6379/2
      
      # --- Outline 集成配置 ---
      OUTLINE_API_URL: https://<your-domain.com>
      OUTLINE_API_TOKEN: <在Outline中生成的API Token>
      OUTLINE_WEBHOOK_SECRET: <在Outline中配置Webhook时使用的密钥>
      OUTLINE_WEBHOOK_SIGN: true
      
      # --- AI 模型配置 (以 SiliconFlow 为例) ---
      EMBEDDING_API_URL: https://api.siliconflow.cn
      EMBEDDING_API_TOKEN: <您的SiliconFlow API Token>
      EMBEDDING_MODEL: BAAI/bge-m3
      RERANKER_API_URL: https://api.siliconflow.cn
      RERANKER_API_TOKEN: <您的SiliconFlow API Token>
      RERANKER_MODEL: BAAI/bge-reranker-v2-m3
      CHAT_API_URL: https://api.siliconflow.cn
      CHAT_API_TOKEN: <您的SiliconFlow API Token>
      CHAT_MODEL: Qwen/Qwen2-7B-Instruct
      
      # --- OIDC 单点登录配置 (以 GitLab 为例) ---
      USE_JOSE_VERIFY: true
      GITLAB_URL: https://<your-gitlab-instance.com>
      GITLAB_CLIENT_ID: <您的GitLab OAuth App ID>
      GITLAB_CLIENT_SECRET: <您的GitLab OAuth App Secret>
      OIDC_REDIRECT_URI: https://<your-domain.com>/chat/oidc/callback
      
      # --- 文件上传配置 ---
      MAX_CONTENT_LENGTH: 10485760 # 10MB
      ALLOWED_FILE_EXTENSIONS: txt,md,pdf
      ATTACHMENTS_DIR: /app/data/attachments
      ARCHIVE_DIR: /app/data/archive

    volumes:
      - ./attachments:/app/data/attachments
      - ./archive:/app/data/archive
      - ./outline-rag-db/socket:/var/run/postgresql # 通过Socket连接数据库，效率更高
    ports:
      - "127.0.0.1:8033:8080" # 仅监听本地端口，由Nginx转发
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 180s
      timeout: 5s
      retries: 5
    networks:
      - outline-network

  # 2. Outline Wiki 服务
  pigeon-wiki:
    image: outlinewiki/outline:latest # 建议使用具体的版本号
    container_name: pigeon-wiki
    restart: always
    depends_on:
      - pigeon-wiki-redis
    environment:
      # --- 基础配置 ---
      SECRET_KEY: <请生成另一个随机字符串>
      UTILS_SECRET: <再生成一个随机字符串>
      URL: https://<your-domain.com>
      PORT: 3000
      FORCE_HTTPS: false # SSL由Nginx处理
      TZ: Asia/Shanghai
      
      # --- 数据库与Redis (Outline使用自己的数据库，这里假设您已有一个外部DB) ---
      # 注意：此模板不包含Outline的数据库，请连接到您现有的PostgreSQL数据库
      DATABASE_URL: postgres://<user>:<password>@<db-host>:<db-port>/<outline-db-name>
      REDIS_URL: redis://:<YOUR_OUTLINE_REDIS_PASSWORD>@pigeon-wiki-redis:6379/1
      
      # --- OIDC 单点登录 (需要与Outline-RAG的配置匹配) ---
      OIDC_CLIENT_ID: <您的GitLab OAuth App ID>
      OIDC_CLIENT_SECRET: <您的GitLab OAuth App Secret>
      OIDC_AUTH_URI: https://<your-gitlab-instance.com>/oauth/authorize
      OIDC_TOKEN_URI: https://<your-gitlab-instance.com>/oauth/token
      OIDC_USERINFO_URI: https://<your-gitlab-instance.com>/oauth/userinfo
      OIDC_USERNAME_CLAIM: username
      OIDC_DISPLAY_NAME: <登录按钮上显示的名称>
      
      # --- 文件存储 ---
      FILE_STORAGE: local
      FILE_STORAGE_LOCAL_ROOT_DIR: /var/lib/outline/data
      
    volumes:
      - ./pigeon-data:/var/lib/outline/data
    ports:
      - "127.0.0.1:8030:3000" # 仅监听本地端口
    networks:
      - outline-network

  # 3. Outline-RAG 的数据库 (使用带pgvector扩展的PostgreSQL)
  outline-rag-db:
    image: pgvector/pgvector:pg16
    container_name: outline-rag-db
    restart: always
    environment:
      POSTGRES_DB: outline-rag
      POSTGRES_USER: outline-rag
      POSTGRES_PASSWORD: <YOUR_RAG_DB_PASSWORD>
      TZ: Asia/Shanghai
    volumes:
      - ./outline-rag-db/data:/var/lib/postgresql/data
      - ./outline-rag-db/socket:/var/run/postgresql # 共享Socket给主应用
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 60s
      timeout: 5s
      retries: 10
    networks:
      - outline-network

  # 4. Redis 服务 (供Outline和Outline-RAG使用)
  pigeon-wiki-redis:
    image: redis:7
    container_name: pigeon-wiki-redis
    restart: always
    command: redis-server --requirepass <YOUR_OUTLINE_REDIS_PASSWORD>
    volumes:
      - ./pigeon-wiki-redis/data:/data
    networks:
      - outline-network

# 定义共享网络
networks:
  outline-network:
    driver: bridge
```

### 3\. 配置 Nginx 反向代理

将以下配置添加到您的 Nginx 站点配置文件中（例如 `/etc/nginx/sites-available/your-domain.com.conf`）。

此配置负责：

* 处理 SSL 证书。
* 将 `http` 请求重定向到 `https`。
* 根据 URL 路径，将流量正确转发到 Outline Wiki 或 Outline-RAG 服务。
* 为静态资源添加缓存。

<!-- end list -->

```nginx
# /etc/nginx/conf.d/outline.conf 或其他Nginx配置路径

# 定义上游服务，对应 docker-compose.yml 中暴露的端口
upstream outline-wiki {
    server 127.0.0.1:8030;
    keepalive 32;
}

upstream outline-rag {
    server 127.0.0.1:8033;
    keepalive 32;
}

# 代理缓存配置
proxy_cache_path /var/cache/nginx/outline_cache levels=1:2 keys_zone=outline_cache:10m max_size=1g inactive=60m use_temp_path=off;

server {
    listen 80;
    server_name <your-domain.com>;

    # 自动将HTTP重定向到HTTPS
    location / {
        return 301 https://$host$request_uri;
    }

    # Let's Encrypt 证书续期验证
    location ^~ /.well-known/acme-challenge/ {
        allow all;
        root /var/www/html;
    }
}

server {
    listen 443 ssl http2;
    server_name <your-domain.com>;

    # --- SSL 证书配置 ---
    ssl_certificate /path/to/your/fullchain.pem;
    ssl_certificate_key /path/to/your/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    
    # --- 日志文件 ---
    access_log /var/log/nginx/outline.access.log;
    error_log /var/log/nginx/outline.error.log;

    # --- 通用代理头设置 ---
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # --- 路由规则 ---

    # 规则 1: 转发 Outline-RAG 的静态资源，并缓存
    location ^~ /chat/static {
        proxy_pass http://outline-rag;
        proxy_cache outline_cache;
        proxy_cache_valid 200 304 12h;
        proxy_cache_key $uri$is_args$args;
        add_header X-Cache-Status $upstream_cache_status;
    }

    # 规则 2: 转发 Outline-RAG 的 API 请求 (流式接口，禁用缓存和缓冲)
    location ^~ /chat/api {
        proxy_pass http://outline-rag;
        proxy_buffering off; # 必须关闭，以支持流式响应
        proxy_cache off;
    }

    # 规则 3: 转发所有 /chat 路径的请求到 Outline-RAG
    location ^~ /chat {
        proxy_pass http://outline-rag;
    }

    # 规则 4: 转发 Outline Wiki 的静态资源，并缓存
    location ^~ /(static|fonts) {
        proxy_pass http://outline-wiki;
        proxy_cache outline_cache;
        proxy_cache_valid 200 304 12h;
        proxy_cache_key $uri$is_args$args;
        add_header X-Cache-Status $upstream_cache_status;
    }

    # 规则 5: 默认将所有其他请求转发到 Outline Wiki
    location / {
        proxy_pass http://outline-wiki;
    }
}
```

### 4\. 启动应用

1.  **启动服务**:
    在包含 `docker-compose.yml` 的 `outline-app` 目录下，运行：

    ```bash
    docker-compose up -d
    ```

2.  **重载 Nginx 配置**:
    测试 Nginx 配置是否有语法错误，然后重新加载。

    ```bash
    sudo nginx -t
    sudo systemctl reload nginx
    ```

3.  **访问应用**:
    现在，您可以通过浏览器访问 `https://<your-domain.com>` 来使用 Outline Wiki，并通过 `https://<your-domain.com>/chat` 访问 Outline-RAG 的问答界面。

## ⚙️ 配置项说明

请务必在 `docker-compose.yml` 的 `environment` 部分配置以下关键变量：

| 变量名 | 说明 | 示例 |
| :--- | :--- | :--- |
| `SECRET_KEY` | Flask 应用的会话密钥，请务必修改为一个随机长字符串。 | `openssl rand -hex 16` |
| `DATABASE_URL` | Outline-RAG 使用的数据库连接字符串。 | `postgresql+psycopg2://user:pass@...` |
| `OUTLINE_API_URL` | 您的 Outline 实例的访问 URL。 | `https://wiki.example.com` |
| `OUTLINE_API_TOKEN` | 在 Outline 的 "设置" -\> "API" 中生成的密钥。 | `ol_api_...` |
| `EMBEDDING_API_URL` | Embedding 模型的 API 地址。 | `https://api.siliconflow.cn` |
| `EMBEDDING_API_TOKEN` | Embedding 模型的 API 密钥。 | `sk-...` |
| `EMBEDDING_MODEL` | 使用的 Embedding 模型名称。 | `BAAI/bge-m3` |
| `CHAT_API_URL` | 对话大模型的 API 地址。 | `https://api.openai.com/v1` |
| `CHAT_API_TOKEN` | 对话大模型的 API 密钥。 | `sk-...` |
| `CHAT_MODEL` | 使用的对话大模型名称。 | `gpt-4-turbo` |
| `OIDC_*` / `GITLAB_*` | 用于配置 OIDC 单点登录的参数。 | |

## 🤝 贡献

欢迎任何形式的贡献！如果您有任何问题或建议，请随时提交 Issue 或 Pull Request。

## 📄 许可证

本项目基于 [GNU GPLv3 License](https://www.google.com/search?q=LICENSE) 开源。