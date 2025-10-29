# blueprints/api.py
# API端点处理
import json
import logging
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
    if redis_client:
        redis_client.delete(f"messages:{conv_id}")
    return jsonify({"ok": True})

@api_bp.route("/api/messages")
def api_messages():
    require_login()
    conv_id = request.args.get("conv_id")
    if not conv_id: return jsonify({"items": [], "total": 0}), 400
    cache_key = f"messages:{conv_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return Response(cached_data, mimetype='application/json')
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"),
                            {"cid": conv_id, "u": current_user()["id"]}).scalar():
            abort(403)
        rs = conn.execute(text("SELECT id, role, content, created_at, model, temperature, top_p FROM messages WHERE conv_id=:cid ORDER BY id ASC"),
                          {"cid": conv_id}).mappings().all()
    items = [dict(r, created_at=r['created_at'].isoformat()) for r in rs]
    response_data = {"items": items, "total": len(rs)}
    response_json = json.dumps(response_data)
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

    if not query or not conv_id:
        return jsonify({"error":"missing query or conv_id"}), 400

    history_messages = []
    with engine.begin() as conn:
        # 验证会话所有权
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": current_user()["id"]}).scalar():
            abort(403)

        # 1. (修改) 获取历史消息
        rs = conn.execute(
            text("SELECT role, content FROM messages WHERE conv_id=:cid ORDER BY id DESC LIMIT :lim"),
            {"cid": conv_id, "lim": config.MAX_HISTORY_MESSAGES}
        ).mappings().all()
        # 反转列表，使消息按时间顺序排列 (旧 -> 新)
        history_messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rs)]

        # 2. 保存当前用户消息
        conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'user',:c)"), {"cid": conv_id, "c": query})

    # 清理消息缓存
    if redis_client:
        redis_client.delete(f"messages:{conv_id}")

    # --- (新增) 步骤 1: 查询重写 ---
    rewritten_query = query
    if history_messages:
        # 格式化历史
        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history_messages])
        # 构建重写提示词
        rewrite_prompt = config.REWRITE_PROMPT_TEMPLATE.format(history=history_str, query=query)
        rewrite_messages = [{"role": "user", "content": rewrite_prompt}]

        logger.info(f"[{conv_id}] Performing query rewrite...")
        # 调用阻塞式 API 进行重写（使用较低的温度以获取确定性输出）
        rewritten_query_from_llm = services.chat_completion_blocking(
            rewrite_messages,
            model=model,
            temperature=0.0,
            top_p=1.0
        )

        if rewritten_query_from_llm:
            rewritten_query = rewritten_query_from_llm
            logger.info(f"[{conv_id}] Original query: '{query}' -> Rewritten query: '{rewritten_query}'")
        else:
            logger.warning(f"[{conv_id}] Query rewrite failed, falling back to original query.")
            rewritten_query = query # 确保回退

    # --- 步骤 2: RAG 检索 (使用 rewritten_query) ---
    candidates = rag.search_similar(rewritten_query, k=config.TOP_K)
    passages = [c["content"] for c in candidates]
    contexts = passages[:5] # 默认回退
    if passages:
        ranked = services.rerank(rewritten_query, passages, top_k=min(config.K, len(passages)))
        top_passages = [passages[r["index"]] for r in ranked if r.get("index") is not None and 0 <= r["index"] < len(passages)]
        contexts = top_passages or passages[:5]

    # --- (修改) 步骤 3: 构建最终提示词 ---
    system_prompt = config.SYSTEM_PROMPT
    # 将多个上下文片段用分隔符连接
    continuous_context = "\n\n---\n\n".join(contexts)

    # 使用新的模板，填充上下文和 *原始* query
    final_user_prompt = config.HISTORY_AWARE_PROMPT_TEMPLATE.format(context=continuous_context, query=query)

    # 最终发送给 LLM 的消息列表：系统指令 + 历史 + RAG提示
    messages_for_llm = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": final_user_prompt}]

    # --- 步骤 4: 流式生成答案 ---
    def generate():
        yield ": ping\n\n"
        buffer = []
        model_name = model

        # (修改) 使用 messages_for_llm 进行调用
        resp_stream = services.chat_completion_stream(messages_for_llm, model=model, temperature=temperature, top_p=top_p)

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
                            if data.get("model"): model_name = data["model"]
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
    # 此处 upsert_one_doc 逻辑需要根据实际情况实现，暂时注释
    # doc_id = f"att:{current_user()['id']}:{int(time.time()*1000)}:{secrets.token_hex(4)}"
    # rag.upsert_one_doc(doc_id)
    return jsonify({"ok": True, "filename": name})

