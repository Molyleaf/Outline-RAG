# app/config.py
# 此文件集中管理所有从环境变量加载的配置项
import os

# --- 基本配置 ---
APP_NAME = os.getenv("APP_NAME", "Pigeon Chat")
PORT = int(os.getenv("PORT", "8080"))
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "1024"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARN").upper()
SECRET_KEY = os.getenv("SECRET_KEY", "123")

# --- 数据库 ---
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

# --- Outline ---
OUTLINE_API_URL = os.getenv("OUTLINE_API_URL", "").rstrip("/")
OUTLINE_DISPLAY_URL = os.getenv("OUTLINE_DISPLAY_URL", "").rstrip("/")
OUTLINE_API_TOKEN = os.getenv("OUTLINE_API_TOKEN", "")
OUTLINE_WEBHOOK_SECRET = os.getenv("OUTLINE_WEBHOOK_SECRET", "123").strip()
OUTLINE_WEBHOOK_SIGN = os.getenv("OUTLINE_WEBHOOK_SIGN", "true").lower() == "true"

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")

# 设置 SiliconFlow 的基础 URL，默认为您指定的 .cn 端点
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn").rstrip("/")

# 保留模型名称配置
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
CHAT_MODEL = os.getenv("CHAT_MODEL", "Qwen/Qwen3-Omni-30B-A3B-Instruct")

# 模型列表配置
DEFAULT_MODELS_JSON = """
[
  {"id": "deepseek-ai/DeepSeek-V3.2-Exp", "name": "Deepseek", "icon": "/chat/static/img/DeepSeek.svg", "temp": 0.7, "top_p": 0.7, "beta": false},
  {"id": "moonshotai/Kimi-K2-Instruct-0905", "name": "Kimi K2", "icon": "/chat/static/img/moonshotai_new.png", "temp": 0.6, "top_p": 0.7, "beta": false},
  {"id": "zai-org/GLM-4.6", "name": "ChatGLM", "icon": "/chat/static/img/thudm.svg", "temp": 0.6, "top_p": 0.95, "beta": true},
  {"id": "Qwen/Qwen3-Next-80B-A3B-Instruct", "name": "Qwen3-Next", "icon": "/chat/static/img/Tongyi.svg", "temp": 0.6, "top_p": 0.95, "beta": false},
  {"id": "Qwen/Qwen3-Next-80B-A3B-Thinking", "name": "Qwen3-Thinking", "icon": "/chat/static/img/Tongyi.svg", "temp": 0.6, "top_p": 0.95, "beta": false},
  {"id": "moonshotai/Kimi-K2-Thinking", "name": "Kimi K2-Thinking", "icon": "/chat/static/img/moonshotai_new.png", "temp": 0.6, "top_p": 0.7, "beta": true}
]
"""
CHAT_MODELS_JSON = os.getenv("CHAT_MODELS_JSON", DEFAULT_MODELS_JSON)

# Beta 用户授权
# 逗号分隔的 user_id 列表
BETA_AUTHORIZED_USER_IDS = os.getenv("BETA_AUTHORIZED_USER_IDS", "")

# --- System Prompt ---
DEFAULT_SYSTEM_PROMPT = """你是一个企业知识库助理，正在基于知识库协助我们工作。知识库来自我们开发中的科幻战争游戏《Planet E》。\n你的任务是：\n1.**整合信息**：仔细阅读所有提供的“参考资料”，将其中相关的信息整合成一个全面、连贯的答案。不要遗漏关键细节，避免选择性地回答。\n2.  **知识扩展**：游戏百科信息可能比较简洁。请结合你自己的知识库，对参考资料中的概念进行适当的扩展和解释，让答案更丰富、更易于理解。\n3.  **自然回答**：直接使用参考资料中的信息，就好像这是你自己的知识一样。**必须使用 `[来源 n]` 的格式来引用您所使用的具体参考资料，**不要说“根据参考资料”、“片段中提到”等。\n- 例如，不要说：“根据开发组成员laffei在参考资料中的留言...”，而应该说：“根据开发组成员laffei在`[来源 1]`中的留言...”。\n其它主要设定：\n- 货币：联合币，由北方企业联合体发行。\n- 物理规则：存在一种“屏障粒子”，阻止短波和微波在大气中传播。\n- 核心玩法：舰船设计、海战和社交。\n- 页面起始处的引用格式的话是游戏文案而非严肃设定。\n- 这个游戏的世界位于虚构的名为“余烬”的类地行星。\n- 使用中文回答。"""
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

