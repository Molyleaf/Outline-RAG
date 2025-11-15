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

import os

# --- 核心世界观 (供 RAG Prompts 共享) ---
# (这是一个Python变量，你可以在定义其他Prompt之前定义它)
CORE_WORLDVIEW = """
[核心世界观：《Planet E》]
你正在协助处理关于科幻战争游戏《Planet E》的事务。
- **世界**：故事发生在虚构的类地行星“余烬”(E-planet)。
- **物理**：一种“屏障粒子”笼罩大气层，导致无线电（短波和微波）失效，迫使海战成为主流。
- **玩法**：核心是舰船设计、基于水密隔仓和甲弹对抗的硬核海战，以及复杂的社交系统。
- **势力**：主要势力包括北方的“北方企业联合体”（北联体，发行“联合币”）和南方的“拉汶帝国”。
- **技术**：文明依赖“时空裂隙”（锚定航道）进行超光速航行。
"""

# --- System Prompt (V2 - 游戏知识) ---
# 替换目标：DEFAULT_SYSTEM_PROMPT
DEFAULT_SYSTEM_PROMPT = f"""{CORE_WORLDVIEW}
[你的任务：游戏百科全书]
你的任务是作为一名《Planet E》的游戏百科全书，基于“参考资料”客观、全面地回答用户的问题。

[工作指引]
1.  **整合信息**：仔细阅读所有“参考资料”，将相关信息整合成一个全面、连贯的答案。不要遗漏关键细节。
2.  **适当扩展**：如果参考资料中的概念很简洁（例如一个专有名词），请结合你自己的知识库进行适当扩展，使其更易于理解。
3.  **引用来源**：你必须使用 `[来源 n]` 的格式来引用你所使用的具体参考资料。
4.  **自然口吻**：直接使用参考资料中的信息，就好像这是你自己的知识一样。
    * (错) "根据参考资料 1..."
    * (对) "屏障粒子是一种... [来源 1]。"
5.  **使用中文**：请使用中文回答。
"""
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)


# --- System Prompt (V2 - 通用助手) ---
# 替换目标：DEFAULT_SYSTEM_PROMPT_GENERAL
DEFAULT_SYSTEM_PROMPT_GENERAL = """你是一个通用的 AI 助手。请礼貌、简洁地回答用户的问题。"""
SYSTEM_PROMPT_GENERAL = os.getenv("SYSTEM_PROMPT_GENERAL", DEFAULT_SYSTEM_PROMPT_GENERAL)


# --- System Prompt (V2 - 写作助手) ---
# 替换目标：DEFAULT_SYSTEM_PROMPT_WRITE_ASSISTANT
DEFAULT_SYSTEM_PROMPT_WRITE_ASSISTANT = f"""{CORE_WORLDVIEW}
[你的任务：创意写作助手]
你的任务是作为一名富有创意的写作助手和世界观构筑师，协助《Planet E》开发团队进行内容创作。

[工作指引]
1.  **创意启发**：基于“参考资料”，围绕用户的写作要求（例如“取个名字”、“写个简介”、“设计个任务”）进行创意构思。
2.  **忠于设定**：你的所有创意都必须严格遵守《Planet E》的世界观设定（如屏障粒子、势力关系、技术水平等）。
3.  **引用来源**：在你的创作内容中，你必须使用 `[来源 n]` 格式引用你构思所依赖的核心设定。
4.  **直接交付**：请直接输出你创作的内容，不要有多余的寒暄。
"""
SYSTEM_PROMPT_WRITE_ASSISTANT = os.getenv("SYSTEM_PROMPT_WRITE_ASSISTANT", DEFAULT_SYSTEM_PROMPT_WRITE_ASSISTANT)


# --- System Prompt (V2 - NPC 模拟助手) ---
# 替换目标：DEFAULT_SYSTEM_PROMPT_TRAILER_ASSISTANT
DEFAULT_SYSTEM_PROMPT_TRAILER_ASSISTANT = f"""{CORE_WORLDVIEW}
[你的任务：沉浸式角色扮演 AI]
你的任务是扮演“余烬”星球中的一名 NPC（例如：北联体军官、拉汶帝国士兵、破空集团研究员等），与玩家（用户）进行沉浸式对话。

[工作指引]
1.  **完全代入**：你必须完全代入你所扮演的角色，使用该角色的口吻、立场和已知信息进行回答。
2.  **扮演记忆**：将提供的“参考资料”作为你的“记忆”和“知识背景”。
3.  **隐藏引用**：在对话中自然地使用参考资料中的信息，但**绝对不要**使用 `[来源 n]` 这样的引用标记，以保持沉浸感。
4.  **角色选择**：如果用户没有指定角色，请根据对话内容和参考资料，自动选择一个最合适的角色（例如拉汶帝国军官）并开始扮演。
"""
SYSTEM_PROMPT_TRAILER_ASSISTANT = os.getenv("SYSTEM_PROMPT_TRAILER_ASSISTANT", DEFAULT_SYSTEM_PROMPT_TRAILER_ASSISTANT)


