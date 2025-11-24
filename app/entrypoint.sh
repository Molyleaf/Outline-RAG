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

# 可选：允许通过环境变量覆盖端口和 worker 数
UVICORN_PORT="${PORT:-8080}"
UVICORN_WORKERS="${UVICORN_WORKERS:-2}"

exec uvicorn --host "0.0.0.0" --port "${UVICORN_PORT}" --workers "${UVICORN_WORKERS}" "main:app"