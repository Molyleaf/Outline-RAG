# Outline-RAG

**为您的 [Outline](https://github.com/outline/outline) 知识库带来由大语言模型（LLM）驱动的智能问答能力。**

Outline-RAG 是一个基于 **检索增强生成 (Retrieval-Augmented Generation, RAG)** 技术的应用程序，专为开源知识库 Outline Wiki 设计。它能够将您在 Outline 中存储的所有文档和知识转化为一个可对话的智能知识库。用户可以通过自然语言提问，并获得基于知识库内容的精准、可靠的回答。

---

**Bringing the power of Large Language Models (LLMs) to your [Outline](https://github.com/outline/outline) knowledge base for intelligent Q\&A.**

Outline-RAG is an application based on **Retrieval-Augmented Generation (RAG)** technology, designed specifically for the open-source knowledge base, Outline Wiki. It transforms all the documents and knowledge stored in your Outline instance into a conversational, intelligent knowledge base. Users can ask questions in natural language and receive accurate, reliable answers grounded in the content of their knowledge base.

### Docker Hub: https://hub.docker.com/r/molyleaf/outline-rag

USE tag 9.0.2 ！！！

### GitHub: https://github.com/molyleaf/outline-rag

## 📦 Docker compose

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
      PORT: 8080
      LOG_LEVEL: INFO
      TOP_K: 12
      K: 6
      REFRESH_BATCH_SIZE: 50
      
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
      EMBEDDING_API_TOKEN: <您的 API Token>
      EMBEDDING_MODEL: BAAI/bge-m3
      RERANKER_API_URL: https://api.siliconflow.cn
      RERANKER_API_TOKEN: <您的 API Token>
      RERANKER_MODEL: BAAI/bge-reranker-v2-m3
      CHAT_API_URL: https://api.siliconflow.cn
      CHAT_API_TOKEN: <您的 API Token>
      CHAT_MODEL: Qwen/Qwen2-7B-Instruct

      SYSTEM_PROMPT: 你是一个企业知识库助理。你正在回答RAG应用的问题。
      
      # --- OIDC 单点登录配置 (以 GitLab 为例) ---
      USE_JOSE_VERIFY: true
      GITLAB_URL: https://<your-gitlab-instance.com>
      GITLAB_CLIENT_ID: <您的GitLab OAuth App ID>
      GITLAB_CLIENT_SECRET: <您的GitLab OAuth App Secret>
      OIDC_REDIRECT_URI: https://<your-domain.com>/chat/oidc/callback

      SECRET_KEY: <请生成一个32位的随机字符串> # 例如: openssl rand -hex 16
      # --- 文件上传配置 ---
      MAX_CONTENT_LENGTH: 10485760 # 10MB
      ALLOWED_FILE_EXTENSIONS: txt,md,pdf
      ATTACHMENTS_DIR: /app/data/attachments
      ARCHIVE_DIR: /app/data/archive
      TZ: Asia/Shanghai

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

## 🛠️ 配置 Nginx

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

## 🤝 Contributing

Contributions of any kind are welcome\! If you have any questions or suggestions, please feel free to open an Issue or Pull Request.
