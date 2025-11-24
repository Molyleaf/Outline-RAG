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

RUN flask assets build


# --- 阶段 2: 运行时依赖 (Runtime Python Deps) ---
# (*** 新增阶段 ***)
# 此阶段 *仅* 安装运行时依赖，以保持 /home/outline/.local 纯净
FROM python:3.13-slim-trixie AS runtime_builder

WORKDIR /app
ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER root
RUN rm -f /etc/apt/sources.list \
    && rm -rf /etc/apt/sources.list.d/
COPY sources.list /etc/apt/sources.list
# 仅安装构建 psycopg 所需的依赖
RUN apt-get update && apt-get install -y \
    build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1001 outline && useradd -m -u 1001 -g 1001 outline

# (*** 已修改 ***) 仅复制运行时需求
COPY requirements-runtime.txt .
RUN chown 1001:1001 requirements-runtime.txt

USER 1001:1001
ENV PATH="/home/outline/.local/bin:${PATH}"

# (*** 已修改 ***) 只安装 *运行时* 依赖
RUN pip config set global.index-url https://mirrors.pku.edu.cn/pypi/simple/ \
    && pip install --no-cache-dir --user -r requirements-runtime.txt


# --- 阶段 3: 最终镜像 ---
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

# 设置 $PATH
ENV PATH="/home/outline/.local/bin:${PATH}"

# (新) 切换回 root 用户以复制应用代码并设置权限
USER root

# (*** 已修改 ***) 从 'runtime_builder' 复制 *纯净的* 运行时依赖
COPY --from=runtime_builder /home/outline/.local /home/outline/.local
ENV PATH="/home/outline/.local/bin:${PATH}"

USER root
# (*** 已修改 ***) 从 'builder' 复制 *已构建好的* 应用代码
COPY --from=builder --chown=1001:1001 /app /app/

# (*** 已修改 ***)
# 创建可持久化目录并授权
RUN mkdir -p /app/data/attachments /app/data/archive \
    && chown -R 1001:1001 /app

# 切换到非 root 用户来运行应用
USER 1001:1001

EXPOSE 8080

# (ASYNC REFACTOR) 使用 uvicorn 启动 main:app
CMD ["/bin/sh", "-c", "python3 -c 'import secrets; open(\"/tmp/pigeon.key\", \"w\").write(secrets.token_hex(32))' && uvicorn --host 0.0.0.0 --port 8080 --workers 2 main:app"]