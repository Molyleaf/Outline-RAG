import os
import hmac
import hashlib
import json
import time
import base64
import secrets
import urllib.parse
from datetime import datetime, timezone

from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory, abort
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

# 环境变量
PORT = int(os.getenv("PORT", "8080"))
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "1024"))

POSTGRES_DB = os.getenv("POSTGRES_DB", "outline_rag")
POSTGRES_USER = os.getenv("POSTGRES_USER", "outline")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "outlinepass")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

OUTLINE_API_URL = os.getenv("OUTLINE_API_URL", "").rstrip("/")
OUTLINE_API_TOKEN = os.getenv("OUTLINE_API_TOKEN", "")
OUTLINE_WEBHOOK_SECRET = os.getenv("OUTLINE_WEBHOOK_SECRET", "")

EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "").rstrip("/")
EMBEDDING_API_TOKEN = os.getenv("EMBEDDING_API_TOKEN", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

RERANKER_API_URL = os.getenv("RERANKER_API_URL", "").rstrip("/")
RERANKER_API_TOKEN = os.getenv("RERANKER_API_TOKEN", "")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "bge-reranker-m2")

CHAT_API_URL = os.getenv("CHAT_API_URL", "").rstrip("/")
CHAT_API_TOKEN = os.getenv("CHAT_API_TOKEN", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "your-chat-model")

GITLAB_CLIENT_ID = os.getenv("GITLAB_CLIENT_ID", "")
GITLAB_CLIENT_SECRET = os.getenv("GITLAB_CLIENT_SECRET", "")
GITLAB_URL = os.getenv("GITLAB_URL", "").rstrip("/")

SECRET_KEY = os.getenv("SECRET_KEY", None) or base64.urlsafe_b64encode(os.urandom(32)).decode()

# Flask
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = SECRET_KEY

# 数据库
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

CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  conv_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, -- 'user' or 'assistant' or 'system'
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attachments (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

def db_init():
    with engine.begin() as conn:
        conn.exec_driver_sql(INIT_SQL)

@app.before_first_request
def _init():
    db_init()

def require_login():
    if "user" not in session:
        abort(401)

def current_user():
    return session.get("user")

# OIDC（GitLab）
def oidc_discovery():
    conf_url = f"{GITLAB_URL}/.well-known/openid-configuration"
    import urllib.request
    with urllib.request.urlopen(conf_url, timeout=10) as resp:
        return json.loads(resp.read().decode())

def oidc_build_auth_url(state, code_challenge):
    disc = oidc_discovery()
    params = {
        "response_type": "code",
        "client_id": GITLAB_CLIENT_ID,
        "redirect_uri": url_for("oidc_callback", _external=True),
        "scope": "openid profile email",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return disc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

def oidc_exchange_token(code, code_verifier, urllib=None):
    disc = oidc_discovery()
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": url_for("oidc_callback", _external=True),
        "client_id": GITLAB_CLIENT_ID,
        "client_secret": GITLAB_CLIENT_SECRET,
        "code_verifier": code_verifier,
    }).encode()
    import urllib.request
    req = urllib.request.Request(disc["token_endpoint"], data=data, headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def oidc_jwt_decode(id_token):
    # 简化示例：未校验签名
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid id_token")
    payload = parts[1] + "==="
    payload_bytes = base64.urlsafe_b64decode(payload[: len(payload) - (len(payload) % 4)])
    return json.loads(payload_bytes.decode())

@app.route("/login")
def login():
    state = secrets.token_urlsafe(16)
    code_verifier = secrets.token_urlsafe(64)
    session["oidc_state"] = state
    session["code_verifier"] = code_verifier
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
    return redirect(oidc_build_auth_url(state, code_challenge))

@app.route("/oidc/callback")
def oidc_callback():
    state = request.args.get("state")
    if not state or state != session.get("oidc_state"):
        return "Invalid state", 400
    code = request.args.get("code")
    if not code:
        return "Missing code", 400
    token = oidc_exchange_token(code, session.get("code_verifier"))
    idp = oidc_jwt_decode(token["id_token"])
    user_id = idp.get("sub")
    name = idp.get("name") or idp.get("preferred_username") or idp.get("email") or "user"
    avatar_url = idp.get("picture")
    session["user"] = {"id": user_id, "name": name, "avatar_url": avatar_url}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, name, avatar_url) VALUES (:id,:name,:avatar) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, avatar_url=EXCLUDED.avatar_url"),
                     {"id": user_id, "name": name, "avatar": avatar_url})
    return redirect("/chat")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/chat")

