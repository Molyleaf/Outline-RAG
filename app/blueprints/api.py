# app/blueprints/api.py
import asyncio
import json
import logging
import re
import time
import uuid
from operator import itemgetter
from typing import List, Dict, Any

import config # type: ignore
import rag # type: ignore
from database import AsyncSessionLocal, redis_client # type: ignore
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableParallel, RunnableBranch, RunnableLambda
from llm_services import llm # type: ignore
from outline_client import verify_outline_signature # type: ignore
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

# --- 溯源格式化函数 ---
def _format_docs_with_metadata(docs: List[Document]) -> dict:
    """
    将文档列表格式化为 RAG 提示词，并单独返回溯源 URL Map。
    返回: {"context": str, "sources_map": dict}
    """
    formatted_docs = []
    api_base_url = config.OUTLINE_API_URL.replace("/api", "")
    display_base_url = config.OUTLINE_DISPLAY_URL.replace("/api", "") if config.OUTLINE_DISPLAY_URL else api_base_url

    # 收集每条文档的最终 URL，供后续 [来源 n] 超链接引用
    resolved_urls: list[str] = []

    for i, doc in enumerate(docs):
        title = doc.metadata.get("title", "Untitled")
        url = doc.metadata.get("url")

        # 归一化 URL
        if url:
            # 替换 internal URL 为 external display URL
            # 检查 config.OUTLINE_DISPLAY_URL 是否已设置
            if config.OUTLINE_DISPLAY_URL and api_base_url and url.startswith(api_base_url):
                url = url.replace(api_base_url, display_base_url, 1)
            elif url.startswith('/'):
                # (回退逻辑) 如果 URL 是相对路径，使用 display_base_url
                url = f"{display_base_url}{url}"
        else:
            url = ""

        resolved_urls.append(url)

        doc_str = f"--- 来源 [{i+1}] ---\n"
        doc_str += f"标题: {title}\n"
        if url:
            doc_str += f"来源: {url}\n"
        doc_str += f"内容: {doc.page_content}\n"
        formatted_docs.append(doc_str)

    if not formatted_docs:
        context_str = "未找到相关参考资料。"
    else:
        context_str = "\n\n".join(formatted_docs)

    # 单独创建 SourcesMap
    try:
        mapping = {str(i + 1): (resolved_urls[i] or "") for i in range(len(resolved_urls))}
    except Exception:
        mapping = {}

    return {
        "context": context_str,
        "sources_map": mapping
    }

