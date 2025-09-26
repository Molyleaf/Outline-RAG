# 基于 Python 3.13 轻量镜像
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN set -eux; \
    # apt-get update; \
    # apt-get install -y --no-install-recommends ca-certificates; \
    # rm -rf /var/lib/apt/lists/*; \
    codename="$(. /etc/os-release; echo "$VERSION_CODENAME")"; \
    rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; \
    : > /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian/ %s main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian/ %s-updates main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian-security %s-security main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    printf "deb https://mirrors.nju.edu.cn/debian/ %s-backports main contrib non-free non-free-firmware\n" "$codename" >> /etc/apt/sources.list; \
    apt-get update

# 系统依赖：psycopg2 需要 libpq 和 build 组件
RUN apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户 outline(2000:2000)
RUN groupadd -g 2000 outline && useradd -m -u 2000 -g 2000 outline

WORKDIR /app

# 使用南京大学 PyPI 镜像作为默认源，并设置合理的超时与重试
RUN mkdir -p /etc/pip && \
    printf "[global]\nindex-url = https://mirrors.nju.edu.cn/pypi/web/simple\nextra-index-url = https://pypi.org/simple\ntrusted-host = mirrors.nju.edu.cn\ntimeout = 30\nretries = 3\n" > /etc/pip/pip.conf

# 预先复制依赖清单并安装（利用缓存）
COPY requirements.txt /app/requirements.txt
RUN python -m pip install -i https://mirrors.nju.edu.cn/pypi/web/simple --no-cache-dir -r /app/requirements.txt

# 复制应用代码与静态资源
COPY app.py /app/app.py
COPY static /app/static

# 创建可持久化目录并授权（用于附件与归档）
RUN mkdir -p /app/data/attachments /app/data/archive && chown -R 2000:2000 /app
USER 2000:2000

EXPOSE 8080

CMD ["python", "app.py"]
