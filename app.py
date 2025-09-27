import os
import hmac
import hashlib
import json
import time
import base64
import secrets
import urllib.parse
from datetime import datetime, timezone
import logging
import requests
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory, abort
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
import urllib.request
from flask import make_response
# 环境变量
PORT = int(os.getenv("PORT", "8080"))
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "1024"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# 基础日志配置
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger("app")

# 新增：可调优的检索/重排参数（env）
TOP_K = int(os.getenv("TOP_K", "12"))  # 向量检索召回数（search_similar）
K = int(os.getenv("K", "6"))           # reranker 选取 top_n

POSTGRES_DB = os.getenv("POSTGRES_DB", "outline_rag")
POSTGRES_USER = os.getenv("POSTGRES_USER", "outline")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "outlinepass")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

OUTLINE_API_URL = os.getenv("OUTLINE_API_URL", "").rstrip("/")
OUTLINE_API_TOKEN = os.getenv("OUTLINE_API_TOKEN", "")
OUTLINE_WEBHOOK_SECRET = os.getenv("OUTLINE_WEBHOOK_SECRET", "").strip()
OUTLINE_WEBHOOK_SIGN = os.getenv("OUTLINE_WEBHOOK_SIGN", "true").lower() == "true"

EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "").rstrip("/")
EMBEDDING_API_TOKEN = os.getenv("EMBEDDING_API_TOKEN", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

RERANKER_API_URL = os.getenv("RERANKER_API_URL", "").rstrip("/")
RERANKER_API_TOKEN = os.getenv("RERANKER_API_TOKEN", "")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "bge-reranker-m2")

CHAT_API_URL = os.getenv("CHAT_API_URL", "").rstrip("/")
CHAT_API_TOKEN = os.getenv("CHAT_API_TOKEN", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "your-chat-model")

SAFE_LOG_CHAT_INPUT = os.getenv("SAFE_LOG_CHAT_INPUT", "true").lower() == "true"
MAX_LOG_INPUT_CHARS = int(os.getenv("MAX_LOG_INPUT_CHARS", "4000"))

# 新增：JOSE/cryptography 验签开关（默认启用）
USE_JOSE_VERIFY = os.getenv("USE_JOSE_VERIFY", "true").lower() == "true"

GITLAB_CLIENT_ID = os.getenv("GITLAB_CLIENT_ID", "")
GITLAB_CLIENT_SECRET = os.getenv("GITLAB_CLIENT_SECRET", "")
GITLAB_URL = os.getenv("GITLAB_URL", "").rstrip("/")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")  # 新增：显式配置回调 URL

SECRET_KEY = os.getenv("SECRET_KEY", None)  # 改动：不再回退随机值，缺失时拒绝启动

# Flask
app = Flask(__name__, static_folder="static", static_url_path="/static")
# 在启动阶段校验关键配置（SECRET_KEY、Webhook签名）
if not SECRET_KEY:
    logger.critical("SECRET_KEY 未设置，拒绝启动。")
    raise SystemExit(1)
if OUTLINE_WEBHOOK_SIGN and not OUTLINE_WEBHOOK_SECRET:
    logger.critical("OUTLINE_WEBHOOK_SIGN=true 但 OUTLINE_WEBHOOK_SECRET 为空，拒绝启动。")
    raise SystemExit(1)
app.secret_key = SECRET_KEY
# 确保 Flask JSON 使用 UTF-8 且不转义中文
app.config["JSON_AS_ASCII"] = False
DATABASE_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
engine: Engine = create_engine(DATABASE_URL, poolclass=NullPool, future=True)

# SQL 初始化（表 + pgvector）
INIT_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id BIGSERIAL PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding vector({VECTOR_DIM}) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT,
  avatar_url TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 新增：覆盖索引（user_id, created_at desc）并包含 title 以覆盖列表查询
CREATE INDEX IF NOT EXISTS idx_conversations_user_created_at_desc ON conversations(user_id, created_at DESC) INCLUDE (title);

CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  conv_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 新增索引以支撑查询与归档
CREATE INDEX IF NOT EXISTS idx_messages_conv_id_created_at ON messages(conv_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

CREATE TABLE IF NOT EXISTS attachments (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 生产环境建议：为 ivfflat 设置合适 lists，并在大量写入后 ANALYZE
-- 可选：ALTER INDEX idx_chunks_embedding SET (lists = 100);
"""

def db_init():
    # 使用 advisory lock 保证在多进程并发下仅执行一次
    with engine.begin() as conn:
        conn.exec_driver_sql("SELECT pg_advisory_lock(9876543210)")
        try:
            conn.exec_driver_sql(INIT_SQL)
            # 统计信息更新，利于查询计划
            conn.exec_driver_sql("ANALYZE")
        finally:
            conn.exec_driver_sql("SELECT pg_advisory_unlock(9876543210)")

# 应用启动后单次初始化：避免在多进程下重复执行
try:
    db_init()
except Exception as e:
    logger.exception("数据库初始化失败：%s", e)
    raise

# 启动时对外部依赖进行自检（embedding/reranker/chat 三个 URL/TOKEN）
def _startup_self_check():
    def _req_ok(url, token, payload):
        if not url or not token:
            return False
        try:
            r = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=10)
            return 200 <= r.status_code < 500  # 4xx 也认为连通性正常（如参数错误）
        except Exception:
            return False

    errs = []
    # embedding
    if not EMBEDDING_API_URL or not EMBEDDING_API_TOKEN:
        errs.append("缺少 EMBEDDING_API_URL 或 EMBEDDING_API_TOKEN")
    elif not _req_ok(f"{EMBEDDING_API_URL}/v1/embeddings", {"Authorization": f"Bearer {EMBEDDING_API_TOKEN}"}, {"model": EMBEDDING_MODEL, "input": ["ping"]}):
        errs.append("无法连通 Embedding 服务，请检查 EMBEDDING_API_URL/TOKEN/MODEL")
    # reranker
    if not RERANKER_API_URL or not RERANKER_API_TOKEN:
        errs.append("缺少 RERANKER_API_URL 或 RERANKER_API_TOKEN")
    elif not _req_ok(f"{RERANKER_API_URL}/v1/rerank", {"Authorization": f"Bearer {RERANKER_API_TOKEN}"}, {"model": RERANKER_MODEL, "query": "ping", "documents": ["a", "b"], "top_n": 1}):
        errs.append("无法连通 Reranker 服务，请检查 RERANKER_API_URL/TOKEN/MODEL")
    # chat
    if not CHAT_API_URL or not CHAT_API_TOKEN:
        errs.append("缺少 CHAT_API_URL 或 CHAT_API_TOKEN")
    elif not _req_ok(f"{CHAT_API_URL}/v1/chat/completions", {"Authorization": f"Bearer {CHAT_API_TOKEN}"}, {"model": CHAT_MODEL, "messages": [{"role":"user","content":"ping"}]}):
        errs.append("无法连通 Chat 服务，请检查 CHAT_API_URL/TOKEN/MODEL")

    if errs:
        for e in errs:
            logger.critical("[启动自检] %s", e)
        raise SystemExit("外部依赖自检失败，拒绝启动")

# 在数据库初始化后执行外部依赖自检
_startup_self_check()

# 删除重复的 Flask 实例化，避免覆盖配置与路由
# app = Flask(__name__, static_folder="static", static_url_path="/static")
# app.secret_key = SECRET_KEY

def require_login():
    if "user" not in session:
        abort(401)

def current_user():
    return session.get("user")

# OIDC（GitLab）
def oidc_discovery():
    conf_url = f"{GITLAB_URL}/.well-known/openid-configuration"
    with urllib.request.urlopen(conf_url, timeout=10) as resp:
        return json.loads(resp.read().decode())

def _get_jwks(jwks_uri):
    with urllib.request.urlopen(jwks_uri, timeout=10) as resp:
        return json.loads(resp.read().decode())

def _b64url_decode(b):
    pad = '=' * (-len(b) % 4)
    return base64.urlsafe_b64decode(b + pad)

def _verify_jwt_rs256(id_token, expected_iss, expected_aud, expected_nonce=None):
    # 优先使用 jose/cryptography 完整验签；若关闭或失败则回退到仅声明校验（不建议生产）
    disc = oidc_discovery()
    if USE_JOSE_VERIFY:
        try:
            from jose import jwt
            from jose.utils import base64url_decode  # 触发 ImportError 时落入回退逻辑
            jwks = _get_jwks(disc["jwks_uri"])
            # 构造 jwks 客户端验证
            # python-jose 直接传递 jwk 集合通过 options 验证
            options = {
                "verify_signature": True,
                "verify_aud": True,
                "verify_iat": True,
                "verify_exp": True,
                "verify_nbf": True,
                "require_exp": True,
                "require_iat": False,
                "require_nbf": False,
            }
            payload = jwt.decode(
                id_token,
                jwks,  # 直接传入 JWKS（python-jose 支持字典包含 "keys"）
                algorithms=["RS256"],
                audience=expected_aud,
                issuer=expected_iss,
                options=options,
            )
            if expected_nonce is not None and payload.get("nonce") != expected_nonce:
                raise ValueError("nonce 不匹配")
            return payload
        except Exception as e:
            logger.warning("使用 jose 验签失败，将回退到最小声明校验（不建议生产）：%s", e)

    # 回退：仅 iss/aud/exp/nonce 声明校验（不做签名校验）
    jwks = _get_jwks(disc["jwks_uri"])
    header_b64, payload_b64, sig_b64 = id_token.split(".")
    header = json.loads(_b64url_decode(header_b64).decode())
    payload = json.loads(_b64url_decode(payload_b64).decode())
    alg = header.get("alg")
    if alg != "RS256":
        raise ValueError("不支持的签名算法")
    now = int(time.time())
    iss_ok = payload.get("iss") == expected_iss
    aud_field = payload.get("aud")
    aud_ok = (aud_field == expected_aud) or (isinstance(aud_field, list) and expected_aud in aud_field)
    exp_ok = int(payload.get("exp", 0)) > now
    nonce_ok = True if expected_nonce is None else (payload.get("nonce") == expected_nonce)
    if not (iss_ok and aud_ok and exp_ok and nonce_ok):
        raise ValueError("ID Token 声明校验失败")
    payload["_unsigned_validated"] = True
    return payload

def oidc_build_auth_url(state, code_challenge):
    disc = oidc_discovery()
    redirect_uri = OIDC_REDIRECT_URI or url_for("oidc_callback", _external=True)
    params = {
        "response_type": "code",
        "client_id": GITLAB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "nonce": state.split(".")[0],  # 使用 state 内的 nonce 片段
    }
    return disc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

def oidc_exchange_token(code, code_verifier):
    disc = oidc_discovery()
    redirect_uri = OIDC_REDIRECT_URI or url_for("oidc_callback", _external=True)
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": GITLAB_CLIENT_ID,
        "client_secret": GITLAB_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }).encode()
    req = urllib.request.Request(disc["token_endpoint"], data=data, headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def oidc_jwt_decode(id_token):
    # 兼容旧调用：做最基础解码（不再对外使用）
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid id_token")
    payload = parts[1]
    payload_bytes = _b64url_decode(payload)
    return json.loads(payload_bytes.decode())

@app.route("/chat/login")
def login():
    # state: <nonce>.<ts>.<rand>
    nonce = secrets.token_urlsafe(16)
    ts = int(time.time())
    rand = secrets.token_urlsafe(8)
    state = f"{nonce}.{ts}.{rand}"
    code_verifier = secrets.token_urlsafe(64)
    # 保存并设置过期（10分钟）
    session["oidc_state"] = state
    session["oidc_state_exp"] = ts + 600
    session["code_verifier"] = code_verifier
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    return redirect(oidc_build_auth_url(state, code_challenge))

@app.route("/chat/oidc/callback")
def oidc_callback():
    state = request.args.get("state")
    code = request.args.get("code")
    now = int(time.time())
    sess_state = session.get("oidc_state")
    sess_exp = int(session.get("oidc_state_exp") or 0)
    if not state or state != sess_state or now > sess_exp:
        return "Invalid or expired state", 400
    if not code:
        return "Missing code", 400
    token = oidc_exchange_token(code, session.get("code_verifier"))
    # 安全校验：iss/aud/exp/nonce（GitLab 文档：iss=https://gitlab.example.com，aud=client_id）
    expected_iss = GITLAB_URL
    expected_aud = GITLAB_CLIENT_ID
    expected_nonce = state.split(".")[0]
    try:
        idp = _verify_jwt_rs256(token["id_token"], expected_iss, expected_aud, expected_nonce)
    except Exception as e:
        logger.warning("ID Token 校验失败: %s", e)
        return "Invalid id_token", 400
    # 一次性使用：成功后删除 code_verifier/oidc_state
    session.pop("oidc_state", None)
    session.pop("oidc_state_exp", None)
    session.pop("code_verifier", None)
    user_id = idp.get("sub")
    name = idp.get("name") or idp.get("preferred_username") or idp.get("email") or "user"
    avatar_url = idp.get("picture")
    session["user"] = {"id": user_id, "name": name, "avatar_url": avatar_url}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, name, avatar_url) VALUES (:id,:name,:avatar) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, avatar_url=EXCLUDED.avatar_url"),
                     {"id": user_id, "name": name, "avatar": avatar_url})
    return redirect("/chat")

@app.route("/chat/logout")
def logout():
    session.clear()
    return redirect("/chat")

# 静态前端
@app.route("/chat")
def chat_page():
    if "user" not in session:
        return redirect("/chat/login")
    resp = send_from_directory(app.static_folder, "index.html")
    # 明确声明 HTML 编码
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # 可选缓存控制
    resp.headers.setdefault("Cache-Control", "public, max-age=300")
    return resp

# 新增静态资源直达路由（用于反向代理固定路径）
@app.route("/chat/static/style.css")
def chat_static_style():
    resp = send_from_directory(app.static_folder, "style.css")
    # 交由 Flask 自动推断 mimetype，也可保留如下行
    resp.headers["Content-Type"] = "text/css; charset=utf-8"
    resp.headers.setdefault("Cache-Control", "public, max-age=86400")
    return resp

@app.route("/chat/static/script.js")
def chat_static_script():
    resp = send_from_directory(app.static_folder, "script.js")
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers.setdefault("Cache-Control", "public, max-age=86400")
    return resp

# API：用户信息
@app.route("/chat/api/me")
def api_me():
    if "user" not in session:
        abort(401)
    # 统一使用 jsonify，避免重复设置 Content-Type
    return jsonify(session["user"])

# API：会话
@app.route("/chat/api/conversations", methods=["GET", "POST"])
def api_conversations():
    require_login()
    uid = current_user()["id"]
    # 保障性：确保用户记录存在，避免外键错误（例如旧会话中 session 有 user，但 users 表被清空过）
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, name, avatar_url) VALUES (:id,:name,:avatar) "
                 "ON CONFLICT (id) DO NOTHING"),
            {"id": uid, "name": current_user().get("name"), "avatar": current_user().get("avatar_url")}
        )
    if request.method == "POST":
        title = (request.json or {}).get("title") or "新会话"
        with engine.begin() as conn:
            r = conn.execute(text("INSERT INTO conversations (user_id, title) VALUES (:u,:t) RETURNING id"), {"u": uid, "t": title})
            cid = r.scalar()
        return jsonify({"id": cid, "title": title})
    else:
        # 分页参数：page（从1开始），page_size（默认20，最大100）
        try:
            page = max(1, int(request.args.get("page", "1")))
        except Exception:
            page = 1
        try:
            page_size = int(request.args.get("page_size", "20"))
        except Exception:
            page_size = 20
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size
        with engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(1) FROM conversations WHERE user_id=:u"), {"u": uid}).scalar()
            rs = conn.execute(
                text("SELECT id, title, created_at FROM conversations WHERE user_id=:u ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
                {"u": uid, "lim": page_size, "off": offset}
            ).mappings().all()
        return jsonify({"items": [dict(r) for r in rs], "total": int(total), "page": page, "page_size": page_size})

@app.route("/chat/api/messages")
def api_messages():
    require_login()
    uid = current_user()["id"]
    conv_id = request.args.get("conv_id")
    if not conv_id:
        return jsonify({"items": [], "total": 0, "page": 1, "page_size": 20})
    # 分页参数
    try:
        page = max(1, int(request.args.get("page", "1")))
    except Exception:
        page = 1
    try:
        page_size = int(request.args.get("page_size", "50"))
    except Exception:
        page_size = 50
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size
    with engine.begin() as conn:
        own = conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": uid}).scalar()
        if not own:
            abort(403)
        total = conn.execute(text("SELECT COUNT(1) FROM messages WHERE conv_id=:cid"), {"cid": conv_id}).scalar()
        rs = conn.execute(
            text("SELECT id, role, content, created_at FROM messages WHERE conv_id=:cid ORDER BY id ASC LIMIT :lim OFFSET :off"),
            {"cid": conv_id, "lim": page_size, "off": offset}
        ).mappings().all()
    return jsonify({"items": [dict(r) for r in rs], "total": int(total), "page": page, "page_size": page_size})

# OpenAI 兼容 HTTP 调用
def http_post_json(url, payload, token, stream=False):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    # 统一超时与重试
    timeout = (5, 60) if not stream else (5, 300)
    session_req = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        raise_on_status=False,
    )
    session_req.mount("http://", HTTPAdapter(max_retries=retry))
    session_req.mount("https://", HTTPAdapter(max_retries=retry))
    try:
        if not stream:
            resp = session_req.post(url, json=payload, headers=headers, timeout=timeout)
            if not (200 <= resp.status_code < 300):
                # 避免泄露敏感 token/payload
                logger.warning("http_post_json non-2xx: %s body_len=%s", resp.status_code, len(resp.text or ""))
                return None
            try:
                return resp.json()
            except Exception:
                logger.warning("http_post_json JSON decode error")
                return None
        else:
            resp = session_req.post(url, json=payload, headers=headers, timeout=timeout, stream=True)
            if not (200 <= resp.status_code < 300):
                logger.warning("http_post_json(stream) non-2xx: %s", resp.status_code)
                return None
            return resp
    except requests.Timeout:
        logger.warning("http_post_json timeout: %s", url)
        return None
    except requests.RequestException as e:
        logger.warning("http_post_json error: %s", e)
        return None

def create_embeddings(texts):
    payload = {"model": EMBEDDING_MODEL, "input": texts}
    res = http_post_json(f"{EMBEDDING_API_URL}/v1/embeddings", payload, EMBEDDING_API_TOKEN)
    if not res:
        return [[] for _ in texts]
    vecs = [item.get("embedding", []) for item in res.get("data", [])]
    return vecs

def rerank(query, passages, top_k=5):
    payload = {"model": RERANKER_MODEL, "query": query, "documents": passages, "top_n": top_k}
    res = http_post_json(f"{RERANKER_API_URL}/v1/rerank", payload, RERANKER_API_TOKEN)
    if not res:
        return []
    items = res.get("results") or res.get("data") or []
    ranked = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    return ranked

# def _log_chat_messages_for_debug(messages, stream_flag):
#     try:
#         return
#     except Exception as e:
#         logger.warning("Failed to log chat messages: %s", e)

def chat_completion(messages, temperature=0.2):
    # 安全日志（可选截断）
    if SAFE_LOG_CHAT_INPUT:
        try:
            preview = json.dumps(messages, ensure_ascii=False)
            if len(preview) > MAX_LOG_INPUT_CHARS:
                preview = preview[:MAX_LOG_INPUT_CHARS] + "...(truncated)"
            logger.info("chat_completion input preview(len=%s)", len(preview))
        except Exception:
            pass
    payload = {"model": CHAT_MODEL, "messages": messages, "temperature": temperature, "stream": False}
    res = http_post_json(f"{CHAT_API_URL}/v1/chat/completions", payload, CHAT_API_TOKEN)
    if not res:
        return "对话服务不可用，请稍后重试。"
    try:
        return res["choices"][0]["message"]["content"]
    except Exception:
        return "对话服务返回格式异常。"

def chat_completion_stream(messages, temperature=0.2):
    if SAFE_LOG_CHAT_INPUT:
        try:
            preview = json.dumps(messages, ensure_ascii=False)
            if len(preview) > MAX_LOG_INPUT_CHARS:
                preview = preview[:MAX_LOG_INPUT_CHARS] + "...(truncated)"
            logger.info("chat_completion_stream input preview(len=%s)", len(preview))
        except Exception:
            pass
    payload = {"model": CHAT_MODEL, "messages": messages, "temperature": temperature, "stream": True}
    resp = http_post_json(f"{CHAT_API_URL}/v1/chat/completions", payload, CHAT_API_TOKEN, stream=True)
    if resp is None:
        yield "data: " + json.dumps({"error": "上游流式接口不可用"}) + "\n\n"
        yield "data: [DONE]\n\n"
        return
    try:
        for line in resp.iter_lines(decode_unicode=False):
            if not line:
                continue
            try:
                line = line.decode("utf-8", errors="ignore")
            except Exception:
                continue
            if line.startswith("data: "):
                data = line[len("data: "):]
                if data == "[DONE]":
                    yield "data: [DONE]\n\n"
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content", "")
                except Exception:
                    delta = ""
                if delta:
                    yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
    except requests.RequestException as e:
        # 网络中断时优雅结束
        logger.warning("stream interrupted: %s", e)
        yield "data: " + json.dumps({"error": "与上游连接中断"}) + "\n\n"
        yield "data: [DONE]\n\n"
    finally:
        try:
            resp.close()
        except Exception:
            pass

# RAG：向量检索
def search_similar(query, k=12):
    q_emb = create_embeddings([query])[0]
    # 以 JSON 文本传入，避免 ::vector 绑定语法问题
    qv_text = json.dumps(q_emb)
    with engine.begin() as conn:
        rs = conn.execute(text("""
                               SELECT id, doc_id, idx, content, 1 - (embedding <=> (:qv_text)::vector) AS score
                               FROM chunks
                               ORDER BY embedding <=> (:qv_text)::vector
            LIMIT :k
                               """), {"qv_text": qv_text, "k": k}).mappings().all()
    return [dict(r) for r in rs]

# Chunk
def chunk_text(text, max_chars=1000, overlap=200):
    text = text.strip()
    if not text:
        return []
    # 优先按段落与句子切分，尽量避免过短片段
    import re
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    sentences = []
    for p in paragraphs:
        # 基于中文/英文标点切句
        parts = re.split(r"(?<=[。！？!?；;])\s*|(?<=[!])\s+", p)
        parts = [s.strip() for s in parts if s.strip()]
        sentences.extend(parts if parts else [p])

    chunks = []
    buf = ""
    for s in sentences:
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_chars:
            buf = f"{buf}\n{s}"
        else:
            if len(buf) >= max(100, overlap):  # 避免极短片段
                chunks.append(buf)
            else:
                # 与下一句合并，尽量不输出太短
                buf = f"{buf} {s}" if len(buf) + 1 + len(s) <= max_chars else s
                continue
            # 滑窗重叠
            if overlap > 0 and chunks[-1]:
                tail = chunks[-1][-overlap:]
            else:
                tail = ""
            buf = tail + s if len(tail) + len(s) <= max_chars else s
    if buf and len(buf) >= 100:
        chunks.append(buf)
    return chunks

# Outline API
def outline_headers():
    return {"Authorization": f"Bearer {OUTLINE_API_TOKEN}", "Content-Type":"application/json"}

def http_get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            try:
                return json.loads(resp.read().decode())
            except Exception:
                logger.warning("http_get_json JSON decode error: %s", url)
                return None
    except Exception as e:
        logger.warning("http_get_json error: %s", e)
        return None

def http_post_json_raw(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers or {"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            try:
                return json.loads(resp.read().decode())
            except Exception:
                logger.warning("http_post_json_raw JSON decode error: %s", url)
                return None
    except Exception as e:
        logger.warning("http_post_json_raw error: %s", e)
        return None

def outline_list_docs():
    results = []
    limit = 100
    offset = 0
    while True:
        u = f"{OUTLINE_API_URL}/api/documents.list?limit={limit}&offset={offset}"
        data = http_post_json_raw(u, {}, headers=outline_headers())
        if not data:
            break
        docs = data.get("data", [])
        results.extend(docs)
        if len(docs) < limit:
            break
        offset += limit
    return results

def outline_get_doc(doc_id):
    u = f"{OUTLINE_API_URL}/api/documents.info"
    data = http_post_json_raw(u, {"id": doc_id}, headers=outline_headers())
    return data.get("data") if data else None

# 同步：全量刷新
def refresh_all():
    docs = outline_list_docs()
    # 一次性清空相关表，避免外键限制与锁顺序问题
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE chunks, documents RESTART IDENTITY CASCADE"))
    # 逐文档 upsert，避免主键冲突导致整个过程失败
    for d in docs:
        doc_id = d["id"]
        info = outline_get_doc(doc_id)
        if not info:
            continue
        title = info.get("title") or ""
        content = info.get("text") or ""
        updated_at = info.get("updatedAt") or info.get("updated_at") or datetime.now(timezone.utc).isoformat()
        chunks = chunk_text(content)
        if not chunks:
            # 没有内容则跳过
            continue
        embs = create_embeddings(chunks)
        with engine.begin() as conn:
            # documents 使用 upsert，避免重复
            conn.execute(text("""
                              INSERT INTO documents (id, title, content, updated_at)
                              VALUES (:id, :t, :c, :u)
                                  ON CONFLICT (id) DO UPDATE
                                                          SET title=EXCLUDED.title, content=EXCLUDED.content, updated_at=EXCLUDED.updated_at
                              """), {"id": doc_id, "t": title, "c": content, "u": updated_at})
            # 重建该文档的 chunks
            for idx, (ck, emb) in enumerate(zip(chunks, embs)):
                conn.execute(text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:d,:i,:c,:e)"),
                             {"d": doc_id, "i": idx, "c": ck, "e": emb})

# 增量：Webhook 处理（签名校验）
def verify_outline_signature(raw_body, signature_hex: str) -> bool:
    # 若显式关闭签名校验，则直接通过
    if not OUTLINE_WEBHOOK_SIGN:
        return True
    # 兼容常见前缀与空白
    try:
        sig = (signature_hex or "").strip()
        # 支持 "sha256=<hex>" 或 "Bearer <hex>"
        if sig.lower().startswith("sha256="):
            sig = sig.split("=", 1)[1].strip()
        if sig.lower().startswith("bearer "):
            sig = sig.split(" ", 1)[1].strip()
        mac = hmac.new(OUTLINE_WEBHOOK_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception as e:
        logger.warning("verify_outline_signature error: %s", e)
        return False

def upsert_one_doc(doc_id):
    info = outline_get_doc(doc_id)
    if not info:
        return
    title = info.get("title") or ""
    content = info.get("text") or ""
    updated_at = info.get("updatedAt") or info.get("updated_at") or datetime.now(timezone.utc).isoformat()
    chunks = chunk_text(content)
    if not chunks:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
        return
    embs = create_embeddings(chunks)
    with engine.begin() as conn:
        conn.execute(text("""
                          INSERT INTO documents (id, title, content, updated_at) VALUES (:id,:t,:c,:u)
                              ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, content=EXCLUDED.content, updated_at=EXCLUDED.updated_at
                          """), {"id": doc_id, "t": title, "c": content, "u": updated_at})
        conn.execute(text("DELETE FROM chunks WHERE doc_id=:d"), {"d": doc_id})
        for idx, (ck, emb) in enumerate(zip(chunks, embs)):
            conn.execute(text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:d,:i,:c,:e)"),
                         {"d": doc_id, "i": idx, "c": ck, "e": emb})

def delete_doc(doc_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})

# 端点：手动全量刷新
_refresh_lock = None  # 进程级互斥锁延迟初始化

@app.route("/chat/update/all", methods=["POST"])
def update_all():
    require_login()
    global _refresh_lock
    if _refresh_lock is None:
        import threading
        _refresh_lock = threading.Lock()
    locked = _refresh_lock.acquire(timeout=1.0)
    if not locked:
        return jsonify({"ok": False, "error": "正在刷新中，请稍后重试"}), 429
    try:
        refresh_all()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("refresh_all failed: %s", e)
        return jsonify({"ok": False, "error": "refresh_all failed"}), 500
    finally:
        try:
            _refresh_lock.release()
        except Exception:
            pass

# 端点：Webhook 增量
@app.route("/chat/update/webhook", methods=["POST"])
def update_webhook():
    raw = request.get_data()  # 原始字节，禁止任何预解析
    # 兼容不同大小写与备选头名
    sig = (
            request.headers.get("X-Outline-Signature")
            or request.headers.get("x-outline-signature")
            or request.headers.get("X-Outline-Signature-256")
            or request.headers.get("X-Signature")
    )
    # 当 OUTLINE_WEBHOOK_SIGN=false 时，跳过签名校验；否则要求密钥与签名正确
    if OUTLINE_WEBHOOK_SIGN:
        if not OUTLINE_WEBHOOK_SECRET or not verify_outline_signature(raw, sig):
            # 仅记录安全信息，避免泄露签名/正文
            logger.warning(
                "Webhook signature invalid: has_secret=%s, has_sig=%s, sig_len=%s, ct=%s",
                bool(OUTLINE_WEBHOOK_SECRET),
                bool(sig),
                (len(sig) if sig else 0),
                request.headers.get("Content-Type"),
            )
            return "invalid signature", 401
    else:
        logger.info("Webhook signature verification disabled by OUTLINE_WEBHOOK_SIGN")

    data = request.get_json(force=True, silent=True) or {}
    event = data.get("event")
    doc_id = (data.get("document") or {}).get("id") or data.get("documentId")
    if event in ("documents.create", "documents.update"):
        if doc_id:
            upsert_one_doc(doc_id)
    elif event in ("documents.delete", "documents.permanent_delete"):
        if doc_id:
            delete_doc(doc_id)
    return jsonify({"ok": True})

# 附件上传与检索（文本解析后入库，可参与 RAG）
@app.route("/chat/api/upload", methods=["POST"])
def upload():
    require_login()
    uid = current_user()["id"]
    if "file" not in request.files:
        return jsonify({"error":"missing file"}), 400
    f = request.files["file"]
    name_raw = f.filename or "untitled.txt"
    name = secure_filename(name_raw)
    # 更严格文件名校验（长度与控制字符）
    if len(name) == 0 or len(name) > 200 or any(ord(ch) < 32 for ch in name):
        return jsonify({"error":"invalid filename"}), 400
    if not allowed_file(name):
        return jsonify({"error":"file type not allowed"}), 400
    raw = f.read()
    try:
        content = raw.decode("utf-8", errors="ignore")
    except Exception:
        content = ""

    # 保存原始文件到持久化目录
    ts = int(time.time()*1000)
    disk_name = f"{uid}_{ts}_{name}"
    with open(os.path.join(ATTACHMENTS_DIR, disk_name), "wb") as wf:
        wf.write(raw)

    # 入库 attachments
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO attachments (user_id, filename, content) VALUES (:u,:n,:c)"),
                     {"u": uid, "n": name, "c": content})

    # 向量化
    doc_id = f"att:{uid}:{ts}:{secrets.token_hex(4)}"
    title = f"[附件] {name}"
    chunks = chunk_text(content)
    if chunks:
        embs = create_embeddings(chunks)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO documents (id, title, content, updated_at) VALUES (:id,:t,:c,NOW())"),
                         {"id": doc_id, "t": title, "c": content})
            for idx, (ck, emb) in enumerate(zip(chunks, embs)):
                conn.execute(text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:d,:i,:c,:e)"),
                             {"d": doc_id, "i": idx, "c": ck, "e": emb})
    resp = make_response(jsonify({"ok": True, "filename": name}))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return resp

# RAG 问答（SSE 始终开启）
@app.route("/chat/api/ask", methods=["POST"])
def api_ask():
    require_login()
    body = request.get_json(force=True)
    query = (body.get("query") or "").strip()
    conv_id = body.get("conv_id")
    # 流式开关移除：始终流式返回
    if not query or not conv_id:
        return jsonify({"error":"missing query or conv_id"}), 400

    uid = current_user()["id"]
    with engine.begin() as conn:
        own = conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": uid}).scalar()
        if not own:
            abort(403)
        conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'user',:c)"), {"cid": conv_id, "c": query})

    candidates = search_similar(query, k=12)
    passages = [c["content"] for c in candidates]
    if passages:
        ranked = rerank(query, passages, top_k=min(6, len(passages)))
        top_passages = []
        for r in ranked:
            idx = r.get("index")
            if idx is not None and 0 <= idx < len(passages):
                top_passages.append(passages[idx])
        contexts = top_passages[:5] if top_passages else passages[:5]
    else:
        contexts = []

    system_prompt = "你是一个企业知识库助理。使用提供的参考片段回答问题。如果参考不足，请明确说明。回答使用中文。"
    context_block = "\n\n".join([f"[片段{i+1}]\n{ctx}" for i, ctx in enumerate(contexts)])
    user_prompt = f"问题：{query}\n\n参考资料（可能不完整，请谨慎）：\n{context_block}"

    messages = [
        {"role":"system","content": system_prompt},
        {"role":"user","content": user_prompt}
    ]

    def generate():
        # 不再写入 BOM；先发注释行维持连接
        yield ": ping\n\n"
        buffer = []
        for chunk in chat_completion_stream(messages):
            # chunk 已是 "data: {...}\n\n" 或 DONE
            if chunk.startswith("data: ") and "[DONE]" not in chunk:
                try:
                    payload = json.loads(chunk[len("data: "):].strip())
                    delta = payload.get("delta", "")
                except Exception:
                    delta = ""
                if delta:
                    buffer.append(delta)
            yield chunk
        # 流结束后落库
        full = "".join(buffer)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'assistant',:c)"),
                         {"cid": conv_id, "c": full})

    resp = app.response_class(generate(), mimetype="text/event-stream; charset=utf-8")
    # SSE 头加强
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

from werkzeug.utils import secure_filename

MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "10485760"))  # 10MB
ALLOWED_FILE_EXTENSIONS = set([e.strip().lower() for e in os.getenv("ALLOWED_FILE_EXTENSIONS", "txt,md,pdf").split(",") if e.strip()])
ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", "/app/data/attachments")

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

def allowed_file(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_FILE_EXTENSIONS
# 健康检查
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "/app/data/archive")

def archive_old_messages(days=90, batch_size=5000):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    while True:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                                     SELECT id, conv_id, role, content, created_at
                                     FROM messages
                                     WHERE created_at < :cutoff
                                     ORDER BY id
                                         LIMIT :limit
                                     """), {"cutoff": cutoff, "limit": batch_size}).mappings().all()
            if not rows:
                break
            # 写入归档文件
            ts = int(time.time())
            fname = os.path.join(ARCHIVE_DIR, f"messages_archive_{ts}_{rows[0]['id']}_{rows[-1]['id']}.jsonl")
            with open(fname, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
            # 删除已归档
            ids = [r["id"] for r in rows]
            # 改为 ANY(%s) + psycopg2 数组绑定兼容写法（SQLAlchemy + psycopg2 可直接绑定 list）
            conn.execute(text("DELETE FROM messages WHERE id = ANY(:ids)"), {"ids": ids})

from datetime import timedelta
_last_archive_ts = 0

@app.route("/healthz")
def healthz():
    global _last_archive_ts
    now = time.time()
    if now - _last_archive_ts > 3600:  # 每小时尝试归档一次
        try:
            archive_old_messages(days=90, batch_size=2000)
        except Exception:
            pass
        _last_archive_ts = now
    return "ok"

if __name__ == "__main__":
    # 当直接运行时给出提示，推荐使用 gunicorn 启动
    logger.info("This app is intended to be run with gunicorn, e.g.: gunicorn -w 2 -k gthread -b 0.0.0.0:%s app:app", PORT)
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)