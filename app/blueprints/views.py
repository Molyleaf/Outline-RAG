"""旧前端视图占位模块。

项目已切换到 LightRAG 官方 WebUI，由 `main.py` 直接挂载 `/chat` 子应用。
保留本模块仅为兼容现有导入路径。
"""

from fastapi import APIRouter

views_router = APIRouter()