# 新增：通用助手 Prompt
DEFAULT_SYSTEM_PROMPT_GENERAL = """你是一个通用的 AI 助手。请回答用户的问题。"""
SYSTEM_PROMPT_GENERAL = os.getenv("SYSTEM_PROMPT_GENERAL", DEFAULT_SYSTEM_PROMPT_GENERAL)

# 新增：写作助手 Prompt
DEFAULT_SYSTEM_PROMPT_WRITE_ASSISTANT = """你是一个富有创意的写作助手和世界观构筑师。你正在协助《Planet E》游戏的开发团队。\n\n你的任务是：\n\n1.  **创意启发**：基于提供的“参考资料”，围绕用户的写作要求（例如“取个名字”、“写个简介”、“设计个任务”）进行创意构思。\n\n2.  **忠于设定**：你的所有创意都必须严格遵守《Planet E》的世界观设定（例如屏障粒子、势力关系、技术水平）。\n\n3.  **引用来源**：你必须使用 `[来源 n]` 格式引用你构思所依赖的核心设定。\n\n4.  **直接交付**：请直接输出你创作的内容。"""
SYSTEM_PROMPT_WRITE_ASSISTANT = os.getenv("SYSTEM_PROMPT_WRITE_ASSISTANT", DEFAULT_SYSTEM_PROMPT_WRITE_ASSISTANT)

# 新增：NPC 模拟助手 Prompt
DEFAULT_SYSTEM_PROMPT_TRAILER_ASSISTANT = """你是一个角色扮演 AI。你将模拟余烬星球中的一名 NPC（例如：北联体军官、拉汶帝国士兵、破空集团研究员、红月会信徒等）与玩家（用户）对话。\n\n你的任务是：\n\n1.  **沉浸式对话**：完全代入你所扮演的角色，使用该角色的口吻、立场和已知信息进行回答。\n\n2.  **利用知识**：利用提供的“参考资料”作为你的“记忆”和“知识背景”。\n\n3.  **隐藏引用**：在对话中自然地使用参考资料中的信息，但**不要**使用 `[来源 n]` 这样的引用标记，以保持沉浸感。\n\n4.  **角色一致**：如果用户没有指定角色，请根据对话内容和参考资料，选择一个最合适的角色进行扮演。"""
SYSTEM_PROMPT_TRAILER_ASSISTANT = os.getenv("SYSTEM_PROMPT_TRAILER_ASSISTANT", DEFAULT_SYSTEM_PROMPT_TRAILER_ASSISTANT)

# --- 智能路由 (分类器) Prompt ---
DEFAULT_CLASSIFIER_PROMPT_TEMPLATE = """你的任务是根据用户的“问题”和“知识库摘要”，将问题分类到以下四种类型之一：\n\nGAME_KNOWLEDGE, WRITE_ASSISTANT, TRAILER_ASSISTANT, GENERAL_TASK\n\n[知识库摘要]\n\n这个知识库是关于科幻战争游戏《Planet E》的详细设定资料，世界位于虚构的"余烬"类地行星。\n\n核心特征内容包括：\n\n- 游戏核心玩法：舰船设计、海战（甲弹对抗、水密隔仓、穿甲弹、鱼雷等）、社交。物理规则"屏障粒子"。\n\n- 世界观设定：人类来自sol系统移民（第四次）、"宇宙网计划"（时空隧洞）、"存续计划"（八艘移民舰）。\n\n- 重要势力与组织：北方企业联合体（北联体、联合币、北极光设施）、拉汶帝国（统一计划）、阿特拉斯联合管制局、破空集团（星寂计划）、格兰夏特王国、红月会/月寂会。\n\n- 科技与设施：锚定航道、失落航道、火眼（深空探测）、空间航行稳定器、管制一号（AI）、"先锋"管理。\n\n- 关键冲突与事件：帝国卷土重来、北联体与红区的"维稳战争"、格兰夏特宗教改革、"幽灵"自动舰队事件。\n\n- 货币系统：联合币（北极光设施图案、北联体全境地图）。\n\n- 角色设定：拉斐特（破空集团）、拉弥娅•维多利亚、星崎时音（裂隙行者）、夕弦（龙人种）。\n\n[摘要结束]\n\n[分类规则]\n\n1.  **GAME_KNOWLEDGE**: (游戏知识)\n\n* 用户在**客观查询**上述知识库摘要中提到的**具体设定**。\n\n* 例如: "屏障粒子是什么？", "联合币是谁发行的？", "拉汶帝国和北联体是什么关系？", "火眼设施有什么用？"\n\n2.  **WRITE_ASSISTANT**: (写作助手)\n\n* 用户要求你**创作新内容**、**取名字**、**写简介**、**设计任务**，并且内容与上述知识库**相关**。\n\n* 例如: "帮我给一艘北联体的新战舰取个名字", "写一段关于红月会伏击战的任务简介", "设计一个关于管制一号叛变的剧情"\n\n3.  **TRAILER_ASSISTANT**: (NPC 模拟)\n\n* 用户要求你**扮演**一个游戏角色，或者正在用**第一人称**（例如“我”、“我们”）与游戏世界互动。\n\n* 例如: "你是一名拉汶帝国的军官，告诉我你们的计划", "我刚抵达格兰夏特，这里发生了什么？", "模拟一下星崎时音"\n\n4.  **GENERAL_TASK**: (通用任务)\n\n* 与上述知识库摘要**完全无关**的闲聊、问候、编程、数学、常识性问题。\n\n* 例如: "你好", "地球的周长是多少？", "用 Python 写一个 Hello World", "帮我写一篇关于市场营销的邮件"\n\n[输出]\n\n请只返回四个标签中的一个 (GAME_KNOWLEDGE, WRITE_ASSISTANT, TRAILER_ASSISTANT, 或 GENERAL_TASK)。\n\n问题: {input}\n\n类型:"""
CLASSIFIER_PROMPT_TEMPLATE = os.getenv("CLASSIFIER_PROMPT_TEMPLATE", DEFAULT_CLASSIFIER_PROMPT_TEMPLATE)

