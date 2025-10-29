# 基于 Python 3.13 轻量镜像
FROM python:3.13-slim-trixie

# 设置工作目录
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

# 安装系统依赖（作为 root）
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

# 安装 Python 依赖（作为非 root 用户）
RUN pip config set global.index-url https://mirrors.pku.edu.cn/pypi/simple/ \
    && pip install --no-cache-dir --user -r requirements.txt

# 注意：--user 标志会把包安装到用户的主目录（例如 /home/outline/.local/bin）。
# 为了让 gunicorn 能被 CMD 找到，我们需要把这个路径加入 $PATH。
ENV PATH="/home/outline/.local/bin:${PATH}"

# 切换回 root 用户进行系统清理
USER root
RUN apt-get remove --purge -y build-essential gcc \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# 再次设置工作目录（好习惯）
WORKDIR /app

# 复制应用代码
COPY app/ /app/

# 创建可持久化目录并授权
# 确保整个 /app 目录都属于 outline 用户
RUN mkdir -p /app/data/attachments /app/data/archive \
    && chown -R 1001:1001 /app

# 切换到非 root 用户来运行应用
USER 1001:1001

EXPOSE 8080

# CMD 命令保持不变，入口仍是 app.py 中的 app 实例
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", "-b", "0.0.0.0:8080", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "app:app"]