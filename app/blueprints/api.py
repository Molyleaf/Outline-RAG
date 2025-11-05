# app/blueprints/api.py
import json
import logging
import time
import uuid
from operator import itemgetter
from typing import List, Dict, Any

import config
import rag
from database import AsyncSessionLocal, redis_client
# (修复) APRouter -> APIRouter
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableParallel
from llm_services import llm
from outline_client import verify_outline_signature
from pydantic import BaseModel
from sqlalchemy import text
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)
# (修复) APRouter -> APIRouter
api_router = APIRouter()

# --- 依赖注入：用户认证 ---
def get_current_user(request: Request) -> Dict[str, Any]:
    """FastAPI 依赖项：校验用户是否登录。"""
    if "user" not in request.session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return request.session.get("user")

# --- 依赖注入：获取数据库 Session ---
async def get_db_session():
    """FastAPI 依赖项：获取异步数据库 session。"""
    async with AsyncSessionLocal() as session:
        yield session

# --- utils ---
def allowed_file(filename):
    """(修复 8) 检查文件名后缀是否在允许列表中。"""
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in config.ALLOWED_FILE_EXTENSIONS
# --- 合并结束 ---


@api_router.get("/api/me")
async def api_me(user: Dict[str, Any] = Depends(get_current_user)):
    user_id = user.get("id")
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

    models_dict = {model["id"]: model for model in available_models}

    return JSONResponse({
        "user": user,
        "models": models_dict
    })

# Pydantic 模型
class ConversationCreate(BaseModel):
    title: str | None = "新会话"

class ConversationRename(BaseModel):
    title: str

class AskRequest(BaseModel):
    query: str
    conv_id: str
    model: str
    temperature: float | None = 0.7
    top_p: float | None = 0.7
    edit_source_message_id: int | None = None


