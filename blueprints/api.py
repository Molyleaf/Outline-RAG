# blueprints/api.py
import json
import logging
import secrets
import threading
import time
import uuid

from flask import (Blueprint, jsonify, request, abort, make_response, Response)
from sqlalchemy import text
from werkzeug.utils import secure_filename

import config
import rag
import services
from database import engine, redis_client
from utils import require_login, current_user, allowed_file

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

@api_bp.route("/api/me")
def api_me():
    require_login()
    return jsonify(current_user())

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
    # 删除关联的消息缓存
    if redis_client:
        redis_client.delete(f"messages:{conv_id}")
    return jsonify({"ok": True})

@api_bp.route("/api/messages")
def api_messages():
    require_login()
    conv_id = request.args.get("conv_id")
    if not conv_id: return jsonify({"items": [], "total": 0}), 400

    # 尝试从缓存获取
    cache_key = f"messages:{conv_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return Response(cached_data, mimetype='application/json')

    # 缓存未命中，从数据库获取
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"),
                            {"cid": conv_id, "u": current_user()["id"]}).scalar():
            abort(403)
        rs = conn.execute(text("SELECT id, role, content, created_at, model, temperature, top_p FROM messages WHERE conv_id=:cid ORDER BY id ASC"),
                          {"cid": conv_id}).mappings().all()

    # 序列化为字典列表，并处理日期时间对象
    items = [dict(r, created_at=r['created_at'].isoformat()) for r in rs]
    response_data = {"items": items, "total": len(rs)}
    response_json = json.dumps(response_data)

    # 存入缓存
    if redis_client:
        redis_client.set(cache_key, response_json)

    return Response(response_json, mimetype='application/json')

@api_bp.route("/api/ask", methods=["POST"])
def api_ask():
    require_login()
    body = request.get_json(force=True)
    query, conv_id = (body.get("query") or "").strip(), body.get("conv_id")
    model = body.get("model")
    temperature = body.get("temperature")
    top_p = body.get("top_p")

    if not query or not conv_id: return jsonify({"error":"missing query or conv_id"}), 400

    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": current_user()["id"]}).scalar(): abort(403)
        conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'user',:c)"), {"cid": conv_id, "c": query})

    # 用户消息已添加，删除缓存
    if redis_client:
        redis_client.delete(f"messages:{conv_id}")

    candidates = rag.search_similar(query, k=config.TOP_K)
    passages = [c["content"] for c in candidates]
    contexts = passages[:5]
    if passages:
        ranked = services.rerank(query, passages, top_k=min(config.K, len(passages)))
        top_passages = [passages[r["index"]] for r in ranked if r.get("index") is not None and 0 <= r["index"] < len(passages)]
        contexts = top_passages or passages[:5]

    system_prompt = "你是一个企业知识库助理。知识库基于我们开发中的科幻战争题材游戏，游戏世界位于一颗名为“余烬”的类地行星。\n游戏主要设定：1. 货币名为联合币，由北方企业联合体发行。\n2. 存在一种“屏障粒子”阻止了短波和微波在大气中传播。\n3. 核心玩法为舰船设计、海战和社交。\n\n使用提供的参考资料片段结合你的知识回答问题。\n\n回答使用中文。"
    user_prompt = f"问题：{query}\n\n参考资料片段：\n" + "\n\n".join([f"[片段{i+1}]\n{ctx}" for i, ctx in enumerate(contexts)])
    messages = [{"role":"system","content": system_prompt}, {"role":"user","content": user_prompt}]

    def generate():
        yield ": ping\n\n"
        buffer = []
        model_name = model # 默认使用请求的模型名
        resp_stream = services.chat_completion_stream(messages, model=model, temperature=temperature, top_p=top_p)
        if resp_stream is None:
            yield f"data: {json.dumps({'error': '上游服务不可用'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        resp_stream.encoding = 'utf-8'

        for line in resp_stream.iter_lines(decode_unicode=True):
            if line:
                yield f"{line}\n\n"
                if line.startswith("data:"):
                    if "[DONE]" not in line:
                        try:
                            data = json.loads(line[len("data: "):])
                            # 流数据中可能包含更具体的模型名称，优先使用
                            if data.get("model"):
                                model_name = data["model"]
                            if delta := data.get("choices", [{}])[0].get("delta", {}).get("content"):
                                buffer.append(delta)
                        except (json.JSONDecodeError, IndexError):
                            pass

        full_response = "".join(buffer)
        if full_response:
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO messages (conv_id, role, content, model, temperature, top_p) VALUES (:cid, 'assistant', :c, :m, :t, :p)"),
                    {"cid": conv_id, "c": full_response, "m": model_name, "t": temperature, "p": top_p}
                )
            # 助手消息已添加，再次删除缓存
            if redis_client:
                redis_client.delete(f"messages:{conv_id}")

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

def refresh_task():
    """在后台线程中执行的全量刷新任务"""
    try:
        num_docs = rag.refresh_all()
        if redis_client:
            status = {"status": "success", "message": f"全量刷新完成，共处理 {num_docs} 个文档。"}
            # 设置一个较短的过期时间，避免状态信息永久留存
            redis_client.set("refresh:status", json.dumps(status), ex=300)
            logger.info(status["message"])
    except Exception as e:
        logger.exception("refresh_all background task failed: %s", e)
        if redis_client:
            status = {"status": "error", "message": f"刷新失败: {e}"}
            redis_client.set("refresh:status", json.dumps(status), ex=300)
            logger.error(status["message"])
    finally:
        if redis_client:
            # 任务结束，删除锁
            redis_client.delete("refresh:lock")

@api_bp.route("/update/all", methods=["POST"])
def update_all():
    require_login()
    if not redis_client:
        return jsonify({"ok": False, "error": "任务队列服务未配置"}), 503

    # 使用 Redis 实现分布式锁，ex=3600 设置锁的过期时间为1小时，防止任务异常导致死锁
    if not redis_client.set("refresh:lock", "1", ex=3600, nx=True):
        return jsonify({"ok": False, "error": "正在刷新中"}), 429

    try:
        # 启动前清除旧的状态
        redis_client.delete("refresh:status")
        threading.Thread(target=refresh_task, daemon=True).start()
        return jsonify({"ok": True, "message": "已开始全量刷新"}), 202
    except Exception as e:
        # 如果启动线程失败，确保释放锁
        redis_client.delete("refresh:lock")
        logger.exception("Failed to start refresh_all task: %s", e)
        return jsonify({"ok": False, "error": "启动刷新失败"}), 500

@api_bp.route("/api/refresh/status", methods=["GET"])
def refresh_status():
    """轮询刷新状态"""
    require_login()
    if not redis_client:
        return jsonify({"status": "disabled", "message": "Redis not configured"})

    status_json = redis_client.get("refresh:status")
    if status_json:
        # 返回最终状态（成功或失败）
        return jsonify(json.loads(status_json))

    if redis_client.get("refresh:lock"):
        # 如果仍在锁定，说明正在运行
        return jsonify({"status": "running"})

    # 无锁也无最终状态，视为空闲
    return jsonify({"status": "idle"})

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