# app/blueprints/api.py
import asyncio
import json
import logging
import time
import uuid
from operator import itemgetter
from typing import List, Dict, Any
import re

import config
import rag
from database import AsyncSessionLocal, redis_client
from llm_services import llm
from outline_client import verify_outline_signature
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableParallel, RunnableBranch, RunnableLambda
from pydantic import BaseModel
from sqlalchemy import text
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)
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

# --- (新) Req 5: 溯源格式化函数 ---
def _format_docs_with_metadata(docs: List[Document]) -> str:
    """
    将文档列表格式化为带元数据（标题、来源URL）的字符串，用于 RAG 提示词。
    """
    formatted_docs = []
    base_url = config.OUTLINE_API_URL.replace("/api", "")

    for i, doc in enumerate(docs):
        # (*** 修复：现在 docs 是父文档，元数据在 metadata 属性中 ***)
        title = doc.metadata.get("title", "Untitled")
        url = doc.metadata.get("url")

        doc_str = f"--- 参考资料 [{i+1}] ---\n"
        doc_str += f"标题: {title}\n"

        if url:
            if url.startswith('/'):
                url = f"{base_url}{url}"
            doc_str += f"来源: {url}\n"

        doc_str += f"内容: {doc.page_content}\n"
        formatted_docs.append(doc_str)

    if not formatted_docs:
        return "未找到相关参考资料。"

    return "\n\n".join(formatted_docs)

# (*** 新增辅助函数：用于获取父文档 ***)
async def _get_reranked_parent_docs(query: str) -> List[Document]:
    """
    异步检索链，执行 块检索 -> 块重排 -> 父文档获取
    """
    # 1. 使用 rag.compression_retriever (已在 rag.py 中配置为 rerank chunks)
    #    获取 Top K (6) 个最相关的 *块*
    if not rag.compression_retriever or not rag.parent_store:
        logger.error("RAG components (compression_retriever or parent_store) not initialized.")
        return []

    try:
        # (调用公共的 *sync* 方法，并用 to_thread 包装)
        # 这避免了调用 internal _aget_relevant_documents (需要 run_manager)
        # 也避开了 public aget_relevant_documents (在 classic 包中可能缺失)
        reranked_chunks = await asyncio.to_thread(
            rag.compression_retriever.get_relevant_documents,
            query
        )
    except Exception as e:
        logger.error(f"Failed during chunk retrieval/reranking: {e}", exc_info=True)
        return []

    # 2. 从块中提取父文档 ID (保持顺序并去重)
    parent_ids = []
    seen_ids = set()
    for chunk in reranked_chunks:
        source_id = chunk.metadata.get("source_id")
        if source_id and source_id not in seen_ids:
            parent_ids.append(source_id)
            seen_ids.add(source_id)

    if not parent_ids:
        logger.warning(f"Reranked chunks found, but no source_ids. Query: {query}")
        return []

    # 3. 从 ParentStore (SQLStore) 异步获取唯一的父文档
    #    rag.parent_store.amget() 是异步的
    try:
        parent_docs = await rag.parent_store.amget(parent_ids)

        # 过滤掉 None (以防万一) 并保持顺序
        final_docs = [doc for doc in parent_docs if doc is not None]
        return final_docs
    except Exception as e:
        logger.error(f"Failed to amget parent docs ({parent_ids}) from store: {e}", exc_info=True)
        return []

# --- utils ---
def allowed_file(filename):
    """检查文件名后缀是否在允许列表中。"""
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in config.ALLOWED_FILE_EXTENSIONS

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

    items = [{"id": r["id"], "title": r["title"], "created_at": r['created_at'].isoformat(), "url": f"/chat/{r['id']}"} for r in rs]
    return JSONResponse({"items": items, "total": total, "page": page, "page_size": page_size})


