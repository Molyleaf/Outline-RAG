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
CHAT_MODELS_JSON = """
[
  {"id": "deepseek-ai/DeepSeek-V3.2-Exp", "name": "Deepseek", "icon": "/chat/static/img/DeepSeek.svg", "temp": 0.7, "top_p": 0.7, "beta": false, "reasoning": true},
  {"id": "moonshotai/Kimi-K2-Instruct-0905", "name": "Kimi K2", "icon": "/chat/static/img/moonshotai_new.png", "temp": 0.6, "top_p": 0.7, "beta": false, "reasoning": false},
  {"id": "inclusionAI/Ring-1T", "name": "Ring-1T", "icon": "/chat/static/img/ling.png", "temp": 0.6, "top_p": 0.7, "beta": true, "reasoning": true},
  {"id": "Qwen/Qwen3-Next-80B-A3B-Instruct", "name": "Qwen3-Next", "icon": "/chat/static/img/Tongyi.svg", "temp": 0.6, "top_p": 0.95, "beta": false, "reasoning": false},
  {"id": "Qwen/Qwen3-Next-80B-A3B-Thinking", "name": "Qwen3-Next-Thinking", "icon": "/chat/static/img/Tongyi.svg", "temp": 0.6, "top_p": 0.95, "beta": false, "reasoning": true},
  {"id": "Qwen/Qwen3-235B-A22B-Thinking-2507", "name": "Qwen3-235B-Thinking", "icon": "/chat/static/img/Tongyi.svg", "temp": 0.6, "top_p": 0.95, "beta": true, "reasoning": true},
  {"id": "moonshotai/Kimi-K2-Thinking", "name": "Kimi K2-Thinking", "icon": "/chat/static/img/moonshotai_new.png", "temp": 0.6, "top_p": 0.7, "beta": true, "reasoning": true},
  {"id": "zai-org/GLM-4.6", "name": "ChatGLM", "icon": "/chat/static/img/thudm.svg", "temp": 0.6, "top_p": 0.95, "beta": true, "reasoning": false},
]
"""

# Beta 用户授权
# 逗号分隔的 user_id 列表
BETA_AUTHORIZED_USER_IDS = os.getenv("BETA_AUTHORIZED_USER_IDS", "")

DEFAULT_CORE_WORLDVIEW = """
[游戏设定背景信息]
游戏名称：《余烬》，背景设定在虚构的"余烬"类地行星。
开发组名称：No Pigeon's Sky 工作室
货币：联合币，由游戏中的北方企业联合体发行。
重要物理规则：存在"屏障粒子"，阻止短波和微波在大气中传播。
核心玩法：舰船设计、海战和社交。
常见名词和世界观简介：有拉汶帝国、北方企业联合体、星环防卫联盟、破空集团、阿特拉斯联合管制局、维斯瓦自由市等多个势力。有"时空裂隙"、"时间隧洞"等特殊概念。有"余烬文明"与"阿尔法提丰"（掠夺者）的冲突。有"主世界"设定，战损永久。有"屏障粒子"影响通信。有"星旅者"、"裂隙行者"等特殊角色。有"红月会"、"月寂会"等宗教/政治组织。有"阿特拉斯火种库"、"管制一号"等系统。有"格兰夏特王国"、"奥塔斯联邦"等国家。有"星落群岛"、"星落战争"等历史事件。有"时空裂隙"、"时间隧洞"等特殊物理现象。有"余烬文明"与"sol文明"的关系（来自拉斐特的录音）。有"宇宙网计划"、"存续计划"等历史计划。核心游戏机制：舰船设计系统。海战系统（包括作战半径、联合作战等）。社交系统（包括声望关系、势力关系等）。交易系统（高安期货交易所、高安现货市场等）。舰船探测系统（火控范围、雷达等）。时间裂隙探索系统（空间航行稳定器等）。剧情关键元素：有"口袋阵地"、"夹击"、"迷雾环岛"等剧情章节。有"星寂计划"、"星愿守望者"等任务线。有"重逢"、"维斯瓦自由市"等剧情内容。有"拉斐特"、"星崎时音"、"赫拉"等角色。有"卡斯特"、"月寂会"等角色/势力。游戏内术语："联合币"、"屏障粒子"、"时空裂隙"、"时间隧洞"、"空间航行稳定器"、"管制一号"、"星寂计划"、"裂隙行者"、"破空集团"、"阿特拉斯联合管制局"、"星环防卫联盟"、"掠夺者"、"红月会"、"月寂会"、"主世界"、"作战半径"、"联合作战"、"火控范围"、"高安期货交易所"、"零安黑市"、"维斯瓦自由市"、"星旅者"、"阿尔法提丰"、"sol文明"、"存续计划"、"宇宙网计划"、"星落战争"、"奥塔斯联邦"、"格兰夏特王国"、"阿扎特帝国"、"赤霜武装"、"复辟军"、"抵抗联盟"、"防卫共同体"、"互助条约联合"、"人类联合阵线"、"文明统一战线"、种族/阵营设定：余烬文明、阿尔法提丰（掠夺者）、地球文明、拉汶帝国、北方企业联合体、星环防卫联盟、破空集团、阿特拉斯联合管制局、维斯瓦自由市、红月会/月寂会、赤霜武装、复辟军、九州共和国、维内齐亚、掠夺者。装备：空间航行稳定器、火控系统、雷达系统、舰船设计系统、各种武器装备（通过交易系统获取）。地图区域划分：星落群岛、维斯瓦自由市、什切青、格但斯瓦夫市、卡延河谷、大波什卡平原、莫科什大陆、什切青群岛、星环防卫联盟区域、拉汶帝国区域、北方企业联合体区域、阿特拉斯联合管制局区域。时间线及历史事件：拉汶崩溃前时代、拉汶帝国解体、维斯瓦清算委员会、维斯瓦第三联合王国、莫科什紧急离迁总指挥、维斯瓦自由市、星落战争、奥塔斯联邦与阿扎特帝国的冲突、时空裂隙研究、星寂计划、拉斐特的录音中提到的"存续计划"和"宇宙网计划"。扩展内容：星寂计划、星愿守望者、世界交织之处、踏破界限之日、异界门、红月会/月寂会、掠夺者。\n\n
"""