# 静态前端
@app.route("/chat")
def chat_page():
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(app.static_folder, "index.html")

# API：用户信息
@app.route("/chat/api/me")
def api_me():
    if "user" not in session:
        abort(401)
    return jsonify(session["user"])

# API：会话
@app.route("/chat/api/conversations", methods=["GET", "POST"])
def api_conversations():
    require_login()
    uid = current_user()["id"]
    if request.method == "POST":
        title = (request.json or {}).get("title") or "新会话"
        with engine.begin() as conn:
            r = conn.execute(text("INSERT INTO conversations (user_id, title) VALUES (:u,:t) RETURNING id"), {"u": uid, "t": title})
            cid = r.scalar()
        return jsonify({"id": cid, "title": title})
    else:
        with engine.begin() as conn:
            rs = conn.execute(text("SELECT id, title, created_at FROM conversations WHERE user_id=:u ORDER BY created_at DESC"), {"u": uid}).mappings().all()
        return jsonify([dict(r) for r in rs])

@app.route("/chat/api/messages")
def api_messages():
    require_login()
    uid = current_user()["id"]
    conv_id = request.args.get("conv_id")
    if not conv_id:
        return jsonify([])
    with engine.begin() as conn:
        own = conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": uid}).scalar()
        if not own:
            abort(403)
        rs = conn.execute(text("SELECT id, role, content, created_at FROM messages WHERE conv_id=:cid ORDER BY id ASC"), {"cid": conv_id}).mappings().all()
    return jsonify([dict(r) for r in rs])

# OpenAI 兼容 HTTP 调用
def http_post_json(url, payload, token, stream=False):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={
        "Content-Type":"application/json",
        "Authorization": f"Bearer {token}"
    })
    if not stream:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    else:
        # 返回原始响应对象以供流式读取（使用标准库无法逐行迭代 chunk，这里改用生成器对 SSE 行处理）
        resp = urllib.request.urlopen(req, timeout=300)
        return resp  # 调用方负责关闭

def create_embeddings(texts):
    payload = {"model": EMBEDDING_MODEL, "input": texts}
    res = http_post_json(f"{EMBEDDING_API_URL}/v1/embeddings", payload, EMBEDDING_API_TOKEN)
    vecs = [item["embedding"] for item in res["data"]]
    return vecs

def rerank(query, passages, top_k=5):
    payload = {"model": RERANKER_MODEL, "query": query, "documents": passages, "top_n": top_k}
    res = http_post_json(f"{RERANKER_API_URL}/v1/rerank", payload, RERANKER_API_TOKEN)
    items = res.get("results") or res.get("data") or []
    ranked = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    return ranked

def chat_completion(messages, temperature=0.2):
    payload = {"model": CHAT_MODEL, "messages": messages, "temperature": temperature, "stream": False}
    res = http_post_json(f"{CHAT_API_URL}/v1/chat/completions", payload, CHAT_API_TOKEN)
    return res["choices"][0]["message"]["content"]

def chat_completion_stream(messages, temperature=0.2):
    # 以 OpenAI SSE 格式透传
    payload = {"model": CHAT_MODEL, "messages": messages, "temperature": temperature, "stream": True}
    resp = http_post_json(f"{CHAT_API_URL}/v1/chat/completions", payload, CHAT_API_TOKEN, stream=True)
    try:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            # SSE 以 "data: {...}" 行推送
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
    finally:
        try:
            resp.close()
        except Exception:
            pass