@api_bp.route("/update/all", methods=["POST"])
def update_all():
    require_login()
    if not redis_client:
        return jsonify({"ok": False, "error": "任务队列服务未配置"}), 503
    if not redis_client.set("refresh:lock", "1", ex=3600, nx=True):
        return jsonify({"ok": False, "error": "正在刷新中"}), 429
    try:
        task = {"task": "refresh_all"}
        redis_client.lpush("task_queue", json.dumps(task))
        return jsonify({"ok": True, "message": "已开始全量刷新"}), 202
    except Exception as e:
        redis_client.delete("refresh:lock")
        logger.exception("加入刷新任务到队列时失败: %s", e)
        return jsonify({"ok": False, "error": "启动刷新失败"}), 500

@api_bp.route("/api/refresh/status", methods=["GET"])
def refresh_status():
    """轮询刷新状态，能够报告实时进度和最终结果。"""
    require_login()
    if not redis_client:
        return jsonify({"status": "disabled", "message": "Redis not configured"})

    status_json = redis_client.get("refresh:status")
    if status_json:
        return jsonify(json.loads(status_json))

    if not redis_client.get("refresh:lock"):
        return jsonify({"status": "idle", "message": "空闲"})

    try:
        counts = redis_client.mget([
            "refresh:total_queued", "refresh:success_count",
            "refresh:skipped_count", "refresh:delete_count"
        ])
        total_queued = int(counts[0] or 0)
        success_count = int(counts[1] or 0)
        skipped_count = int(counts[2] or 0)
        delete_count = int(counts[3] or 0)

        processed_count = success_count + skipped_count

        if total_queued > 0 and processed_count >= total_queued:
            # 所有任务处理完成
            msg_parts = []
            if success_count > 0:
                msg_parts.append(f"成功处理 {success_count} 篇")
            if skipped_count > 0:
                msg_parts.append(f"跳过 {skipped_count} 篇空文档")
            if delete_count > 0:
                msg_parts.append(f"删除 {delete_count} 篇陈旧文档")

            final_message = "刷新完成。" + "，".join(msg_parts) + "。" if msg_parts else "刷新完成，数据已是最新。"
            status = {"status": "success", "message": final_message}

            # 写入最终状态并清理
            p = redis_client.pipeline()
            p.set("refresh:status", json.dumps(status), ex=300)
            p.delete("refresh:lock", "refresh:total_queued", "refresh:success_count", "refresh:skipped_count", "refresh:delete_count")
            p.execute()

            return jsonify(status)
        else:
            # 仍在处理中
            progress_msg = f"刷新中... ({processed_count}/{total_queued})"
            return jsonify({"status": "running", "message": progress_msg})

    except (ValueError, TypeError):
        return jsonify({"status": "running", "message": "正在计算..."})


@api_bp.route("/update/webhook", methods=["POST"])
def update_webhook():
    """接收 Outline Webhook，并刷新一个60秒的倒计时器。"""
    raw = request.get_data()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get("Authorization")
    if config.OUTLINE_WEBHOOK_SIGN and not rag.verify_outline_signature(raw, sig):
        return "invalid signature", 401
    if not redis_client:
        logger.warning("收到 Webhook 但 Redis 未配置，无法启动延时刷新。")
        return jsonify({"ok": False, "error": "任务队列服务未配置"}), 503
    due_time = int(time.time()) + 60
    redis_client.set("webhook:refresh_timer_due", due_time)
    logger.info("收到 Webhook，刷新计时器至 %s。", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(due_time)))
    return jsonify({"ok": True, "message": "Timer refreshed"})