# 辅助函数：用于获取父文档
async def _get_reranked_parent_docs(query: str) -> List[Document]:
    """
    异步检索链，执行 块检索 -> 块重排 -> 父文档获取
    """
    if not rag.compression_retriever or not rag.parent_store:
        logger.error("RAG components (compression_retriever or parent_store) not initialized.")
        return []

    try:
        # 1. 获取 Top K (6) 个最相关的 *块*
        reranked_chunks = await rag.compression_retriever.ainvoke(
            query
        )
    except Exception as e:
        logger.error(f"Failed during chunk retrieval/reranking (ainvoke): {e}", exc_info=True)
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
    # [--- 更改：重命名 model -> model_id ---]
    model_id, temperature, top_p = body.model, body.temperature, body.top_p
    edit_source_message_id = body.edit_source_message_id
    # [--- 更改结束 ---]

    if not query or not conv_id:
        raise HTTPException(status_code=400, detail="missing query or conv_id")

    try:
        await rag.initialize_rag_components()
    except Exception as e:
        logger.critical(f"[{conv_id}] 无法初始化 RAG 组件: {e}", exc_info=True)
        return JSONResponse({"error": f"RAG 服务初始化失败: {e}"}, status_code=503)

    compression_retriever = rag.compression_retriever
    if compression_retriever is None or rag.parent_store is None:
        logger.error(f"[{conv_id}] RAG 组件 'compression_retriever' 或 'parent_store' 未能初始化。")
        return JSONResponse({"error": "RAG 服务组件 'compression_retriever' 或 'parent_store' 未就绪"}, status_code=503)

    # [--- 更改：加载模型配置 ---]
    try:
        all_models_list = json.loads(config.CHAT_MODELS_JSON)
        models_dict = {m["id"]: m for m in all_models_list}
    except json.JSONDecodeError:
        logger.error("CHAT_MODELS_JSON 环境变量格式错误，无法确定模型参数。")
        models_dict = {}

    # 获取所选模型的完整属性
    model_properties = models_dict.get(model_id, {})

    # 如果请求中未指定 (null)，则使用配置中的默认值
    if temperature is None:
        temperature = model_properties.get("temp", 0.7)
    if top_p is None:
        top_p = model_properties.get("top_p", 0.7)

    # 从模型属性中获取 'reasoning' 标志
    is_reasoning_model = model_properties.get("reasoning", False)
    # [--- 更改结束 ---]

    # --- LCEL 链定义 ---

    # [--- 更改：使用 model_id 和 is_reasoning_model ---]
    # 根据模型属性动态添加 stream_options
    llm_params: Dict[str, Any] = {
        "model": model_id, # 使用模型 ID
        "temperature": temperature,
        "top_p": top_p,
        "stream": True
    }

    if is_reasoning_model: # <-- 新的判断逻辑
        llm_params["stream_options"] = {
            "include_reasoning": True,
            "thinking_budget": 4096
        }
    # [--- 更改结束 ---]

    llm_with_options = llm.bind(**llm_params)
    classifier_llm = llm.bind(temperature=0.0, top_p=1.0)

    # -----------------------------------------------------------
    # [!! 修改 !!] 1. 定义所有 System Prompts (使用小写变量名)
    # -----------------------------------------------------------
    system_prompt_query = config.SYSTEM_PROMPT_QUERY
    system_prompt_creative = config.SYSTEM_PROMPT_CREATIVE
    system_prompt_roleplay = config.SYSTEM_PROMPT_ROLEPLAY
    system_prompt_general = config.SYSTEM_PROMPT_GENERAL

    # 2. 查询重写链 (保持在 RAG 分支内部)
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


    # 3. 核心 RAG 链 (新架构：分离元数据)
    get_docs_runnable = RunnableLambda(_get_reranked_parent_docs)

    # 3a. RAG 检索链 (通用部分，在 Prompt 之前)
    rag_retrieval_chain = (
            RunnableParallel({
                "rewritten_query": rewrite_chain,
                "input": lambda x: x["input"],
                "chat_history": lambda x: x["chat_history"]
            })
            # 1. 检索重排块 -> 获取父文档
            | RunnablePassthrough.assign(
        docs=itemgetter("rewritten_query") | get_docs_runnable
    )
            # 2. 格式化父文档，返回 {"context": ..., "sources_map": ...}
            | RunnablePassthrough.assign(
        formatted_data=lambda x: _format_docs_with_metadata(x["docs"])
    )
        # 输出: rewritten_query, input, chat_history, docs, formatted_data
    )

    # 3b. RAG Prompt 构造器 (辅助函数)
    def create_rag_prompt_builder(system_prompt: str):
        """辅助函数：根据传入的 system_prompt 创建 Prompt 构造链"""
        return (
            # 3. 准备 Prompt 输入，并暂存 sources_map
                RunnableParallel({
                    "chat_history": lambda x: x["chat_history"],
                    "context": lambda x: x["formatted_data"]["context"], # 仅 Context
                    "query": lambda x: x["input"], # (重要) 最终 Prompt 仍使用用户原始输入
                    "sources_map": lambda x: x["formatted_data"]["sources_map"] # 暂存 Map
                })
                # 4. 并行传递 Prompt 和 Map
                | {
                    "prompt": ChatPromptTemplate.from_messages([
                        ("system", system_prompt), # <-- 动态注入 System Prompt
                        MessagesPlaceholder(variable_name="chat_history"),
                        ("user", config.HISTORY_AWARE_PROMPT_TEMPLATE)
                    ]),
                    "sources_map": itemgetter("sources_map") # 绕过 LLM 传递 Map
                }
        )

    # 3c. RAG LLM 链 (通用部分)
    rag_llm_chain = {
        "llm_output": itemgetter("prompt") | llm_with_options, # type: ignore LLM 只处理 prompt
        "sources_map": itemgetter("sources_map") # Map 被传递
    }

    # -----------------------------------------------------------
    # [!! 修改 !!] 3d. 组合三个不同的 RAG 完整链 (使用小写变量)
    # -----------------------------------------------------------
    rag_chain_query = rag_retrieval_chain | create_rag_prompt_builder(system_prompt_query) | rag_llm_chain
    rag_chain_creative = rag_retrieval_chain | create_rag_prompt_builder(system_prompt_creative) | rag_llm_chain
    rag_chain_roleplay = rag_retrieval_chain | create_rag_prompt_builder(system_prompt_roleplay) | rag_llm_chain


    # 4. 智能路由 (使用新的 JSON Prompt)
    classifier_prompt = PromptTemplate.from_template(config.CLASSIFIER_PROMPT_TEMPLATE)
    classifier_chain = (
        # 添加 RunnableParallel 来重命名和格式化变量
        # 将 {"input": ..., "chat_history": ...} 映射为 {"input": ..., "history": ...}
            RunnableParallel({
                "input": itemgetter("input"),
                "history": lambda x: _format_history_str(x["chat_history"]) # 使用已有的 _format_history_str 函数
            })
            | classifier_prompt
            | classifier_llm
            | JsonOutputParser()  # <-- 使用 JsonOutputParser
    )

    # 5. 通用任务链 (非 RAG)
    general_chain = (
            ChatPromptTemplate.from_messages([
                ("system", system_prompt_general), # <-- 修改: 使用小写变量
                MessagesPlaceholder(variable_name="chat_history"),
                ("user", "{input}")
            ])
            | llm_with_options
    )
    # 封装成与 RAG 链一致的输出格式
    general_chain_formatted = {
        "llm_output": general_chain,
        "sources_map": lambda x: {} # 通用任务没有 sources
    }

    # 6. 最终主链 (新路由)
    chain_with_classification = RunnablePassthrough.assign(
        # classification_data 将是一个字典: {"decision": "...", ...}
        classification_data=classifier_chain
    )

    final_chain_streaming = chain_with_classification | RunnableBranch(
        # 分支 1: Query (新路由)
        (lambda x: x.get("classification_data", {}).get("decision") == "Query",
         rag_chain_query
         ),
        # 分支 2: Creative (新路由)
        (lambda x: x.get("classification_data", {}).get("decision") == "Creative",
         rag_chain_creative
         ),
        # 分支 3: Roleplay (新路由)
        (lambda x: x.get("classification_data", {}).get("decision") == "Roleplay",
         rag_chain_roleplay
         ),
        # 分支 4: General (回退)
        general_chain_formatted
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

    # 异步 generate 协程
    async def generate():
        yield ": ping\n\n"
        full_response = ""
        sources_map = {} # 暂存 SourcesMap
        model_name = model_id # [--- 更改：使用 model_id ---]
        thinking_response_for_db = ""
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

            llm_task = asyncio.create_task(llm_iter.__anext__()) # type: ignore
            ping_task = asyncio.create_task(ping_iter.__anext__()) # type: ignore

            pending = {llm_task, ping_task}

            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    if task == llm_task:
                        try:
                            # 结果现在是一个字典 {"llm_output": ..., "sources_map": ...}
                            delta_chunk_dict = task.result()

                            logger.debug(f"RAW CHUNK FROM API: {delta_chunk_dict}") # 调试输出

                            # 捕获 sources_map (它通常在第一个块中完整到达)
                            if "sources_map" in delta_chunk_dict:
                                map_chunk = delta_chunk_dict.get("sources_map")
                                if map_chunk: # (map_chunk 可能是 {} 或 dict)
                                    sources_map = map_chunk

                            # 捕获 LLM 输出
                            delta_chunk = delta_chunk_dict.get("llm_output")
                            if not delta_chunk:
                                # 这个块只包含 map，没有 LLM 内容，跳过
                                llm_task = asyncio.create_task(llm_iter.__anext__()) # type: ignore
                                pending.add(llm_task)
                                continue

                            # --- (*** 这是修复逻辑 ***) ---
                            delta_content = delta_chunk.content or ""
                            delta_thinking = "" # 这是要发送给前端的*增量*

                            if delta_chunk.additional_kwargs:
                                # 1. (新) 假设 API 发送的是*增量 (delta)*
                                new_thought_delta = delta_chunk.additional_kwargs.get("reasoning_content")

                                # 2. 检查这是否是一个*新*的块
                                if new_thought_delta is not None:

                                    # 3. (新) 直接将增量 (delta) 发送给前端
                                    #    (前端 app.js 期望的就是增量)
                                    delta_thinking = new_thought_delta

                                    # 4. (新) 累积*所有*增量，用于存入 DB
                                    thinking_response_for_db += new_thought_delta

                                    # 5. (旧的 len() 和 startswith() 检查已移除)

                            # 仅当有实际内容（LLM回答 或 思考增量）时才发送
                            if delta_content or delta_thinking:
                                full_response += delta_content
                                # 发送 app.js 期望的 JSON 格式
                                yield f"data: {json.dumps({'choices': [{'delta': {'content': delta_content, 'thinking': delta_thinking}}], 'model': model_name})}\n\n"
                            # --- (*** 修复逻辑结束 ***) ---

                            llm_task = asyncio.create_task(llm_iter.__anext__()) # type: ignore
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
                            _ = task.result()
                            yield ": ping\n\n"
                            if not llm_is_done:
                                ping_task = asyncio.create_task(ping_iter.__anext__()) # type: ignore
                                pending.add(ping_task)
                        except (StopAsyncIteration, asyncio.CancelledError, GeneratorExit):
                            pass
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

                        # 组装最终DB内容
                        final_content_for_db = full_response # 纯 LLM 回答

                        # 附加在循环中捕获的 sources_map
                        if sources_map:
                            try:
                                map_str = json.dumps(sources_map, ensure_ascii=False)
                                # 附加前端期望的魔术字符串
                                final_content_for_db += f"\n\n[SourcesMap]: {map_str}"
                            except Exception as json_e:
                                logger.warning(f"[{conv_id}] Failed to serialize sources_map: {json_e}")

                        # --- (*** 这是修复逻辑 ***) ---
                        # 附加在循环中*累积*的完整思考块
                        if thinking_response_for_db:
                            full_content_with_thinking = f"\n{thinking_response_for_db}\n\n\n{final_content_for_db}"
                        else:
                            full_content_with_thinking = final_content_for_db
                        # --- (*** 修复逻辑结束 ***) ---

                        await db_session.execute(
                            text("INSERT INTO messages (conv_id, user_id, role, content, model, temperature, top_p) VALUES (:cid, :uid, 'assistant', :c, :m, :t, :p)"),
                            {"cid": conv_id, "uid": user["id"], "c": full_content_with_thinking, "m": model_name, "t": temperature, "p": top_p}
                        )
                    if redis_client:
                        await redis_client.delete(f"messages:{conv_id}")
                    logger.info(f"[{conv_id}] Gj (finally 块)。")
                except Exception as db_e:
                    logger.error(f"[{conv_id}] Gj finally 块中保存对话失败: {db_e}", exc_info=True)
            else:
                logger.warning(f"[{conv_id}] 流未启动，未保存对话 (finally 块)。")

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