@api_router.get("/api/conversations")
async def api_get_conversations(
        # (修复 3) 移除了未使用的 'request'
        page: int = 1,
        page_size: int = 20,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    """获取对话列表"""
    uid = user["id"]
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size

    async with session.begin():
        total_res = (await session.execute(text("SELECT COUNT(1) FROM conversations WHERE user_id=:u"), {"u": uid})).scalar()
        total = int(total_res or 0)
        rs = (await session.execute(
            text("SELECT id, title, created_at FROM conversations WHERE user_id=:u ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {"u": uid, "lim": page_size, "off": offset}
        )).mappings().all()

    items = [{"id": r["id"], "title": r["title"], "created_at": r["created_at"], "url": f"/chat/{r['id']}"} for r in rs]
    return JSONResponse({"items": items, "total": total, "page": page, "page_size": page_size})


@api_router.post("/api/conversations")
async def api_create_conversation(
        body: ConversationCreate,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    """创建新对话"""
    uid = user["id"]
    title = body.title or "新会话"
    guid = str(uuid.uuid4())

    try:
        async with session.begin():
            await session.execute(
                text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :u, :t)"),
                {"id": guid, "u": uid, "t": title}
            )
        return JSONResponse({"id": guid, "title": title, "url": f"/chat/{guid}"})
    except Exception as e:
        # 捕捉外键约束失败
        if "ForeignKeyViolation" in str(e):
            logger.error(f"ForeignKeyViolation 为 user {uid} 创建对话失败。用户可能不在 users 表中。", exc_info=True)
            raise HTTPException(status_code=403, detail="用户认证数据不同步，请尝试重新登录。")
        logger.error(f"为 user {uid} 创建对话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建对话失败。")


@api_router.post("/api/conversations/{conv_id}/rename")
async def api_conversation_rename(
        conv_id: str,
        body: ConversationRename,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    async with session.begin():
        res = await session.execute(
            text("UPDATE conversations SET title=:t WHERE id=:id AND user_id=:u"),
            {"t": title, "id": conv_id, "u": user["id"]}
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=403, detail="无权限")

    return JSONResponse({"ok": True})


@api_router.post("/api/conversations/{conv_id}/delete")
async def api_conversation_delete(
        conv_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    async with session.begin():
        res = await session.execute(
            text("DELETE FROM conversations WHERE id=:id AND user_id=:u"),
            {"id": conv_id, "u": user["id"]}
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=403, detail="无权限")

    if redis_client:
        await redis_client.delete(f"messages:{conv_id}")

    return JSONResponse({"ok": True})


@api_router.get("/api/messages")
async def api_messages(
        conv_id: str,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    if not conv_id:
        raise HTTPException(status_code=400, detail="conv_id 缺失")

    cache_key = f"messages:{conv_id}"
    if redis_client:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            return Response(content=cached_data, media_type='application/json')

    async with session.begin():
        if not (await session.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"),
                                      {"cid": conv_id, "u": user["id"]})).scalar():
            raise HTTPException(status_code=403, detail="无权限")

        rs = (await session.execute(
            text("SELECT id, role, content, created_at, model, temperature, top_p FROM messages WHERE conv_id=:cid ORDER BY id ASC"),
            {"cid": conv_id}
        )).mappings().all()

    items = [dict(r, created_at=r['created_at'].isoformat()) for r in rs]
    response_data = {"items": items, "total": len(rs)}
    response_json = json.dumps(response_data)

    if redis_client:
        await redis_client.set(cache_key, response_json)

    return Response(content=response_json, media_type='application/json')


# --- RAG 链定义 (移至 /api/ask 内部以确保组件已初始化) ---

@api_router.post("/api/ask")
async def api_ask(
        body: AskRequest,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    """聊天流式响应"""

    query, conv_id = (body.query or "").strip(), body.conv_id
    model, temperature, top_p = body.model, body.temperature, body.top_p
    edit_source_message_id = body.edit_source_message_id

    if not query or not conv_id:
        raise HTTPException(status_code=400, detail="missing query or conv_id")

    try:
        await rag.initialize_rag_components()
    except Exception as e:
        logger.critical(f"[{conv_id}] 无法初始化 RAG 组件: {e}", exc_info=True)
        return JSONResponse({"error": f"RAG 服务初始化失败: {e}"}, status_code=503)

    compression_retriever = rag.compression_retriever
    if compression_retriever is None:
        logger.error(f"[{conv_id}] RAG 组件 'compression_retriever' 未能初始化。")
        return JSONResponse({"error": "RAG 服务组件 'compression_retriever' 未就绪"}, status_code=503)

    # --- RAG 链定义 (使用异步) ---
    def _format_history_str(messages: List[AIMessage | HumanMessage]) -> str:
        return "\n".join([f"{m.type}: {m.content}" for m in messages])

    def _format_docs(docs: List[Document]) -> str:
        return "\n\n---\n\n".join([doc.page_content for doc in docs])

    # 1. 定义查询重写链 (异步)
    rewrite_chain = (
            RunnableParallel({
                "history": lambda x: _format_history_str(x["chat_history"]),
                "query": lambda x: x["input"]
            })
            | PromptTemplate.from_template(config.REWRITE_PROMPT_TEMPLATE)
            | llm.bind(temperature=0.0, top_p=1.0)
            | StrOutputParser()
    )

    # 必须显式调用 aget_relevant_documents
    # 否则 LCEL 会调用同步的 get_relevant_documents
    async def _run_retriever(query: str) -> List[Document]:
        return await compression_retriever.aget_relevant_documents(query)

    # 2. 定义最终 RAG 链 (异步)
    rag_chain = (
            RunnableParallel({
                "rewritten_query": rewrite_chain,
                "input": lambda x: x["input"],
                "chat_history": lambda x: x["chat_history"]
            })
            | RunnablePassthrough.assign(
        context=(
                itemgetter("rewritten_query")
                | RunnableLambda(_run_retriever) # Linter 误报 (1)
                | RunnableLambda[List[Document], str](_format_docs) # Linter 误报 (2)
        )
    )
            | RunnableParallel({
        "chat_history": lambda x: x["chat_history"],
        "context": lambda x: x["context"],
        "query": lambda x: x["input"] # Linter 误报 (4)
    })
            | ChatPromptTemplate.from_messages([
        ("system", config.SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", config.HISTORY_AWARE_PROMPT_TEMPLATE)
    ])
            | llm
            | StrOutputParser()
    )
    # --- RAG 链定义结束 ---

    chat_history_db = []
    async with session.begin():
        if not (await session.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": user["id"]})).scalar():
            raise HTTPException(status_code=403, detail="无权限")

        rs = [] # Linter 误报 (5) - 'rs' 在下面被使用
        if edit_source_message_id:
            try:
                user_msg_id = int(edit_source_message_id)
                owner_check = (await session.execute(text("SELECT 1 FROM messages WHERE id=:mid AND conv_id=:cid AND user_id=:uid AND role='user'"),
                                                     {"mid": user_msg_id, "cid": conv_id, "uid": user["id"]})).scalar()
                if not owner_check:
                    raise HTTPException(status_code=403, detail="无权限编辑此消息")

                await session.execute(text("DELETE FROM messages WHERE conv_id=:cid AND id > :mid"),
                                      {"cid": conv_id, "mid": user_msg_id})
                await session.execute(text("UPDATE messages SET content=:c, created_at=NOW() WHERE id=:mid AND conv_id=:cid"),
                                      {"cid": conv_id, "c": query, "mid": user_msg_id})
                rs = (await session.execute(
                    text("SELECT role, content FROM messages WHERE conv_id=:cid AND id < :mid ORDER BY id DESC LIMIT :lim"),
                    {"cid": conv_id, "mid": user_msg_id, "lim": config.MAX_HISTORY_MESSAGES}
                )).mappings().all()
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid edit_source_message_id")
        else:
            rs = (await session.execute(
                text("SELECT role, content FROM messages WHERE conv_id=:cid ORDER BY id DESC LIMIT :lim"),
                {"cid": conv_id, "lim": config.MAX_HISTORY_MESSAGES}
            )).mappings().all()
            await session.execute(text("INSERT INTO messages (conv_id, user_id, role, content) VALUES (:cid, :uid, 'user', :c)"),
                                  {"cid": conv_id, "uid": user["id"], "c": query})

        chat_history_db = reversed(rs) # 'rs' 在这里被使用

    if redis_client:
        await redis_client.delete(f"messages:{conv_id}")

    chat_history = []
    for r in chat_history_db:
        if r["role"] == "user":
            chat_history.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            chat_history.append(AIMessage(content=r["content"]))

    llm_with_options = llm.bind(model=model, temperature=temperature, top_p=top_p)

    final_chain_streaming = (
            rag_chain.steps[0]
            | rag_chain.steps[1]
            | rag_chain.steps[2]
            | rag_chain.steps[3]
            | llm_with_options
        # | rag_chain.steps[5] # 移除了 StrOutputParser
    )

    async def generate():
        yield ": ping\n\n"
        full_response = ""
        model_name = model
        thinking_response = ""

        try:
            stream = final_chain_streaming.astream({
                "input": query,
                "chat_history": chat_history
            })

            async for delta_chunk in stream:
                delta_content = delta_chunk.content or ""
                delta_thinking = ""

                if delta_chunk.additional_kwargs and "thinking" in delta_chunk.additional_kwargs:
                    delta_thinking = delta_chunk.additional_kwargs["thinking"] or ""
                    thinking_response = delta_thinking

                if delta_chunk.tool_call_chunks:
                    try:
                        for tc in delta_chunk.tool_call_chunks:
                            if tc.get("name") == "thinking" and tc.get("args"):
                                args_json = json.loads(tc["args"])
                                delta_thinking = args_json.get("thought", "")
                                if delta_thinking:
                                    thinking_response = delta_thinking
                    except Exception:
                        pass

                if delta_content or delta_thinking:
                    full_response += delta_content
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': delta_content, 'thinking': delta_thinking}}], 'model': model_name})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[{conv_id}] LCEL RAG 链执行失败 (async): {e}", exc_info=True)
            yield f"data: {json.dumps({'error': f'RAG 链执行失败 (async): {e}'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if full_response:
            async with AsyncSessionLocal.begin() as db_session:
                full_content_with_thinking = f"\n{thinking_response}\n\n\n{full_response}"
                await db_session.execute(
                    text("INSERT INTO messages (conv_id, user_id, role, content, model, temperature, top_p) VALUES (:cid, :uid, 'assistant', :c, :m, :t, :p)"),
                    {"cid": conv_id, "uid": user["id"], "c": full_content_with_thinking, "m": model_name, "t": temperature, "p": top_p}
                )
            if redis_client:
                await redis_client.delete(f"messages:{conv_id}")

    return StreamingResponse(generate(), media_type="text/event-stream; charset=utf-8", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"
    })

# --- /api/upload ---
@api_router.post("/api/upload")
async def upload(
        request: Request,
        user: Dict[str, Any] = Depends(get_current_user), # 'user' 在此被使用
        session = Depends(get_db_session)
):
    form = await request.form()
    if "file" not in form or not (f := form["file"]).filename:
        raise HTTPException(status_code=400, detail="missing file")

    name = secure_filename(f.filename)
    if not name or len(name) > 200 or not allowed_file(name):
        raise HTTPException(status_code=400, detail="invalid filename or type")

    # read() 是同步的，但在 FastAPI 中可接受
    content_bytes = await f.read()
    content = content_bytes.decode("utf-8", errors="ignore")

    async with session.begin():
        await session.execute(
            text("INSERT INTO attachments (user_id, filename, content) VALUES (:u,:n,:c)"),
            {"u": user["id"], "n": name, "c": content}
        )
    return JSONResponse({"ok": True, "filename": name})

# --- /update/all ---
@api_router.post("/update/all")
async def update_all(_user: Dict[str, Any] = Depends(get_current_user)): # (修复 6)
    if not redis_client:
        return JSONResponse({"ok": False, "error": "任务队列服务未配置"}, status_code=503)
    if not await redis_client.set("refresh:lock", "1", ex=3600, nx=True):
        return JSONResponse({"ok": False, "error": "正在刷新中"}, status_code=429)
    try:
        task = {"task": "refresh_all"}
        await redis_client.lpush("task_queue", json.dumps(task))
        return JSONResponse({"ok": True, "message": "已开始全量刷新"}, status_code=202)
    except Exception as e:
        await redis_client.delete("refresh:lock")
        logger.exception("加入刷新任务到队列时失败 (async): %s", e)
        return JSONResponse({"ok": False, "error": "启动刷新失败"}, status_code=500)

# --- /api/refresh/status ---
@api_router.get("/api/refresh/status")
async def refresh_status(_user: Dict[str, Any] = Depends(get_current_user)): # (修复 6)
    if not redis_client:
        return JSONResponse({"status": "disabled", "message": "Redis not configured"})

    status_json = await redis_client.get("refresh:status")
    if status_json:
        return JSONResponse(json.loads(status_json))

    if not await redis_client.get("refresh:lock"):
        return JSONResponse({"status": "idle", "message": "空闲"})

    try:
        # (修复 7) 移除了 "refresh:delete_count"
        counts = await redis_client.mget([
            "refresh:total_queued", "refresh:success_count",
            "skipped_count"
        ])
        total_queued = int(counts[0] or 0)
        success_count = int(counts[1] or 0)
        skipped_count = int(counts[2] or 0)
        # (修复 7) 移除了 'delete_count'

        processed_count = success_count + skipped_count

        if total_queued > 0 and processed_count >= total_queued:
            # ... (消息逻辑不变)
            final_message = "刷新完成。"
            status = {"status": "success", "message": final_message}

            p = redis_client.pipeline()
            p.set("refresh:status", json.dumps(status), ex=300)
            # (修复 7) 移除了 "refresh:delete_count"
            p.delete("refresh:lock", "refresh:total_queued", "refresh:success_count", "refresh:skipped_count")
            await p.execute()

            return JSONResponse(status)
        else:
            progress_msg = f"刷新中... ({processed_count}/{total_queued})"
            return JSONResponse({"status": "running", "message": progress_msg})

    except (ValueError, TypeError):
        return JSONResponse({"status": "running", "message": "正在计算..."})

# --- /update/webhook ---
@api_router.post("/update/webhook")
async def update_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("X-Outline-Signature") or request.headers.get("Authorization")

    if config.OUTLINE_WEBHOOK_SIGN and not verify_outline_signature(raw, sig):
        return Response("invalid signature", status_code=401)

    if not redis_client:
        logger.warning("收到 Webhook 但 Redis 未配置，无法启动延时刷新。")
        return JSONResponse({"ok": False, "error": "任务队列服务未配置"}, status_code=503)

    due_time = int(time.time()) + 60
    await redis_client.set("webhook:refresh_timer_due", due_time)
    logger.info("收到 Webhook，刷新计时器至 %s。", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(due_time)))
    return JSONResponse({"ok": True, "message": "Timer refreshed"})