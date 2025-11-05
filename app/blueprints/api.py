# app/blueprints/api.py
import json
import logging
import time
import uuid
from typing import List

from flask import (Blueprint, jsonify, request, abort, make_response, Response)
from sqlalchemy import text
from werkzeug.utils import secure_filename

# --- LangChain ---
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

import config
from database import engine, redis_client
from utils import require_login, current_user, allowed_file

# --- (新) 导入 LangChain 和 Outline 服务 ---
from app.llm_services import llm
from app.rag import compression_retriever
from app.outline_client import verify_outline_signature

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__)

# --- (不变) /api/me ---
@api_bp.route("/api/me")
def api_me():
    require_login()
    return jsonify(current_user())

# --- (不变) /api/conversations (GET, POST) ---
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

# --- (不变) /api/conversations/<id>/rename ---
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

# --- (不变) /api/conversations/<id>/delete ---
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

# --- (不变) /api/messages ---
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

# --- (重写) /api/ask (核心 RAG 链) ---

def _format_history_str(messages: List[AIMessage | HumanMessage]) -> str:
    """辅助函数：将 LangChain 消息列表格式化为重写提示词所需的字符串。"""
    return "\n".join([f"{m.type}: {m.content}" for m in messages])

def _format_docs(docs: List[Document]) -> str:
    """辅助函数：将检索到的文档格式化为上下文字符串。"""
    return "\n\n---\n\n".join([doc.page_content for doc in docs])

# 1. 定义查询重写链 (复刻 api.py 逻辑)
#    输入: {"chat_history": List[Message], "input": str}
#    输出: str (重写的查询)
rewrite_chain = (
        {
            "history": lambda x: _format_history_str(x["chat_history"]),
            "query": lambda x: x["input"]
        }
        | PromptTemplate.from_template(config.REWRITE_PROMPT_TEMPLATE)
        | llm.bind(temperature=0.0, top_p=1.0) # 使用确定性设置
        | StrOutputParser()
)

# 2. 定义最终 RAG 链 (复刻 api.py 逻辑)
#    输入: {"chat_history": List[Message], "input": str}
#    输出: str (最终答案)
rag_chain = (
    # 1. 并行执行：
    #    - 运行重写链以获取 rewritten_query
    #    - 传递原始 input (用于最终提示词)
    #    - 传递原始 chat_history (用于最终提示词)
        {
            "rewritten_query": rewrite_chain,
            "input": lambda x: x["input"],
            "chat_history": lambda x: x["chat_history"]
        }
        # 2. 使用 rewritten_query 调用检索器 (Reranker)
        #    并将结果 (文档) 添加到 "context" 键
        | RunnablePassthrough.assign(
    context=lambda x: _format_docs(compression_retriever.invoke(x["rewritten_query"]))
)
        # 3. 构建最终提示词
        #    - 传递 chat_history
        #    - 传递 context (来自上一步)
        #    - 传递 query (使用原始 input)
        | {
            "chat_history": lambda x: x["chat_history"],
            "context": lambda x: x["context"],
            "query": lambda x: x["input"]
        }
        | ChatPromptTemplate.from_messages([
    ("system", config.SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    ("user", config.HISTORY_AWARE_PROMPT_TEMPLATE)
])
        # 4. 调用 LLM 并解析输出
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

    if not query or not conv_id:
        return jsonify({"error":"missing query or conv_id"}), 400

    chat_history_db = []
    with engine.begin() as conn:
        # 验证会话所有权 (不变)
        if not conn.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": current_user()["id"]}).scalar():
            abort(403)
        # 1. (不变) 获取历史消息
        rs = conn.execute(
            text("SELECT role, content FROM messages WHERE conv_id=:cid ORDER BY id DESC LIMIT :lim"),
            {"cid": conv_id, "lim": config.MAX_HISTORY_MESSAGES}
        ).mappings().all()
        chat_history_db = reversed(rs) # (旧 -> 新)
        # 2. (不变) 保存当前用户消息
        conn.execute(text("INSERT INTO messages (conv_id, role, content) VALUES (:cid,'user',:c)"), {"cid": conv_id, "c": query})

    # (不变) 清理消息缓存
    if redis_client:
        redis_client.delete(f"messages:{conv_id}")

    # (新) 格式化历史消息为 LangChain 对象
    chat_history = []
    for r in chat_history_db:
        if r["role"] == "user":
            chat_history.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            chat_history.append(AIMessage(content=r["content"]))

    # (新) 绑定前端传入的 LLM 参数
    llm_with_options = llm.bind(
        model=model,
        temperature=temperature,
        top_p=top_p
    )
    # (新) 覆盖 RAG 链中的最后一个 llm (回答者)
    final_chain = rag_chain.with_config({"configurable": {"llm": llm_with_options}})

    # (新) .with_config 比较复杂，我们使用 .assign 动态替换
    # (这需要 llm_answer 在 chain 定义时是一个 RunnablePassthrough)
    # 为简单起见，我们直接重新绑定链的最后一步

    final_chain = (
            rag_chain.steps[0] # {rewritten_query, input, chat_history}
            | rag_chain.steps[1] # assign(context=...)
            | rag_chain.steps[2] # {chat_history, context, query}
            | rag_chain.steps[3] # FINAL_PROMPT
            | llm_with_options   # <-- (新) 替换的 LLM
            | rag_chain.steps[5] # StrOutputParser
    )


    def generate():
        yield ": ping\n\n"
        full_response = ""
        model_name = model # 默认为前端所选

        try:
            # (新) 使用 LCEL 链的 .stream()
            stream = final_chain.stream({
                "input": query,
                "chat_history": chat_history
            })

            for delta in stream:
                if delta:
                    full_response += delta
                    # (不变) 构造与前端兼容的 SSE 响应
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': delta}}], 'model': model_name})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[{conv_id}] LCEL RAG 链执行失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': f'RAG 链执行失败: {e}'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if full_response:
            # (不变) 保存助手消息
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
    # (原版也未实现) 此处 upsert_one_doc 逻辑需要实现
    return jsonify({"ok": True, "filename": name})

# --- (修改) /update/all ---
@api_bp.route("/update/all", methods=["POST"])
def update_all():
    require_login()
    if not redis_client:
        return jsonify({"ok": False, "error": "任务队列服务未配置"}), 503
    if not redis_client.set("refresh:lock", "1", ex=3600, nx=True):
        return jsonify({"ok": False, "error": "正在刷新中"}), 429
    try:
        # (新) 导入重构后的 rag 任务
        import rag
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
            "refresh:skipped_count", "refresh:delete_count"
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

# --- (修改) /update/webhook ---
@api_bp.route("/update/webhook", methods=["POST"])
def update_webhook():
    raw = request.get_data()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get("Authorization")

    # (新) 从 outline_client 导入验证函数
    if config.OUTLINE_WEBHOOK_SIGN and not verify_outline_signature(raw, sig):
        return "invalid signature", 401

    if not redis_client:
        logger.warning("收到 Webhook 但 Redis 未配置，无法启动延时刷新。")
        return jsonify({"ok": False, "error": "任务队列服务未配置"}), 503

    due_time = int(time.time()) + 60
    redis_client.set("webhook:refresh_timer_due", due_time)
    logger.info("收到 Webhook，刷新计时器至 %s。", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(due_time)))
    return jsonify({"ok": True, "message": "Timer refreshed"})