# 包含所有数据交互的 API 接口，例如消息、会话管理、RAG 问答、文件上传和 Webhook
import json
import logging
import os
import secrets
import threading
import time
import uuid
from flask import (Blueprint, jsonify, request, abort, make_response)
from werkzeug.utils import secure_filename
from sqlalchemy import text
import config
import rag
import services
from database import engine
from utils import require_login, current_user, allowed_file

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)
_refresh_lock = threading.Lock()

@api_bp.route("/api/me")
def api_me():
    if "user" not in (user_session := current_user() or {}):
        abort(401)
    return jsonify(user_session)

@api_bp.route("/api/conversations", methods=["GET", "POST"])
def api_conversations():
    require_login()
    uid = current_user()["id"]
    if request.method == "POST":
        title = (request.json or {}).get("title") or "新会话"
        guid = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :u, :t)"),
                         {"id": guid, "u": uid, "t": title})
        return jsonify({"id": guid, "title": title, "url": f"/chat/{guid}"})

    page = max(1, request.args.get("page", 1, type=int))
    page_size = max(1, min(100, request.args.get("page_size", 20, type=int)))
    offset = (page - 1) * page_size
    with engine.begin() as conn:
        total = conn.execute(text("SELECT COUNT(1) FROM conversations WHERE user_id=:u"), {"u": uid}).scalar()
        rs = conn.execute(text("SELECT id, title, created_at FROM conversations WHERE user_id=:u ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
                          {"u": uid, "lim": page_size, "off": offset}).mappings().all()
    items = [{"id": r["id"], "title": r["title"], "created_at": r["created_at"], "url": f"/chat/{r['id']}"} for r in rs]
    return jsonify({"items": items, "total": int(total or 0), "page": page, "page_size": page_size})

@api_bp.route("/api/conversations/<string:conv_id>/rename", methods=["POST"])
def api_conversation_rename(conv_id):
    require_login()
    title = (request.get_json(silent=True) or {}).get("title", "").strip()
    if not title: return jsonify({"ok": False, "error": "标题不能为空"}), 400
    with engine.begin() as conn:
        res = conn.execute(text("UPDATE conversations SET title=:t WHERE id=:id AND user_id=:u"),
                           {"t": title, "id": conv_id, "u": current_user()["id"]})
        if res.rowcount == 0: return jsonify({"ok": False, "error": "无权限"}), 403
    return jsonify({"ok": True})

@api_bp.route("/api/conversations/<string:conv_id>/delete", methods=["POST"])
def api_conversation_delete(conv_id):
    require_login()
    with engine.begin() as conn:
        res = conn.execute(text("DELETE FROM conversations WHERE id=:id AND user_id=:u"),
                           {"id": conv_id, "u": current_user()["id"]})
        if res.rowcount == 0: return jsonify({"ok": False, "error": "无权限"}), 403
    return jsonify({"ok": True})

@api_bp.route("/api/messages")
def api_messages():
    require_login()
    conv_id = request.args.get("conv_id")
    if not conv_id: return jsonify({"items": [], "total": 0}), 400
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"),
                            {"cid": conv_id, "u": current_user()["id"]}).scalar():
            abort(403)
        rs = conn.execute(text("SELECT id, role, content, created_at FROM messages WHERE conv_id=:cid ORDER BY id ASC"),
                          {"cid": conv_id}).mappings().all()
    return jsonify({"items": [dict(r) for r in rs], "total": len(rs)})

@api_bp.route("/api/ask", methods=["POST"])
def api_ask():
    require_login()
    body = request.get_json(force=True)
    query, conv_id = (body.get("query") or "").strip(), body.get("conv_id")
    if not query or not conv_id: return jsonify({"error":"missing query or conv_id"}), 400

    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": current_user()["id"]}).scalar(): abort(403)
        conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'user',:c)"), {"cid": conv_id, "c": query})

    candidates = rag.search_similar(query, k=config.TOP_K)
    passages = [c["content"] for c in candidates]
    contexts = passages[:5]
    if passages:
        ranked = services.rerank(query, passages, top_k=min(config.K, len(passages)))
        top_passages = [passages[r["index"]] for r in ranked if r.get("index") is not None and 0 <= r["index"] < len(passages)]
        contexts = top_passages or passages[:5]

    system_prompt = "你是一个企业知识库助理..." # (保持原样)
    user_prompt = f"问题：{query}\n\n参考资料片段：\n" + "\n\n".join([f"[片段{i+1}]\n{ctx}" for i, ctx in enumerate(contexts)])
    messages = [{"role":"system","content": system_prompt}, {"role":"user","content": user_prompt}]

    def generate():
        yield ": ping\n\n"
        buffer = []
        resp_stream = services.chat_completion_stream(messages)
        if resp_stream is None:
            yield f"data: {json.dumps({'error': '上游服务不可用'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        for line in resp_stream.iter_lines(decode_unicode=True):
            if line.startswith("data:"):
                yield f"{line}\n\n"
                if "[DONE]" not in line:
                    try:
                        data = json.loads(line[len("data: "):])
                        if delta := data.get("choices", [{}])[0].get("delta", {}).get("content"):
                            buffer.append(delta)
                    except (json.JSONDecodeError, IndexError):
                        pass
        full_response = "".join(buffer)
        if full_response:
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'assistant',:c)"),
                             {"cid": conv_id, "c": full_response})

    resp = make_response(generate(), 200)
    resp.mimetype = "text/event-stream; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

@api_bp.route("/api/upload", methods=["POST"])
def upload():
    require_login()
    if "file" not in request.files or not (f := request.files["file"]).filename:
        return jsonify({"error":"missing file"}), 400

    name = secure_filename(f.filename)
    if not name or len(name) > 200 or not allowed_file(name):
        return jsonify({"error":"invalid filename or type"}), 400

    content = f.read().decode("utf-8", errors="ignore")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO attachments (user_id, filename, content) VALUES (:u,:n,:c)"),
                     {"u": current_user()["id"], "n": name, "c": content})

    doc_id = f"att:{current_user()['id']}:{int(time.time()*1000)}:{secrets.token_hex(4)}"
    rag.upsert_one_doc(doc_id)
    return jsonify({"ok": True, "filename": name})

@api_bp.route("/update/all", methods=["POST"])
def update_all():
    require_login()
    if not _refresh_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "正在刷新中"}), 429
    try:
        threading.Thread(target=lambda: (rag.refresh_all(), _refresh_lock.release()), daemon=True).start()
        return jsonify({"ok": True, "message": "已开始全量刷新"}), 202
    except Exception as e:
        _refresh_lock.release()
        logger.exception("refresh_all failed: %s", e)
        return jsonify({"ok": False, "error": "启动刷新失败"}), 500

@api_bp.route("/update/webhook", methods=["POST"])
def update_webhook():
    raw = request.get_data()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get("X-Signature")
    if config.OUTLINE_WEBHOOK_SIGN and not rag.verify_outline_signature(raw, sig):
        return "invalid signature", 401

    data = request.get_json(force=True, silent=True) or {}
    event = data.get("event")
    doc_id = (data.get("document") or {}).get("id") or data.get("documentId")
    if doc_id:
        if event in ("documents.create", "documents.update"):
            rag.upsert_one_doc(doc_id)
        elif event in ("documents.delete", "documents.permanent_delete"):
            rag.delete_doc(doc_id)
    return jsonify({"ok": True})