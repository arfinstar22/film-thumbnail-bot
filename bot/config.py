import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(2 * 1024**3)))
CHANNEL_WATERMARK = os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()
DEFAULT_REQUEST_LINK = os.getenv("DEFAULT_REQUEST_LINK", "").strip()
VAULT_CHANNEL = os.getenv("VAULT_CHANNEL", "").strip()
ADMIN_USER_IDS = [
    1166479771,
    *[int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit() and int(x.strip()) != 1166479771]
]
ABSOLUTE_ADMIN_USER_IDS = {
    1166479771,
    *[int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()]
}
ABSOLUTE_ADMIN_USERNAMES = {
    "dxstar22", "dxtstar22",
    *[u.strip().lower().lstrip("@") for u in os.getenv("ADMIN_USERNAMES", "").split(",") if u.strip()]
}


if not BOT_TOKEN and not SESSION_STRING:
    raise RuntimeError("BOT_TOKEN atau SESSION_STRING harus diisi. Lihat .env.example")
if not API_ID or not API_HASH:
    raise RuntimeError("API_ID dan API_HASH harus diisi. Daftar di my.telegram.org")