@api_router.post("/api/conversations")
async def api_create_conversation(
        body: ConversationCreate,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    """创建新对话"""
    uid = user["id"]
    name = user.get("name")
    avatar_url = user.get("avatar_url")
    title = body.title or "新会话"
    guid = str(uuid.uuid4())

    try:
        async with session.begin():
            # --- (修复 3) 修复：外键约束错误 ---
            # 在插入 conversation 之前，确保 user 存在于 users 表中
            await session.execute(
                text("""
                     INSERT INTO users (id, name, avatar_url)
                     VALUES (:id, :name, :avatar_url)
                         ON CONFLICT (id) DO UPDATE SET
                         name = EXCLUDED.name,
                                                 avatar_url = EXCLUDED.avatar_url
                     """),
                {"id": uid, "name": name, "avatar_url": avatar_url}
            )
            # --- 修复结束 ---

            await session.execute(
                text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :u, :t)"),
                {"id": guid, "u": uid, "t": title}
            )
        return JSONResponse({"id": guid, "title": title, "url": f"/chat/{guid}"})
    except Exception as e:
        if "ForeignKeyViolation" in str(e) or "foreign key constraint" in str(e):
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

    # (*** 修复：现在 compression_retriever 返回 *块* ***)
    # (*** parent_store 用于手动获取父文档 ***)
    compression_retriever = rag.compression_retriever
    if compression_retriever is None or rag.parent_store is None:
        logger.error(f"[{conv_id}] RAG 组件 'compression_retriever' 或 'parent_store' 未能初始化。")
        return JSONResponse({"error": "RAG 服务组件 'compression_retriever' 或 'parent_store' 未就绪"}, status_code=503)

    # --- LCEL 链定义 ---

    # 修复：根据模型名称动态添加 reasoning=True
    # 参考: https://docs.siliconflow.cn/cn/userguide/capabilities/reasoning
    llm_params = {
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
        "stream": True
    }

    # 仅当模型名称包含 "thinking" (不区分大小写) 时，才启用 include_reasoning
    if "thinking" in model.lower():
        llm_params["stream_options"] = {"include_reasoning": True}

    llm_with_options = llm.bind(**llm_params)

    # 分类器（用于路由）不需要 reasoning
    classifier_llm = llm.bind(temperature=0.0, top_p=1.0)

    # 1. 查询重写链
    def _format_history_str(messages: List[AIMessage | HumanMessage]) -> str:
        return "\n".join([f"{m.type}: {m.content}" for m in messages])

    rewrite_chain = (
            RunnableParallel({
                "history": lambda x: _format_history_str(x["chat_history"]),
                "query": lambda x: x["input"]
            })
            | PromptTemplate.from_template(config.REWRITE_PROMPT_TEMPLATE)
            | classifier_llm
            | StrOutputParser()
    )


    # 3. 核心 RAG 链 (*** 新架构 ***)
    # <--- 2. 将异步函数包装为 RunnableLambda
    get_docs_runnable = RunnableLambda(_get_reranked_parent_docs)

    rag_chain_pre_llm = (
            RunnableParallel({
                "rewritten_query": rewrite_chain,
                "input": lambda x: x["input"],
                "chat_history": lambda x: x["chat_history"]
            })
            # (*** 修复 ***)
            # 1. 将重写后的查询传递给新的异步函数 _get_reranked_parent_docs
            #    它处理: 块检索 (k=12) -> 块重排 (k=6) -> 父文档获取
            | RunnablePassthrough.assign(
        # <--- 3. 在管道中使用包装后的 RunnableLambda
        docs=itemgetter("rewritten_query") | get_docs_runnable
    )
            # 2. 格式化父文档
            | RunnablePassthrough.assign(
        context=lambda x: _format_docs_with_metadata(x["docs"])
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
    )

    rag_chain = rag_chain_pre_llm | llm_with_options

    # 4. 智能路由 (不变)
    classifier_prompt = PromptTemplate.from_template(
        """判断用户问题的类型。只回答 'rag' (需要知识库)、'greeting' (问候) 或 'other' (其他)。
问题: {input}
类型:"""
    )
    classifier_chain = (
            classifier_prompt
            | classifier_llm
            | StrOutputParser()
    )

    greeting_chain = (
            PromptTemplate.from_template("你是一个友好的助手。请回复用户的问候。")
            | llm_with_options
    )

    general_chain = (
            ChatPromptTemplate.from_messages([
                ("system", config.SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="chat_history"),
                ("user", "{input}")
            ])
            | llm_with_options
    )

    chain_with_classification = RunnablePassthrough.assign(
        classification=classifier_chain
    )

    final_chain_streaming = chain_with_classification | RunnableBranch(
        (lambda x: "greeting" in x["classification"].lower(), greeting_chain),
        (lambda x: "rag" in x["classification"].lower(), rag_chain),
        general_chain
    )
    # --- RAG 链定义结束 ---

    chat_history_db = []
    async with session.begin():
        if not (await session.execute(text("SELECT 1 FROM conversations WHERE id=:cid AND user_id=:u"), {"cid": conv_id, "u": user["id"]})).scalar():
            raise HTTPException(status_code=403, detail="无权限")

        rs = []
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

        chat_history_db = reversed(rs)

    if redis_client:
        await redis_client.delete(f"messages:{conv_id}")

    chat_history = []
    for r in chat_history_db:
        if r["role"] == "user":
            chat_history.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            content = r["content"]
            # 适配前端的 \n\n\n 分隔符
            thinking_match = re.search(r"\n(.*?)\n\n\n(.*)", content, re.DOTALL)
            if thinking_match:
                chat_history.append(AIMessage(content=thinking_match.group(2)))
            else:
                chat_history.append(AIMessage(content=content))

    # --- (修复 2) 异步 generate 函数 ---
    async def generate():
        yield ": ping\n\n"
        full_response = ""
        model_name = model
        thinking_response = ""
        stream_started = False
        llm_is_done = False # LLM 完成标志

        llm_task = None
        ping_task = None

        try:
            llm_stream = final_chain_streaming.astream({
                "input": query,
                "chat_history": chat_history
            })
            stream_started = True

            async def ping_generator():
                while True:
                    await asyncio.sleep(20)
                    yield "ping"

            ping_stream = ping_generator()

            llm_iter = llm_stream.__aiter__()
            ping_iter = ping_stream.__aiter__()

            llm_task = asyncio.create_task(llm_iter.__anext__())
            ping_task = asyncio.create_task(ping_iter.__anext__())

            pending = {llm_task, ping_task}

            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    if task == llm_task:
                        try:
                            delta_chunk = task.result()
                            delta_content = delta_chunk.content or ""
                            delta_thinking = ""
                            new_thinking_detected = False

                            # (*** 关键逻辑 ***)
                            # 检查 LLM 块中的 additional_kwargs
                            if delta_chunk.additional_kwargs:
                                # 对应 SiliconFlow 文档的 "reasoning_content"
                                new_thought = delta_chunk.additional_kwargs.get("reasoning_content")
                                if new_thought and new_thought != thinking_response:
                                    thinking_response = new_thought
                                    # 将其放入 "thinking" 字段，供 app.js 消费
                                    delta_thinking = new_thought
                                    new_thinking_detected = True

                            if delta_content or new_thinking_detected:
                                full_response += delta_content
                                # (*** 关键逻辑 ***)
                                # 发送 app.js 期望的 JSON 格式
                                yield f"data: {json.dumps({'choices': [{'delta': {'content': delta_content, 'thinking': delta_thinking}}], 'model': model_name})}\n\n"

                            llm_task = asyncio.create_task(llm_iter.__anext__())
                            pending.add(llm_task)

                        except (StopAsyncIteration, asyncio.CancelledError, GeneratorExit):
                            llm_is_done = True
                            if ping_task:
                                ping_task.cancel()
                        except Exception as e:
                            logger.error(f"[{conv_id}] LCEL 链执行失败 (async): {e}", exc_info=True)
                            yield f"data: {json.dumps({'error': f'RAG 链执行失败 (async): {e}'})}\n\n"
                            llm_is_done = True
                            if ping_task:
                                ping_task.cancel()
                            if ping_task in pending:
                                pending.remove(ping_task)

                    elif task == ping_task:
                        try:
                            _ = task.result() # 如果被取消，这里会 raise CancelledError
                            yield ": ping\n\n"
                            if not llm_is_done:
                                ping_task = asyncio.create_task(ping_iter.__anext__())
                                pending.add(ping_task)
                        except (StopAsyncIteration, asyncio.CancelledError, GeneratorExit):
                            pass # Ping 任务被取消或停止，这是预期的
                        except Exception as e:
                            logger.warning(f"[{conv_id}] Ping generator 失败: {e}", exc_info=True)

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[{conv_id}] 异步流 generate 协程失败: {e}", exc_info=True)
            try:
                yield f"data: {json.dumps({'error': f'异步流 generate 协程失败: {e}'})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                pass
        finally:
            if llm_task and not llm_task.done():
                llm_task.cancel()
            if ping_task and not ping_task.done():
                ping_task.cancel()

            if stream_started:
                try:
                    async with AsyncSessionLocal.begin() as db_session:
                        # (*** 关键逻辑 ***)
                        # 保持与 app.js 兼容的格式保存到数据库
                        if thinking_response:
                            full_content_with_thinking = f"\n{thinking_response}\n\n\n{full_response}"
                        else:
                            full_content_with_thinking = full_response

                        await db_session.execute(
                            text("INSERT INTO messages (conv_id, user_id, role, content, model, temperature, top_p) VALUES (:cid, :uid, 'assistant', :c, :m, :t, :p)"),
                            {"cid": conv_id, "uid": user["id"], "c": full_content_with_thinking, "m": model_name, "t": temperature, "p": top_p}
                        )
                    if redis_client:
                        await redis_client.delete(f"messages:{conv_id}")
                    logger.info(f"[{conv_id}] 成功保存对话 (finally 块)。")
                except Exception as db_e:
                    logger.error(f"[{conv_id}] 在 finally 块中保存对话失败: {db_e}", exc_info=True)
            else:
                logger.warning(f"[{conv_id}] 流未启动，未保存对话 (finally 块)。")
    # --- 修复结束 ---

    return StreamingResponse(generate(), media_type="text/event-stream; charset=utf-8", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"
    })

