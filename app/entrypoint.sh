#!/bin/sh

# 1. 动态生成密钥
# 使用 Python 生成一个强随机的 32 字节 Hex 字符串
generated_key=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

# 2. 导出为环境变量
# 这样，随后启动的任何命令（包括 uvicorn 及其 worker）都能看到这个变量
export SECRET_KEY="$generated_key"

echo "Running with dynamically generated SECRET_KEY."

# 3. 执行 Docker CMD 传入的命令
# 使用 'exec' 是关键，它确保 uvicorn 替换当前 shell 成为 PID 1 进程，
# 从而能正确接收停止信号 (SIGTERM)
exec "$@"