import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "http://127.0.0.1:8081")
USE_LOCAL_API = bool(API_ID and API_HASH)
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(2 * 1024**3)))
TMP_DIR = os.getenv("TMP_DIR", "/tmp/thumbbot")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN belum diisi. Lihat .env.example")