# --- /api/upload ---
@api_router.post("/api/upload")
async def upload(
        request: Request,
        user: Dict[str, Any] = Depends(get_current_user),
        session = Depends(get_db_session)
):
    form = await request.form()
    if "file" not in form or not (f := form["file"]).filename:
        raise HTTPException(status_code=400, detail="missing file")

    name = secure_filename(f.filename)
    if not name or len(name) > 200 or not allowed_file(name):
        raise HTTPException(status_code=400, detail="invalid filename or type")

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
async def update_all(_user: Dict[str, Any] = Depends(get_current_user)):
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
async def refresh_status(_user: Dict[str, Any] = Depends(get_current_user)):
    if not redis_client:
        return JSONResponse({"status": "disabled", "message": "Redis not configured"})

    status_json = await redis_client.get("refresh:status")
    if status_json:
        return JSONResponse(json.loads(status_json))

    if not await redis_client.get("refresh:lock"):
        return JSONResponse({"status": "idle", "message": "空闲"})

    try:
        counts = await redis_client.mget([
            "refresh:total_queued", "refresh:success_count",
            "refresh:skipped_count"
        ])
        total_queued = int(counts[0] or 0)
        success_count = int(counts[1] or 0)
        skipped_count = int(counts[2] or 0)

        processed_count = success_count + skipped_count

        if total_queued > 0 and processed_count >= total_queued:
            final_message = "刷新完成。"
            status = {"status": "success", "message": final_message}

            p = redis_client.pipeline()
            p.set("refresh:status", json.dumps(status), ex=300)
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