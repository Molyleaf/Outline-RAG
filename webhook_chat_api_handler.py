import os
import json
from urllib.parse import parse_qs
from app.web.views import handle_index, handle_chat_api, handle_admin_sync_full, handle_webhook_outline

BASE_PATH = os.getenv("BASE_PATH", "/chat").rstrip("/")

def respond_json(start_response, status_code, obj):
    data = json.dumps(obj).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(data)))]
    start_response(f"{status_code} OK" if status_code == 200 else f"{status_code} ERROR", headers)
    return [data]

def respond_html(start_response, html):
    data = html.encode("utf-8")
    headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data)))]
    start_response("200 OK", headers)
    return [data]

def parse_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except:
        length = 0
    body = environ["wsgi.input"].read(length) if length > 0 else b""
    ctype = environ.get("CONTENT_TYPE", "")
    if "application/json" in ctype:
        try:
            return json.loads(body.decode("utf-8"))
        except:
            return {}
    elif "application/x-www-form-urlencoded" in ctype:
        return {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    else:
        try:
            return json.loads(body.decode("utf-8"))
        except:
            return {}

def app(environ, start_response):
    method = environ["REQUEST_METHOD"].upper()
    path = environ.get("PATH_INFO", "")
    if path == "/":
        # redirect to /chat
        start_response("302 Found", [("Location", f"{BASE_PATH}/")])
        return [b""]

    # Static single page under BASE_PATH
    if path == f"{BASE_PATH}" or path == f"{BASE_PATH}/":
        return respond_html(start_response, handle_index())

    # APIs
    if path == f"{BASE_PATH}/api/chat" and method == "POST":
        body = parse_body(environ)
        return respond_json(start_response, 200, handle_chat_api(body))

    if path == f"{BASE_PATH}/admin/sync_full" and method in ("POST", "GET"):
        return respond_json(start_response, 200, handle_admin_sync_full())

    # Webhook (Outline can be configured to POST here)
    if path == f"{BASE_PATH}/webhook/outline" and method == "POST":
        body = parse_body(environ)
        return respond_json(start_response, 200, handle_webhook_outline(body))

    # Not found
    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"Not Found"]
