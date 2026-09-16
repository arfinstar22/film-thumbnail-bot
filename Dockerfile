FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Unduh telegram-bot-api terbaru (latest release)
RUN mkdir -p /opt/api && \
    cd /opt/api && \
    curl -L -o tgbapi.tar.gz "https://github.com/alexander-akulov/telegram-bot-api/releases/latest/download/telegram-bot-api-linux-amd64.tar.gz" && \
    tar -xzf tgbapi.tar.gz && \
    rm tgbapi.tar.gz


FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# FFmpeg + deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy telegram-bot-api binary
COPY --from=builder /opt/api/telegram-bot-api /usr/local/bin/telegram-bot-api
RUN chmod +x /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]