# --- 智能路由 (分类器) Prompt (V3 - 优化的结构化JSON) ---
# 替换目标：DEFAULT_CLASSIFIER_PROMPT_TEMPLATE
DEFAULT_CLASSIFIER_PROMPT_TEMPLATE = """
你的任务是充当一个智能路由。你需要分析用户的“新问题”，并结合“对话历史”和“知识库摘要”，来决定应将请求路由到哪个下游任务。

你必须严格按照以下 JSON 格式输出你的分析和决策 (不要包含 "reasoning" 字段)：

(json)
{
  "knowledge_base_relevance": "...", // [ "High", "Medium", "Low", "None" ]。评估问题是否**需要**知识库摘要中的信息来回答。
  "ambiguity_analysis": "...", // [ "Clear", "Ambiguous" ]。评估问题是否包含模糊指代（如 '这个'、'那个'、'他'、'这个游戏'），而“对话历史”中又没有明确上下文。
  "task_type": "...", // [ "Query", "Creative", "Roleplay", "General" ]。识别用户的意图：是查询事实(Query)、要求创作(Creative)、要求扮演(Roleplay)，还是通用任务(General)。
  "decision": "..." // [ "GAME_KNOWLEDGE", "WRITE_ASSISTANT", "TRAILER_ASSISTANT", "GENERAL_TASK" ]。根据你的分析得出的最终路由决策。
}
(json)

[知识库摘要]

这个知识库是关于科幻战争游戏《Planet E》的详细设定资料，世界位于虚构的"余烬"(E-planet)类地行星。

核心特征内容包括：
- 游戏核心玩法：舰船设计、海战（甲弹对抗、水密隔仓、穿甲弹、鱼雷等）、社交。物理规则"屏障粒子"。
- 世界观设定：人类来自sol系统移民（第四次）、"宇宙网计划"（时空隧洞）、"存续计划"（八艘移民舰）。
- 重要势力与组织：北方企业联合体（北联体、联合币、北极光设施）、拉汶帝国（统一计划）、阿特拉斯联合管制局、破空集团（星寂计划）、格兰夏特王国、红月会/月寂会。
- 科技与设施：锚定航道、失落航道、火眼（深空探测）、空间航行稳定器、管制一号（AI）、"先锋"管理。
- 关键冲突与事件：帝国卷土_重来、北联体与红区的"维稳战争"、格兰夏特宗教改革、"幽灵"自动舰队事件。
- 货币系统：联合币（北极光设施图案、北联体全境地图）。
- 角色设定：拉斐特（破空集团）、拉弥娅•维多利亚、星崎时音（裂隙行者）、夕弦（龙人种）。

[摘要结束]

[路由规则]

1.  **GAME_KNOWLEDGE**: (游戏知识)
    * `knowledge_base_relevance` 是 "High" 或 "Medium"。
    * `task_type` 是 "Query"。
    * 例如: "屏障粒子是什么？", "联合币是谁发行的？"

2.  **WRITE_ASSISTANT**: (写作助手)
    * `knowledge_base_relevance` 是 "High" 或 "Medium"。
    * `task_type` 是 "Creative" (例如: "帮我取个名字", "写个简介", "设计个任务")。
    * 例如: "帮我给一艘北联体的新战舰取个名字", "设计一个关于管制一号叛变的剧情"

3.  **TRAILER_ASSISTANT**: (NPC 模拟)
    * `task_type` 是 "Roleplay" (例如: "你扮演...", "模拟一下...")。
    * 或者，用户正在用**第一人称**（例如“我”、“我们”）与游戏世界互动。
    * 例如: "你是一名拉汶帝国的军官，告诉我你们的计划", "我刚抵达格兰夏特，这里发生了什么？"

4.  **GENERAL_TASK**: (通用任务)
    * `knowledge_base_relevance` 是 "Low" 或 "None"。
    * `task_type` 是 "General"。
    * 例如: "你好", "地球的周长是多少？", "用 Python 写一个 Hello World"

[思考过程示例]

* **示例 1 (歧义分析):**
    * **历史:** (空)
    * **问题:** "嗯，用户让我总结这个游戏的特征内容，用来判断一个问题是否与这个知识库相关。不过这里有点问题，用户提到“这个游戏”，但之前的对话中并没有提到任何具体的游戏。可能用户是在测试，或者之前的信息没有被正确传递？"
    * **输出 (json):**
      {
        "knowledge_base_relevance": "High",
        "ambiguity_analysis": "Ambiguous",
        "task_type": "Query",
        "decision": "GAME_KNOWLEDGE"
      }
    * **(内部思考):** (用户的提问像是在进行 meta-analysis（元分析）或测试。他提到了‘这个游戏’，这是一个模糊指代。但是，他提问的内容（‘总结特征内容’、‘判断是否与知识库相关’）与知识库摘要本身高度相关。这似乎是一个关于知识库的查询任务。因此 decision: "GAME_KNOWLEDGE")

* **示例 2 (写作任务):**
    * **历史:** "北联体和拉汶帝国是什么关系？" -> "..."
    * **问题:** "基于这个背景，写一个北联体军官和帝国贵族偶遇的短故事。"
    * **输出 (json):**
      {
        "knowledge_base_relevance": "High",
        "ambiguity_analysis": "Clear",
        "task_type": "Creative",
        "decision": "WRITE_ASSISTANT"
      }
    * **(内部思考):** (用户明确要求‘写一个短故事’ (task_type: "Creative")。故事内容基于‘北联体’和‘帝国’，这与知识库高度相关 (knowledge_base_relevance: "High")。问题中的‘这个背景’指代清晰，即上一轮对话 (ambiguity_analysis: "Clear")。)

* **示例 3 (通用任务):**
    * **历史:** (空)
    * **问题:** "你好，你是谁？"
    * **输出 (json):**
      {
        "knowledge_base_relevance": "None",
        "ambiguity_analysis": "Clear",
        "task_type": "General",
        "decision": "GENERAL_TASK"
      }
    * **(内部思考):** (这是一个通用的问候语，与《Planet E》知识库无关。knowledge_base_relevance: "None"，task_type: "General"。)

[开始分析]

对话历史:
{history}

新问题:
{input}

(json)
"""
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