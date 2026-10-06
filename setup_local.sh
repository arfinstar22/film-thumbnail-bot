#!/bin/bash
set -e

echo "🎬 Film Thumbnail Bot - Setup Lokal"
echo "==================================="

# Install dependencies
echo ""
echo "[1/3] Menginstall dependencies sistem..."
sudo apt update -qq
sudo apt install -y -qq ffmpeg python3-pip curl git > /dev/null 2>&1
echo "✅ Dependencies terinstall"

# Install Python dependencies
echo ""
echo "[2/3] Menginstall Python dependencies..."
pip3 install --break-system-packages -r requirements.txt > /dev/null 2>&1 || pip install -r requirements.txt > /dev/null 2>&1
echo "✅ Python dependencies terinstall"

# Buat .env jika belum ada
if [ ! -f .env ]; then
    echo ""
    echo "[3/3] Membuat file .env..."
    cp .env.example .env
    echo "📝 File .env sudah dibuat. Edit dengan: nano .env"
else
    echo ""
    echo "[3/3] File .env sudah ada, skip."
fi

# Verifikasi
echo ""
echo "==================================="
echo "✅ Setup selesai!"
echo ""
echo "Sebelum jalan, isi .env dengan:"
echo "  - BOT_TOKEN: dari @BotFather"
echo "  - API_ID dan API_HASH: dari my.telegram.org"
echo ""
echo "Jalankan bot dengan: ./run_local.sh"
echo "==================================="