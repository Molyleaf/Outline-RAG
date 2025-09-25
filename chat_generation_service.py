import os
from typing import List
from app.http_client import http_post

CHAT_API_URL = os.getenv("CHAT_API_URL", "").rstrip("/")
CHAT_API_TOKEN = os.getenv("CHAT_API_TOKEN", "")

def chat_generate(system_prompt: str, messages: List[dict]) -> str:
    headers = {"Authorization": f"Bearer {CHAT_API_TOKEN}"} if CHAT_API_TOKEN else {}
    payload = {
        "model": "chat-default",
        "messages": [{"role":"system","content":system_prompt}] + messages,
        "temperature": 0.2,
    }
    resp = http_post(f"{CHAT_API_URL}/chat/completions", payload, headers=headers)
    # Expected OpenAI-like: { choices: [ { message: { content: "..." } } ] }
    choices = resp.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""
