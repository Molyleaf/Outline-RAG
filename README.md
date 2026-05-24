# Outline-RAG (v9.0.2)

[![Docker Pulls](https://img.shields.io/docker/pulls/molyleaf/outline-rag?style=flat-square)](https://hub.docker.com/r/molyleaf/outline-rag)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.123+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-v1%20classic-green?style=flat-square)](https://github.com/langchain-ai/langchain)
[![Postgres](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-blue?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org)

**Bringing the power of Large Language Models (LLMs) to your [Outline](https://github.com/outline/outline) knowledge base for intelligent, contextual, and immersive Q&A.**

Outline-RAG is a state-of-the-art Retrieval-Augmented Generation (RAG) system tailored specifically for the open-source Outline Wiki. It converts all documents stored in Outline into an intelligent conversational experience, utilizing modern asynchronous pipelines, high-performance database caching, automated intent routing, and premium visual interfaces.

This branch (`legacy-langchain-9.0.2`) represents a highly optimized, fully asynchronous production release featuring the FastAPI migration, Redis-backed task queueing, robust concurrent embedding caches, and dual-engine intent classification.

---

## 🚀 Key Features & Architectural Enhancements

### 1. High-Performance FastAPI Async Engine
* **Fully Asynchronous**: Replaced the legacy synchronous Flask endpoints with a modern **FastAPI** web core. Implements native async request handling throughout views, database connections, and OIDC middleware.
* **Efficient Database Operations**: Powered by `sqlalchemy.ext.asyncio` and `psycopg3` for high-throughput, non-blocking PostgreSQL and PGVector connections.

### 2. LangChain v1+ & `langchain_classic` Integration
* **Stability & Compatibility**: Upgraded to standard LangChain v1+ packages (`langchain-core`, `langchain-community`, `langchain-postgres`) while utilizing `langchain_classic` as a seamless compatibility layer to run legacy structural modules (such as `EncoderBackedStore`, `ContextualCompressionRetriever`, `DocumentCompressorPipeline`, `CacheBackedEmbeddings`).
* **Clean Dependency Model**: Standardized dependencies in `requirements.txt` to guarantee smooth, conflict-free production builds using a modern Python 3.13-slim runtime.

### 3. High-Concurrency Embedding & Chat Caching
* **Idempotent SQL Caching**: Features a custom `IdempotentSQLStore` subclassing SQLStore. Overrides `amset` to perform database cache updates via `INSERT ... ON CONFLICT DO NOTHING`. This resolves critical `UniqueViolation` race conditions when multiple concurrent worker processes compute and cache identical embeddings simultaneously.
* **Global LLM Cache**: Integrates `AsyncRedisCache` globally with an automated TTL (3600s), enabling near-instant, cost-free responses for repetitive outline-related inquiries.
* **Secure Cache Key Hashing**: Implements a dedicated SHA-256 encoder prefixed with model identifiers to safeguard cached embeddings against lookup collisions.

### 4. Advanced Dual-Engine RAG Pipeline
* **Asynchronous PGVector Store**: Utilizes `AsyncPGVectorStore` with explicit metadata extraction, indexing documents on custom fields (`source_id`, `title`, `url`, `outline_updated_at_str`) as well as the standard JSON `langchain_metadata` column.
* **Context-Aware Document Chunking**: Processes documents with `RecursiveCharacterTextSplitter` (1024 character chunk size, 100 overlap). Dynamically prepends document context (e.g. `文档标题: {parent_title}\n\n{chunk.page_content}`) to every sub-chunk, ensuring semantic embeddings contain full document perspective.
* **Custom Async Reranker**: Adapts SiliconFlow's Reranker API to `BaseDocumentCompressor` via `httpx.AsyncClient`. Incorporates exponential backoff retries (`RetryTransport`), limits network payload size by discarding redundant documents, and extracts rich diagnostic payloads on HTTP error scenarios.

### 5. Smart Prompt & Intent Routing
* **Core Worldview Classifier**: Integrates a robust game worldview (specifically tailored for *"余烬 (Embers)"* developed by *No Pigeon's Sky Studio*, highlighting features like北方企业联合体, 屏障粒子, etc.).
* **Four-Stream Intent Classification**: A JSON-structured classifier evaluates user queries and routes them into specific pipelines:
  * **Query (Encyclopedia/QA)**: Leverages documents from the knowledge base, enforcing rigorous citation rules (`[来源 n]` strictly separated, e.g., `[来源 1][来源 2]`, written naturally without artificial headers).
  * **Creative**: Inspires content creation (e.g., ship design, naming, lore drafting) while adhering strictly to structural guidelines.
  * **Roleplay**: Promotes immersive NPC interactions using the retrieved document context as "memories" without showing raw citation markers.
  * **General**: Bypasses the knowledge base completely to handle standard off-topic conversations (e.g., coding, translation, basic chat).

### 6. Queue-Based Sync & Webhook Debouncing
* **Redis Task Worker**: Offloads heavy syncing operations into a background task pipeline. Outline document updates trigger lightweight queue entries (`task_queue`), which are processed in batches by an asynchronous background consumer (`task_worker`).
* **Intelligent Webhook Watcher**: Employs a debouncer/watcher via Redis (`webhook:refresh_timer_due`). Instead of thrashing the database on massive document edits, it consolidates updates and triggers a single, graceful global refresh once editing activity subsides.

### 7. Secure OIDC & User Management
* **Secure GitLab OAuth Integration**: Built-in OIDC callback validating RS256 JWT ID tokens via cached discovery documents and JSON Web Key Sets (JWKS).
* **Automatic Metadata Synchronization**: Safely inserts or updates user identities in Postgres (`ON CONFLICT DO NOTHING / UPDATE`) upon each login.
* **Strict Session Sanitation**: Clears session data globally upon logout and completely removes session cookies via HTTP response headers to guarantee airtight client-side security.

### 8. Premium Visual Interface & Styling
* **Fluid Stream Animation**: Features a beautiful modern input box bordered with a dynamic horizontal glowing stream animation. Transitions flowing speed and colors during focused or editing states.
* **Native System Theme Adaptation**: Complete CSS Dark Mode integration adapted seamlessly to browser and operating system settings.
* **Optimized Mobile UX**: Responsive sidebars including elegant overlay drawers and smooth transition masks for mobile viewports.

---

## 📐 System Architecture

The following diagram illustrates the high-level architecture and asynchronous data flow between the Outline instance, the FastAPI application, Redis queue, and PostgreSQL:

```mermaid
graph TD
    %% Clients & Entry
    User[User Browser] <-->|HTTP / WS / SSE| Nginx[Nginx Reverse Proxy]
    Nginx <-->|Proxy Pass| Web[FastAPI Web App: main:app]
    
    %% Webhook & Outline Sync
    Outline[Outline Wiki] --->|Webhook Events| Web
    Web --->|Query Metadata / Content| Outline
    
    %% Session & Queue (Redis)
    Web <-->|Session Store & Cache| Redis[(Redis Caching & Queue)]
    Redis -.->|brpop task_queue| Worker[Background Worker: task_worker]
    Worker --->|Process Batches| RAG[RAG Pipeline: rag.py]
    
    %% Database Interaction
    Web <-->|User & Conv Tables| Postgres[(PostgreSQL + pgvector)]
    RAG <-->|Idempotent Caching & PGVectorStore| Postgres
    
    %% AI APIs
    RAG <-->|Embedding / Chat / Rerank| SiliconFlow[SiliconFlow LLM API]
```

---

## 📁 Directory Structure

```
outline-rag-v2/
├── app/
│   ├── blueprints/           # FastAPI APIRouter Blueprints
│   │   ├── api.py            # Primary Chat, RAG, Webhooks, & Upload APIs
│   │   ├── auth.py           # OIDC / GitLab Login & Logout Flows
│   │   └── views.py          # HTML Template Views (Jinja2)
│   ├── app.py                # Legacy App Launcher
│   ├── config.py             # Centralized Configuration & System Prompts
│   ├── database.py           # Async Database initialization (psycopg3) & DDL
│   ├── entrypoint.sh         # Production container launcher (uvicorn)
│   ├── llm_services.py       # Caching, Embeddings, Reranker, & LLM instances
│   ├── main.py               # Main FastAPI entrypoint, lifespan events & background tasks
│   └── rag.py                # Core RAG pipeline, splitting, syncing & deleting
├── data/
│   ├── archive/              # Optional documents archive
│   └── attachments/          # User-uploaded attachments
├── static/                   # Front-end templates, styles & scripts
├── Dockerfile                # Multi-stage optimized Docker build
├── requirements.txt          # Global build-time dependencies
└── requirements-runtime.txt  # Lightweight run-time dependencies
```

---

## ⚙️ Environment Variables Configuration

Outline-RAG is configured primarily using environment variables. These variables are loaded and parsed centrally inside `app/config.py`.

### Core Configurations
| Variable | Description | Default | Required |
| :--- | :--- | :--- | :---: |
| `APP_NAME` | The title displayed across the chat UI. | `Pigeon Chat` | ❌ |
| `PORT` | Local port for FastAPI to listen on inside the container. | `8080` | ❌ |
| `SECRET_KEY` | Hex secret for session cookie encryption. | *(Auto-generated if blank)* | ❌ |
| `DATABASE_URL` | SQLAlchemy async connection URL (`postgresql+psycopg2://...` or `postgresql+psycopg://...`). | - | **Yes** |
| `REDIS_URL` | Redis server connection URI (`redis://...`). | - | **Yes** |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARN`, `ERROR`). | `WARN` | ❌ |

### Outline Integration
| Variable | Description | Default | Required |
| :--- | :--- | :--- | :---: |
| `OUTLINE_API_URL` | Base API URL of your Outline instance (no trailing slash). | - | **Yes** |
| `OUTLINE_API_TOKEN` | An API Token generated inside your Outline instance. | - | **Yes** |
| `OUTLINE_WEBHOOK_SECRET` | Secret key used to verify incoming Webhook events from Outline. | `123` | ❌ |
| `OUTLINE_WEBHOOK_SIGN` | Whether to strictly verify signature headers of Outline webhooks. | `True` | ❌ |

### AI Model Config (SiliconFlow)
| Variable | Description | Default | Required |
| :--- | :--- | :--- | :---: |
| `SILICONFLOW_API_KEY` | API authentication key for SiliconFlow. | - | **Yes** |
| `SILICONFLOW_BASE_URL` | Base API URL for SiliconFlow OpenAI-compatible gateway. | `https://api.siliconflow.cn/v1` | ❌ |
| `EMBEDDING_MODEL` | Embedding model used by RAG (`SiliconFlowEmbeddings`). | `BAAI/bge-m3` | ❌ |
| `RERANKER_MODEL` | Document Reranking model. | `BAAI/bge-reranker-v2-m3` | ❌ |
| `BASE_CHAT_MODEL` | Model used for internal tasks like query rewriting and classification. | `Qwen/Qwen3-Next-80B-A3B-Instruct` | ❌ |
| `CHAT_MODELS_JSON` | A JSON-serialized array listing client-selectable LLM models. | *(See `config.py` defaults)* | ❌ |

### RAG Tuning Parameters
| Variable | Description | Default | Required |
| :--- | :--- | :--- | :---: |
| `TOP_K` | Maximum number of chunks returned by the base PGVector retriever. | `12` | ❌ |
| `K` | Number of final top chunks forwarded to the LLM context after Reranking. | `3` | ❌ |
| `REFRESH_BATCH_SIZE` | Batch size limit for scheduling background sync tasks. | `100` | ❌ |
| `VECTOR_DIM` | Dimensionality of your embedding model vector space. | `1024` | ❌ |

### OIDC Single-Sign-On
| Variable | Description | Default | Required |
| :--- | :--- | :--- | :---: |
| `GITLAB_URL` | Hostname of your GitLab SSO instance. | - | **Yes** (if OIDC is used) |
| `GITLAB_CLIENT_ID` | OAuth Application Client ID. | - | **Yes** (if OIDC is used) |
| `GITLAB_CLIENT_SECRET` | OAuth Application Client Secret. | `123` | **Yes** (if OIDC is used) |
| `OIDC_REDIRECT_URI` | Explicit callback endpoint (e.g., `https://domain.com/chat/oidc/callback`). | *(Auto-detected if blank)* | ❌ |
| `USE_JOSE_VERIFY` | Use the strict python-jose library to verify OIDC tokens. | `True` | ❌ |

---

## 📦 Deployment Guide

To deploy Outline-RAG alongside an Outline Wiki installation, we recommend using Docker Compose coupled with an Nginx reverse proxy.

### 1. Docker Compose Configuration

Create a `docker-compose.yml` file mapping out the services:

```yaml
version: '3.8'

services:
  # 1. Outline-RAG Application
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
      
      # Database and Caching URIs
      DATABASE_URL: postgresql+psycopg://outline-rag:your_secure_db_pass@outline-rag-db/outline-rag
      REDIS_URL: redis://:your_secure_redis_pass@outline-redis:6379/2
      
      # Outline Integration
      OUTLINE_API_URL: https://your-outline-domain.com
      OUTLINE_API_TOKEN: ot_your_outline_api_token_here
      OUTLINE_WEBHOOK_SECRET: your_webhook_secret_key
      OUTLINE_WEBHOOK_SIGN: "true"
      
      # SiliconFlow API Credentials
      SILICONFLOW_API_KEY: sk-your_siliconflow_api_key_here
      EMBEDDING_MODEL: BAAI/bge-m3
      RERANKER_MODEL: BAAI/bge-reranker-v2-m3
      
      # GitLab OIDC Single Sign-On
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
      - "127.0.0.1:8033:8080" # Exposed locally; managed by Nginx
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 180s
      timeout: 5s
      retries: 5
    networks:
      - outline-network

  # 2. PGVector Enabled Database
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

  # 3. Redis Instance (shared with Outline or isolated)
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

### 2. Nginx Reverse Proxy Configuration

Nginx routes normal users to Outline, and intercepts the `/chat` route to proxy to Outline-RAG. Ensure `proxy_buffering` is explicitly **disabled** for API routes to enable real-time Server-Sent Events (SSE) streaming.

```nginx
upstream outline-wiki {
    server 127.0.0.1:8030;
    keepalive 32;
}

upstream outline-rag {
    server 127.0.0.1:8033;
    keepalive 32;
}

proxy_cache_path /var/cache/nginx/outline_cache levels=1:2 keys_zone=outline_cache:10m max_size=1g inactive=60m use_temp_path=off;

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

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

    # Route 1: Route static chat resources with client-side caching
    location ^~ /chat/static {
        proxy_pass http://outline-rag;
        proxy_cache outline_cache;
        proxy_cache_valid 200 304 12h;
        proxy_cache_key $uri$is_args$args;
        add_header X-Cache-Status $upstream_cache_status;
    }

    # Route 2: Route chat APIs (SSE streaming must disable proxy buffering and caching)
    location ^~ /chat/api {
        proxy_pass http://outline-rag;
        proxy_buffering off;
        proxy_cache off;
    }

    # Route 3: Route all other /chat requests to Outline-RAG
    location ^~ /chat {
        proxy_pass http://outline-rag;
    }

    # Route 4: Route Outline Wiki static assets
    location ^~ /(static|fonts) {
        proxy_pass http://outline-wiki;
        proxy_cache outline_cache;
        proxy_cache_valid 200 304 12h;
        proxy_cache_key $uri$is_args$args;
        add_header X-Cache-Status $upstream_cache_status;
    }

    # Route 5: Catch-all routes direct to standard Outline Wiki
    location / {
        proxy_pass http://outline-wiki;
    }
}
```

---

## 🛠️ Local Development Setup

To run Outline-RAG locally without Docker for testing or development, follow these steps:

### Prerequisites
* **Python 3.13** installed on your workstation.
* A running **PostgreSQL** instance with the `pgvector` extension enabled.
* A running **Redis** server.

### Steps

1. **Clone the Repository and Branch**:
   ```bash
   git clone https://github.com/molyleaf/outline-rag.git
   cd outline-rag
   git checkout legacy-langchain-9.0.2
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Prepare Environment Settings**:
   Create a `.env` file in the root directory (or export them in your terminal) containing your credentials:
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

5. **Initialize Web Assets**:
   Compile static UI files using Flask Assets command:
   ```bash
   flask assets build
   ```

6. **Launch the FastAPI Server**:
   Start the application locally with hot-reloading:
   ```bash
   uvicorn main:app --reload --port 8080
   ```
   Open `http://localhost:8080/chat` in your web browser.

---

## 🤝 Contributing

Contributions of all types are welcome! If you encounter bugs, have suggestions, or would like to submit feature improvements, please open an Issue or submit a Pull Request.

When submitting pull requests, please ensure that you follow the project's asynchronous paradigms and compatibility models to keep codebases running efficiently under production scales.