# RAG：向量检索
def search_similar(query, k=12):
    q_emb = create_embeddings([query])[0]
    with engine.begin() as conn:
        rs = conn.execute(text(f"""
            SELECT id, doc_id, idx, content, 1 - (embedding <=> :qv) AS score
            FROM chunks
            ORDER BY embedding <=> :qv
            LIMIT :k
        """), {"qv": q_emb, "k": k}).mappings().all()
    return [dict(r) for r in rs]

# Chunk
def chunk_text(text, max_chars=1000, overlap=200):
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + max_chars)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == n: break
        start = max(0, end - overlap)
    return chunks

# Outline API
def outline_headers():
    return {"Authorization": f"Bearer {OUTLINE_API_TOKEN}", "Content-Type":"application/json"}

def http_get_json(url, headers=None):
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())

def http_post_json_raw(url, payload, headers=None):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers or {"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())

def outline_list_docs():
    results = []
    limit = 100
    offset = 0
    while True:
        u = f"{OUTLINE_API_URL}/api/documents.list?limit={limit}&offset={offset}"
        data = http_post_json_raw(u, {}, headers=outline_headers())
        docs = data.get("data", [])
        results.extend(docs)
        if len(docs) < limit:
            break
        offset += limit
    return results

def outline_get_doc(doc_id):
    u = f"{OUTLINE_API_URL}/api/documents.info"
    data = http_post_json_raw(u, {"id": doc_id}, headers=outline_headers())
    return data.get("data")

# 同步：全量刷新
def refresh_all():
    docs = outline_list_docs()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE chunks RESTART IDENTITY CASCADE"))
        conn.execute(text("TRUNCATE documents CASCADE"))
    for d in docs:
        doc_id = d["id"]
        info = outline_get_doc(doc_id)
        if not info: continue
        title = info.get("title") or ""
        content = info.get("text") or ""
        updated_at = info.get("updatedAt") or info.get("updated_at") or datetime.now(timezone.utc).isoformat()
        chunks = chunk_text(content)
        if not chunks:
            continue
        embs = create_embeddings(chunks)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO documents (id, title, content, updated_at) VALUES (:id,:t,:c,:u)"),
                         {"id": doc_id, "t": title, "c": content, "u": updated_at})
            for idx, (ck, emb) in enumerate(zip(chunks, embs)):
                conn.execute(text("INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (:d,:i,:c,:e)"),
                             {"d": doc_id, "i": idx, "c": ck, "e": emb})

# 增量：Webhook 处理（签名校验）
def verify_outline_signature(raw_body, signature_hex: str) -> bool:
    mac = hmac.new(OUTLINE_WEBHOOK_SECRET.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature_hex or "")

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
@app.route("/chat/update/all", methods=["POST"])
def update_all():
    require_login()
    refresh_all()
    return jsonify({"ok": True})

# 端点：Webhook 增量
@app.route("/chat/update/webhook", methods=["POST"])
def update_webhook():
    raw = request.get_data()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get("x-outline-signature")
    if not OUTLINE_WEBHOOK_SECRET or not verify_outline_signature(raw, sig):
        return "invalid signature", 401
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
    name = f.filename or "untitled.txt"
    content = f.read().decode("utf-8", errors="ignore")
    # 入库 attachments
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO attachments (user_id, filename, content) VALUES (:u,:n,:c)"),
                     {"u": uid, "n": name, "c": content})
    # 将附件内容作为个人文档入向量库（按用户隔离：doc_id 前缀）
    doc_id = f"att:{uid}:{int(time.time()*1000)}:{secrets.token_hex(4)}"
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
    return jsonify({"ok": True, "filename": name})

# RAG 问答（支持流式）
@app.route("/chat/api/ask", methods=["POST"])
def api_ask():
    require_login()
    body = request.get_json(force=True)
    query = (body.get("query") or "").strip()
    conv_id = body.get("conv_id")
    stream = bool(body.get("stream", False))
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

    if not stream:
        answer = chat_completion(messages)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'assistant',:c)"), {"cid": conv_id, "c": answer})
        return jsonify({"answer": answer})
    else:
        def generate():
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
        return app.response_class(generate(), mimetype="text/event-stream")

# 健康检查
@app.route("/healthz")
def healthz():
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)