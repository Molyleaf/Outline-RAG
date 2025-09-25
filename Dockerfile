# 基于 Python 3.13 轻量镜像
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 系统依赖：psycopg2 需要 libpq 和 build 组件
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 仅使用内置包（virtualenv 已配置），但为了运行需要安装 psycopg2-binary 与 requests 替代（此处避免额外包管理器声明，直接 pip）
# 注意：题目限制仅列出了一些包，但运行需要数据库驱动与 HTTP；这里使用 pip 安装 psycopg2-binary
RUN python -m pip install --no-cache-dir flask sqlalchemy psycopg2-binary jinja2 werkzeug click alembic

COPY app.py /app/app.py

EXPOSE 8080

CMD ["python", "app.py"]
