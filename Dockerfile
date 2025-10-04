# 基于 Python 3.13 轻量镜像
FROM python:3.13-slim

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 更新 APT 源为南京大学镜像
RUN set -eux; \
    codename="$(. /etc/os-release; echo "$VERSION_CODENAME")"; \
    rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; \
    : > /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian/ %s main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian/ %s-updates main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian-security %s-security main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian/ %s-backports main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    apt-get update

# 系统依赖
RUN apt-get install -y \
    build-essential gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -g 2000 outline && useradd -m -u 2000 -g 2000 outline

WORKDIR /app

# 配置 PyPI 镜像
RUN mkdir -p /etc/pip && \
    printf "[global]\nindex-url = https://mirrors.nju.edu.cn/pypi/web/simple\nextra-index-url = https://pypi.org/simple\ntrusted-host = mirrors.nju.edu.cn\ntimeout = 30\nretries = 3\n" > /etc/pip/pip.conf

# 安装依赖
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && . /opt/venv/bin/activate && \
    pip install -i https://mirrors.nju.edu.cn/pypi/web/simple --no-cache-dir -r /tmp/requirements.txt && \
    pip install -i https://mirrors.nju.edu.cn/pypi/web/simple --no-cache-dir gunicorn

ENV PATH="/opt/venv/bin:$PATH"

# 复制所有 .py 文件
COPY *.py /app/
# 复制 blueprints 目录
COPY blueprints /app/blueprints
# 复制静态资源目录
COPY static /app/static

# 创建可持久化目录并授权 (保持不变)
RUN mkdir -p /app/data/attachments /app/data/archive && chown -R 2000:2000 /app
USER 2000:2000

EXPOSE 8080

# CMD 命令保持不变，入口仍是 app.py 中的 app 实例
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", "-b", "0.0.0.0:8080", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "app:app"]