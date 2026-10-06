#!/bin/bash
set -e

echo "🎬 Menjalankan Film Thumbnail Bot (Pyrogram)..."
echo "==============================================="

if [ ! -f .env ]; then
    echo "❌ File .env belum ada. Buat dari .env.example & isi token."
    exit 1
fi

set -a
source .env
set +a

echo "🤖 Menjalankan bot... Tekan Ctrl+C untuk berhenti."
python3 -m bot.main