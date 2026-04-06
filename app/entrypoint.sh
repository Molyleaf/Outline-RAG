#!/usr/bin/env sh
set -e

# 如果未显式提供 SECRET_KEY，则在启动主应用前随机生成一个
if [ -z "${SECRET_KEY}" ]; then
  SECRET_KEY="$(python - << 'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  export SECRET_KEY
fi

# LightRAG 默认使用本地文件存储，运行期建议单 worker。
UVICORN_PORT="${PORT:-8080}"
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

exec uvicorn --host "0.0.0.0" --port "${UVICORN_PORT}" --workers "${UVICORN_WORKERS}" "main:app"