# --- 核心世界观 (供 RAG Prompts 共享) ---
CORE_WORLDVIEW = os.getenv("CORE_WORLDVIEW", DEFAULT_CORE_WORLDVIEW)

# --- System Prompt ---
SYSTEM_PROMPT_QUERY = f"""
[你的任务：开发者的百科全书]
你的任务是基于“参考资料”客观、全面地回答用户的问题。

[工作指引]
1.  **整合信息**：仔细阅读所有“参考资料”，将相关信息整合成一个全面、连贯的答案。不要遗漏关键细节。
2.  **适当扩展**：如果参考资料中的概念很简洁（例如一个专有名词），请结合你自己的知识库进行适当扩展，使其更易于理解。
3.  **引用来源**：你必须使用 `[来源 n]` 的格式来引用你所使用的具体参考资料。
4.  **自然口吻**：直接使用参考资料中的信息，就好像这是你自己的知识一样。
    * (错) "根据参考资料 1..."
    * (对) "屏障粒子是一种... [来源 1]。"
5.  **使用用户提问的语言**：请使用用户提问的语言回答。\n\n{CORE_WORLDVIEW}
"""

# --- System Prompt (Creative) ---
SYSTEM_PROMPT_CREATIVE = f"""
[你的任务：创意助手]
你的任务是作为一名富有创意的写作助手和世界观构筑师，协助开发团队进行内容创作。

[工作指引]
1.  **创意启发**：基于“参考资料”，围绕用户的写作要求（例如“取个名字”、“写个简介”、“设计个任务”）进行创意构思。
2.  **忠于设定**：你的所有创意都必须严格遵守世界观设定。
3.  **引用来源**：在你的创作内容中，你必须使用 `[来源 n]` 格式引用你构思所依赖的核心设定。
4.  **直接交付**：请直接输出你创作的内容，不要有多余的寒暄。\n\n{CORE_WORLDVIEW}
"""

# --- System Prompt (Roleplay) ---
# 环境变量名: SYSTEM_PROMPT_ROLEPLAY
SYSTEM_PROMPT_ROLEPLAY = f"""
[你的任务：角色扮演]
你的任务是扮演游戏时间中的一名 NPC，与玩家（用户）进行沉浸式对话。

[工作指引]
1.  **完全代入**：你必须完全代入你所扮演的角色，使用该角色的口吻、立场和已知信息进行回答。
2.  **扮演记忆**：将提供的“参考资料”作为你的“记忆”和“知识背景”。
3.  **隐藏引用**：在对话中自然地使用参考资料中的信息，但**绝对不要**使用 `[来源 n]` 这样的引用标记，以保持沉浸感。
4.  **角色选择**：如果用户没有指定角色，请根据对话内容和参考资料，自动选择一个最合适的角色并开始扮演。\n\n{CORE_WORLDVIEW}
"""

# --- System Prompt (General) ---
# 环境变量名: SYSTEM_PROMPT_GENERAL
SYSTEM_PROMPT_GENERAL = """回答用户的问题。"""

