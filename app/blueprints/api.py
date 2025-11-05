# app/blueprints/api.py
import json
import logging
import time
import uuid
from typing import List

import config
from database import engine, redis_client
from flask import (Blueprint, jsonify, request, abort, make_response, Response, session)
from langchain_core.documents import Document
from operator import itemgetter as itemgetter
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableParallel
from sqlalchemy import text
from werkzeug.utils import secure_filename

from llm_services import llm
from outline_client import verify_outline_signature
from rag import compression_retriever

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

# --- (不变) utils.py 合并于此 ---
def require_login():
    """校验用户是否登录，否则中止请求。"""
    if "user" not in session:
        abort(401)

def current_user():
    """获取当前登录的用户信息。"""
    return session.get("user")

def allowed_file(filename):
    """检查文件名后缀是否在允许列表中。"""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in config.ALLOWED_FILE_EXTENSIONS
# --- 合并结束 ---


@api_bp.route("/api/me")
def api_me():
    require_login()

    # --- (新) 加载和过滤模型列表 ---
    user_id = current_user().get("id")
    auth_user_ids = set(uid.strip() for uid in config.BETA_AUTHORIZED_USER_IDS.split(",") if uid.strip())

    try:
        all_models = json.loads(config.CHAT_MODELS_JSON)
    except json.JSONDecodeError:
        logger.error("CHAT_MODELS_JSON 环境变量格式错误，将返回空模型列表。")
        all_models = []

    available_models = []
    for model in all_models:
        is_beta = model.get("beta", False)
        if not is_beta or (is_beta and user_id in auth_user_ids):
            available_models.append(model)

    # 转换列表为前端期望的字典格式 (keyed by id)
    models_dict = {model["id"]: model for model in available_models}

    # 返回用户信息和过滤后的模型列表
    return jsonify({
        "user": current_user(),
        "models": models_dict
    })

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

# --- (核心 RAG 链) ---

def _format_history_str(messages: List[AIMessage | HumanMessage]) -> str:
    return "\n".join([f"{m.type}: {m.content}" for m in messages])

def _format_docs(docs: List[Document]) -> str:
    return "\n\n---\n\n".join([doc.page_content for doc in docs])

# 1. 定义查询重写链
rewrite_chain = (
        RunnableParallel({
            "history": lambda x: _format_history_str(x["chat_history"]),
            "query": lambda x: x["input"]
        })
        | PromptTemplate.from_template(config.REWRITE_PROMPT_TEMPLATE)
        | llm.bind(temperature=0.0, top_p=1.0)
        | StrOutputParser()
)

