# --- 阶段 1: 构建器 ---
# 基于 Python 3.13 轻量镜像
FROM python:3.13-slim-trixie AS builder

WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP="app:app" \
    PYTHONPATH="/app"

# 默认使用 root 用户执行系统级操作
USER root

# 更换 APT 源
RUN rm -f /etc/apt/sources.list \
    && rm -rf /etc/apt/sources.list.d/
COPY sources.list /etc/apt/sources.list

# 安装系统依赖（作为 root），包括构建工具
RUN apt-get update && apt-get install -y \
    build-essential gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -g 1001 outline && useradd -m -u 1001 -g 1001 outline

# 复制需求文件
COPY requirements.txt .
# 更改文件所有者为新用户
RUN chown 1001:1001 requirements.txt

# 切换到非 root 用户
USER 1001:1001

ENV PATH="/home/outline/.local/bin:${PATH}"

# 安装 Python 依赖（作为非 root 用户）
RUN pip config set global.index-url https://mirrors.pku.edu.cn/pypi/simple/ \
    && pip install --no-cache-dir --user -r requirements.txt

COPY --chown=1001:1001 app/. /app/

ENV OUTLINE_WEBHOOK_SIGN=false \
    SECRET_KEY="123"

RUN flask assets build


# --- 阶段 2: 最终镜像 ---
# 基于 Python 3.13 轻量镜像
FROM python:3.13-slim-trixie

WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_DEBUG=0 \
    ASSETS_DEBUG=0

# 默认使用 root 用户执行系统级操作
USER root

# 更换 APT 源
RUN rm -f /etc/apt/sources.list \
    && rm -rf /etc/apt/sources.list.d/
COPY sources.list /etc/apt/sources.list

# (新) 只安装生产环境所需的系统依赖
RUN apt-get update && apt-get install -y \
    libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -g 1001 outline && useradd -m -u 1001 -g 1001 outline

# 切换到非 root 用户
USER 1001:1001

# (新) 从构建器阶段复制已安装的 Python 依赖
COPY --from=builder /home/outline/.local /home/outline/.local

# 设置 $PATH
ENV PATH="/home/outline/.local/bin:${PATH}"

# (新) 切换回 root 用户以复制应用代码并设置权限
USER root

# (*** 已修改 ***)
# 从构建器阶段复制已包含预构建资源的应用代码
COPY --from=builder --chown=1001:1001 /app /app/

# (*** 已修改 ***)
# 关键步骤：移除原始的 JS 和 CSS 源文件
RUN rm -rf /app/static/js /app/static/css /app/static/.webassets-cache

# (*** 已修改 ***)
# 创建可持久化目录并授权
RUN mkdir -p /app/data/attachments /app/data/archive \
    && chown -R 1001:1001 /app

# 切换到非 root 用户来运行应用
USER 1001:1001

EXPOSE 8080

# (*** 已修改 ***)
# CMD 命令保持不变，但它现在是在 /code 目录中运行
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", "-b", "0.0.0.0:8080", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "app:app"]