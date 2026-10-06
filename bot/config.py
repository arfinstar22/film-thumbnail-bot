import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(2 * 1024**3)))
CHANNEL_WATERMARK = os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN belum diisi. Lihat .env.example")
if not API_ID or not API_HASH:
    raise RuntimeError("API_ID dan API_HASH harus diisi. Daftar di my.telegram.org")