# 2. 定义最终 RAG 链
rag_chain = (
    # 修复：显式使用 RunnableParallel
        RunnableParallel({
            "rewritten_query": rewrite_chain,
            "input": lambda x: x["input"],
            "chat_history": lambda x: x["chat_history"]
        })
        | RunnablePassthrough.assign(
    context=(
            RunnableLambda(itemgetter("rewritten_query"))
            | compression_retriever
            | RunnableLambda[List[Document], str](_format_docs)
    )
)
        | RunnableParallel({
            "chat_history": lambda x: x["chat_history"],
            "context": lambda x: x["context"],
            "query": lambda x: x["input"]
        })
        | ChatPromptTemplate.from_messages([
    ("system", config.SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    ("user", config.HISTORY_AWARE_PROMPT_TEMPLATE)
])
        | llm
        | StrOutputParser()
)


@api_bp.route("/api/ask", methods=["POST"])
def api_ask():
    require_login()
    body = request.get_json(force=True)
    query, conv_id = (body.get("query") or "").strip(), body.get("conv_id")
    model = body.get("model")
    temperature = body.get("temperature")
    top_p = body.get("top_p")

    # (新) 获取编辑ID
    edit_source_message_id = body.get("edit_source_message_id")

    if not query or not conv_id:
        return jsonify({"error":"missing query or conv_id"}), 400

    chat_history_db = []
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": current_user()["id"]}).scalar():
            abort(403)

        rs = []

        if edit_source_message_id:
            # (新) 编辑逻辑
            try:
                user_msg_id = int(edit_source_message_id)
                # 确保此消息是用户自己的
                owner_check = conn.execute(text("SELECT 1 FROM messages WHERE id=:mid AND conv_id=:cid AND user_id=:uid AND role='user'"),
                                           {"mid": user_msg_id, "cid": conv_id, "uid": current_user()["id"]}).scalar()
                if not owner_check:
                    # 如果消息不属于该用户或不是 'user' 角色，则中止
                    abort(403)

                # 删除此消息之后的所有消息 (AI的回复)
                conn.execute(text("DELETE FROM messages WHERE conv_id=:cid AND id > :mid"),
                             {"cid": conv_id, "mid": user_msg_id})
                # 更新此消息的内容
                conn.execute(text("UPDATE messages SET content=:c, created_at=NOW() WHERE id=:mid AND conv_id=:cid"),
                             {"cid": conv_id, "c": query, "mid": user_msg_id})
                # 获取此消息之前的所有历史
                rs = conn.execute(
                    text("SELECT role, content FROM messages WHERE conv_id=:cid AND id < :mid ORDER BY id DESC LIMIT :lim"),
                    {"cid": conv_id, "mid": user_msg_id, "lim": config.MAX_HISTORY_MESSAGES}
                ).mappings().all()
            except (ValueError, TypeError):
                abort(400, "Invalid edit_source_message_id")

        else:
            # (旧) 新增逻辑
            rs = conn.execute(
                text("SELECT role, content FROM messages WHERE conv_id=:cid ORDER BY id DESC LIMIT :lim"),
                {"cid": conv_id, "lim": config.MAX_HISTORY_MESSAGES}
            ).mappings().all()
            # 插入新
            conn.execute(text("INSERT INTO messages (conv_id, user_id, role, content) VALUES (:cid, :uid, 'user', :c)"),
                         {"cid": conv_id, "uid": current_user()["id"], "c": query})

        chat_history_db = reversed(rs)

    if redis_client:
        redis_client.delete(f"messages:{conv_id}")

    chat_history = []
    for r in chat_history_db:
        if r["role"] == "user":
            chat_history.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            chat_history.append(AIMessage(content=r["content"]))

    llm_with_options = llm.bind(
        model=model,
        temperature=temperature,
        top_p=top_p
    )

    # (新) RAG 链 (移除末尾 StrOutputParser 以便处理 thinking)
    final_chain_streaming = (
            rag_chain.steps[0]
            | rag_chain.steps[1]
            | rag_chain.steps[2]
            | rag_chain.steps[3]
            | llm_with_options
        # | rag_chain.steps[5] # 移除了 StrOutputParser
    )


    def generate():
        yield ": ping\n\n"
        full_response = ""
        model_name = model
        thinking_response = "" # (新) 存储 thinking 内容

        try:
            # (新) 使用移除 StrOutputParser 的链
            stream = final_chain_streaming.stream({
                "input": query,
                "chat_history": chat_history
            })

            for delta_chunk in stream:
                # delta_chunk 是一个 AIMessageChunk
                delta_content = delta_chunk.content or ""
                delta_thinking = ""

                # (新) 尝试获取 'thinking' (Qwen/Qwen3-235B-A22B-Thinking-2507)
                if delta_chunk.additional_kwargs and "thinking" in delta_chunk.additional_kwargs:
                    # 这是一个中间状态，不断被覆盖
                    delta_thinking = delta_chunk.additional_kwargs["thinking"] or ""
                    thinking_response = delta_thinking # 存储最后/最新的 thinking

                # (新) 尝试获取 'tool_calls' (Qwen/Qwen3-Next)
                if delta_chunk.tool_call_chunks:
                    try:
                        for tc in delta_chunk.tool_call_chunks:
                            if tc.get("name") == "thinking" and tc.get("args"):
                                # 假设 args 是一个 JSON 字符串
                                args_json = json.loads(tc["args"])
                                delta_thinking = args_json.get("thought", "")
                                if delta_thinking:
                                    thinking_response = delta_thinking # 存储
                    except Exception:
                        pass # 解析失败则忽略

                # (新) 仅在有内容或 thinking 时发送数据
                if delta_content or delta_thinking:
                    full_response += delta_content # 只有 content 计入最终回复
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': delta_content, 'thinking': delta_thinking}}], 'model': model_name})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[{conv_id}] LCEL RAG 链执行失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': f'RAG 链执行失败: {e}'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if full_response:
            with engine.begin() as conn:
                # (新) 将 thinking 内容和 user_id 添加到 assistant 消息
                full_content_with_thinking = f"<!-- THINKING -->\n{thinking_response}\n\n<!-- CONTENT -->\n{full_response}"
                conn.execute(
                    text("INSERT INTO messages (conv_id, user_id, role, content, model, temperature, top_p) VALUES (:cid, :uid, 'assistant', :c, :m, :t, :p)"),
                    {"cid": conv_id, "uid": current_user()["id"], "c": full_content_with_thinking, "m": model_name, "t": temperature, "p": top_p}
                )
            if redis_client:
                redis_client.delete(f"messages:{conv_id}")

    resp = make_response(generate(), 200)
    resp.mimetype = "text/event-stream; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

# --- (不变) /api/upload ---
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
    return jsonify({"ok": True, "filename": name})

# --- (不变) /update/all ---
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

# --- (不变) /api/refresh/status ---
@api_bp.route("/api/refresh/status", methods=["GET"])
def refresh_status():
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
            "skipped_count", "refresh:delete_count"
        ])
        total_queued = int(counts[0] or 0)
        success_count = int(counts[1] or 0)
        skipped_count = int(counts[2] or 0)
        delete_count = int(counts[3] or 0)

        processed_count = success_count + skipped_count

        if total_queued > 0 and processed_count >= total_queued:
            msg_parts = []
            if success_count > 0:
                msg_parts.append(f"成功处理 {success_count} 篇")
            if skipped_count > 0:
                msg_parts.append(f"跳过 {skipped_count} 篇空文档")
            if delete_count > 0:
                msg_parts.append(f"删除 {delete_count} 篇陈旧文档")

            final_message = "刷新完成。" + "，".join(msg_parts) + "。" if msg_parts else "刷新完成，数据已是最新。"
            status = {"status": "success", "message": final_message}

            p = redis_client.pipeline()
            p.set("refresh:status", json.dumps(status), ex=300)
            p.delete("refresh:lock", "refresh:total_queued", "refresh:success_count", "refresh:skipped_count", "refresh:delete_count")
            p.execute()

            return jsonify(status)
        else:
            progress_msg = f"刷新中... ({processed_count}/{total_queued})"
            return jsonify({"status": "running", "message": progress_msg})

    except (ValueError, TypeError):
        return jsonify({"status": "running", "message": "正在计算..."})

# --- (不变) /update/webhook ---
@api_bp.route("/update/webhook", methods=["POST"])
def update_webhook():
    raw = request.get_data()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get("Authorization")

    if config.OUTLINE_WEBHOOK_SIGN and not verify_outline_signature(raw, sig):
        return "invalid signature", 401

    if not redis_client:
        logger.warning("收到 Webhook 但 Redis 未配置，无法启动延时刷新。")
        return jsonify({"ok": False, "error": "任务队列服务未配置"}), 503

    due_time = int(time.time()) + 60
    redis_client.set("webhook:refresh_timer_due", due_time)
    logger.info("收到 Webhook，刷新计时器至 %s。", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(due_time)))
    return jsonify({"ok": True, "message": "Timer refreshed"})