import json
import ssl
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def http_post(url, payload, headers=None, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        raise RuntimeError(f"POST {url} failed: {e.code} {e.read().decode('utf-8', errors='ignore')}")
    except URLError as e:
        raise RuntimeError(f"POST {url} failed: {e}")

def http_get(url, headers=None, timeout=60):
    hdrs = {}
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs, method="GET")
    try:
        with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        raise RuntimeError(f"GET {url} failed: {e.code} {e.read().decode('utf-8', errors='ignore')}")
    except URLError as e:
        raise RuntimeError(f"GET {url} failed: {e}")
