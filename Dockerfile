FROM python:3.13-slim-trixie AS builder

WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP="app:app" \
    PYTHONPATH="/app"

USER root
RUN rm -f /etc/apt/sources.list \
    && rm -rf /etc/apt/sources.list.d/
COPY sources.list /etc/apt/sources.list
RUN apt-get update && apt-get install -y \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1001 outline && useradd -m -u 1001 -g 1001 outline

COPY requirements.txt .
RUN chown 1001:1001 requirements.txt

USER 1001:1001
ENV PATH="/home/outline/.local/bin:${PATH}"
RUN pip config set global.index-url https://mirrors.zju.edu.cn/pypi/web/simple/ \
    && pip install --no-cache-dir --user -r requirements.txt

COPY --chown=1001:1001 app/. /app/
RUN flask assets build


FROM python:3.13-slim-trixie

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_DEBUG=0 \
    ASSETS_DEBUG=0 \
    PATH="/home/outline/.local/bin:${PATH}"

RUN groupadd -g 1001 outline && useradd -m -u 1001 -g 1001 outline

COPY --from=builder /home/outline/.local /home/outline/.local
COPY --from=builder --chown=1001:1001 /app /app/

RUN mkdir -p /app/data/lightrag /app/data/lightrag_inputs \
    && chown -R 1001:1001 /app

USER 1001:1001

EXPOSE 8080

CMD ["/app/entrypoint.sh"]