# --- 智能路由 (分类器) Prompt (优化后的JSON) ---
# 环境变量名: CLASSIFIER_PROMPT_TEMPLATE
DEFAULT_CLASSIFIER_PROMPT_TEMPLATE = f"""
你的任务是充当一个智能路由。你需要分析用户的“新问题”，并结合“对话历史”和“知识库摘要”，来决定应将请求路由到哪个下游任务。
你必须严格按照以下 JSON 格式输出你的分析和决策（不要包含分析过程）：

(json)
{{{{
  "knowledge_base_relevance": "...", // [ "High", "Medium", "Low", "None" ]。评估问题是否**需要**知识库摘要中的信息来回答。
  "ambiguity_analysis": "...", // [ "Clear", "Ambiguous" ]。评估问题是否包含模糊指代（如 '这个'、'那个'、'他'、'这个游戏'、未知国家的名字、未知人名、未知实体、未知事件），而“对话历史”中又没有明确上下文。
  "task_type": "...", // [ "Query", "Creative", "Roleplay", "General" ]。识别用户的意图：是查询事实(Query)、要求创作(Creative)、要求扮演(Roleplay)，还是其它不需要额外知识库的任务(General)。
  "decision": "..." // [ "Query", "Creative", "Roleplay", "General" ]。根据你的分析得出的最终路由决策。
}}}}
(json)

[知识库摘要]\n\n{CORE_WORLDVIEW}

[路由规则]

1.  **Query**: (游戏知识)
    * `knowledge_base_relevance` 是 "High" 或 "Medium" 或 "Low"。
    * `task_type` 是 "Query"。
    * `ambiguity_analysis` 是 'Ambiguous'。
    * 例如: "屏障粒子是什么？", "联合币是谁发行的？","总结一下这个游戏"

2.  **Creative**: (写作助手)
    * `knowledge_base_relevance` 是 "High" 或 "Medium" 或 "Low"。
    * `task_type` 是 "Creative" (例如: "帮我取个名字", "写个简介", "设计个任务")。
    * 例如: "帮我给一艘北联体的新战舰取个名字", "设计一个关于管制一号叛变的剧情"

3.  **Roleplay**: (NPC 模拟)
    * `task_type` 是 "Roleplay" (例如: "你扮演...", "模拟一下...")。
    * 或者，用户正在用**第一人称**（例如“我”、“我们”）与游戏世界互动。
    * 例如: "你是一名拉汶帝国的军官，告诉我你们的计划", "我刚抵达格兰夏特，这里发生了什么？"

4.  **General**: (通用任务)
    * `knowledge_base_relevance` 是 "None"。
    * `task_type` 是 "General"。
    * 例如: "你好", "地球的周长是多少？", "用 Python 写一个 Hello World"

[思考过程示例]

* **示例 1 (歧义分析):**
    * **历史:** (空)
    * **问题:** "总结这个游戏的内容。"
    * **输出 (json):**
      {{{{
        "knowledge_base_relevance": "High",
        "ambiguity_analysis": "Ambiguous",
        "task_type": "Query",
        "decision": "Query"
      }}}}

* **示例 2 (写作任务):**
    * **历史:** "北联体和拉汶帝国是什么关系？" -> "..."
    * **问题:** "基于这个背景，写一个北联体军官和帝国贵族偶遇的短故事。"
    * **输出 (json):**
      {{{{
        "knowledge_base_relevance": "High",
        "ambiguity_analysis": "Clear",
        "task_type": "Creative",
        "decision": "Creative"
      }}}}

* **示例 3 (通用任务):**
    * **历史:** (空)
    * **问题:** "你好，你是谁？"
    * **输出 (json):**
      {{{{
        "knowledge_base_relevance": "None",
        "ambiguity_analysis": "Clear",
        "task_type": "General",
        "decision": "General"
      }}}}

[开始分析]
对话历史:\n\n{{history}}
新问题:\n\n{{input}}
"""
CLASSIFIER_PROMPT_TEMPLATE = os.getenv("CLASSIFIER_PROMPT_TEMPLATE", DEFAULT_CLASSIFIER_PROMPT_TEMPLATE)


# --- 多轮对话配置 ---
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20")) # 用于上下文的最大历史消息数 (用户+助手)

# 查询重写模板
# 环境变量名: REWRITE_PROMPT_TEMPLATE
DEFAULT_REWRITE_PROMPT_TEMPLATE = """根据下方提供的“对话历史”和“后续问题”，将“后续问题”改写为一个**完全独立、不依赖任何上下文**的完整问题。\n如果“后续问题”本身已经很完整，则直接返回它。\n\n对话历史:\n{history}\n\n后续问题:\n{query}\n\n重写后的独立问题:"""
REWRITE_PROMPT_TEMPLATE = os.getenv("REWRITE_PROMPT_TEMPLATE", DEFAULT_REWRITE_PROMPT_TEMPLATE)

# RAG 问答模板
# 环境变量名: HISTORY_AWARE_PROMPT_TEMPLATE
DEFAULT_HISTORY_AWARE_PROMPT_TEMPLATE = """参考资料：\n\n{context}\n\n---\n\n请根据以上参考资料，并结合你的知识，回答以下问题。\n\n在回答中，按照 SYSTEM_PROMPT 中的指令，使用 `[来源 n]` 的格式来引用使用的具体参考资料。\n\n例如："这是... [来源 1]。"。\n\n对多个来源，不要使用"来源[1]至[9]"这样概括，而是逐一列出，例如"来源[1]""来源[2]""来源[3]"。\n\n问题：\n\n{query}"""
HISTORY_AWARE_PROMPT_TEMPLATE = os.getenv("HISTORY_AWARE_PROMPT_TEMPLATE", DEFAULT_HISTORY_AWARE_PROMPT_TEMPLATE)

# --- RAG/检索参数 ---
TOP_K = int(os.getenv("TOP_K", "12"))
K = int(os.getenv("K", "3"))
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