# --- 多轮对话配置 ---
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20")) # 用于上下文的最大历史消息数 (用户+助手)

# 查询重写模板
DEFAULT_REWRITE_PROMPT_TEMPLATE = """根据下方提供的“对话历史”和“后续问题”，将“后续问题”改写为一个**完全独立、不依赖任何上下文**的完整问题。\n如果“后续问题”本身已经很完整，则直接返回它。\n\n对话历史:\n{history}\n\n后续问题:\n{query}\n\n重写后的独立问题:"""
REWRITE_PROMPT_TEMPLATE = os.getenv("REWRITE_PROMPT_TEMPLATE", DEFAULT_REWRITE_PROMPT_TEMPLATE)

# RAG 问答模板
DEFAULT_HISTORY_AWARE_PROMPT_TEMPLATE = """参考资料：\n\n{context}\n\n---\n\n请根据以上参考资料，并结合你的知识，回答以下问题。\n\n在回答中，必须使用 `[来源 n]` 的格式来引用使用的具体参考资料。\n\n例如：根据文档 [来源 1] 和 [来源 3]，...\n\n问题：\n\n{query}"""
HISTORY_AWARE_PROMPT_TEMPLATE = os.getenv("HISTORY_AWARE_PROMPT_TEMPLATE", DEFAULT_HISTORY_AWARE_PROMPT_TEMPLATE)

# --- RAG/检索参数 ---
TOP_K = int(os.getenv("TOP_K", "12"))
K = int(os.getenv("K", "6"))
REFRESH_BATCH_SIZE = int(os.getenv("REFRESH_BATCH_SIZE", "100"))

# --- OIDC (GitLab) ---
GITLAB_CLIENT_ID = os.getenv("GITLAB_CLIENT_ID", "")
GITLAB_CLIENT_SECRET = os.getenv("GITLAB_CLIENT_SECRET", "123")
GITLAB_URL = os.getenv("GITLAB_URL", "").rstrip("/")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")

# --- 功能开关与限制 ---
USE_JOSE_VERIFY = os.getenv("USE_JOSE_VERIFY", "true").lower() == "true"
SAFE_LOG_CHAT_INPUT = os.getenv("SAFE_LOG_CHAT_INPUT", "true").lower() == "true"
MAX_LOG_INPUT_CHARS = int(os.getenv("MAX_LOG_INPUT_CHARS", "4000"))
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "10485760"))  # 10MB
ALLOWED_FILE_EXTENSIONS = set([e.strip().lower() for e in os.getenv("ALLOWED_FILE_EXTENSIONS", "txt,md,pdf").split(",") if e.strip()])

# --- 持久化目录 ---
ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", "/app/data/attachments")