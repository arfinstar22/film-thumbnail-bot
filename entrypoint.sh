#!/bin/sh
set -e

# Baca env vars
API_ID="${API_ID:-}"
API_HASH="${API_HASH:-}"
TMP_DIR="${TMP_DIR:-/tmp/thumbbot}"
LOCAL_API_URL="${LOCAL_API_URL:-http://127.0.0.1:8081}"

mkdir -p "${TMP_DIR}"

# Start telegram-bot-api in background
echo "Memulai Telegram Bot API..."
telegram-bot-api \
    --api-id="$API_ID" \
    --api-hash="$API_HASH" \
    --local \
    --http-port=8081 \
    --dir="${TMP_DIR}/bot-api-data" &

# Tunggu Bot API ready
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:8081" > /dev/null 2>&1; then
        echo "Telegram Bot API ready!"
        break
    fi
    sleep 1
done

# Start bot
echo "Memulai bot..."
exec python -m bot.main "$@"