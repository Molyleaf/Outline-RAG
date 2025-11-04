# --- 阶段 1: 构建器 ---
# [cite_start]基于 Python 3.13 轻量镜像 [cite: 1]
FROM python:3.13-slim-trixie AS builder

# 设置工作目录
WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP="app:app"
# 设置 FLASK_APP 环境变量以运行 assets 命令

# 默认使用 root 用户执行系统级操作
USER root

# 更换 APT 源
RUN rm -f /etc/apt/sources.list \
    && rm -rf /etc/apt/sources.list.d/
COPY sources.list /etc/apt/sources.list

RUN apt-get update && apt-get install -y \
    build-essential gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -g 1001 outline && useradd -m -u 1001 -g 1001 outline

# 复制需求文件
COPY requirements.txt .
# [cite_start]更改文件所有者为新用户 [cite: 2]
RUN chown 1001:1001 requirements.txt

# 切换到非 root 用户
USER 1001:1001

# 安装 Python 依赖（作为非 root 用户）
RUN pip config set global.index-url https://mirrors.pku.edu.cn/pypi/simple/ \
    [cite_start]&& pip install --no-cache-dir --user -r requirements.txt [cite: 4]

# 注意：--user 标志会把包安装到用户的主目录（例如 /home/outline/.local/bin）。
# 为了让 gunicorn 和 flask 命令能被找到，我们需要把这个路径加入 $PATH。
ENV PATH="/home/outline/.local/bin:${PATH}"

# 复制应用代码 (将 app/ 的内容复制到 /app)
COPY --chown=1001:1001 app/. /app/

# 作为非 root 用户预构建静态资源
RUN flask assets build


# --- 阶段 2: 最终镜像 ---
# [cite_start]基于 Python 3.13 轻量镜像 [cite: 1]
FROM python:3.13-slim-trixie

WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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

# (新) 从构建器阶段复制已包含预构建资源的应用代码
# 这一步现在会正确地复制 /app (包含 app.py, config.py 等)
COPY --from=builder --chown=1001:1001 /app /app

# (新) 关键步骤：移除原始的 JS 和 CSS 源文件
RUN rm -rf /app/static/js /app/static/css

# 创建可持久化目录并授权
# 确保整个 /app 目录都属于 outline 用户
RUN mkdir -p /app/data/attachments /app/data/archive \
    && chown -R 1001:1001 /app

# [cite_start]切换到非 root 用户来运行应用 [cite: 3]
USER 1001:1001

EXPOSE 8080

# [cite_start]CMD 命令保持不变 [cite: 3]
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", "-b", "0.0.0.0:8080", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "app:app"]