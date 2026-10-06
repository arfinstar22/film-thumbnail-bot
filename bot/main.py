import asyncio
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from pyrogram import idle
from pyrogram.errors import FloodWait

from .config import BOT_TOKEN, API_ID, API_HASH
from .handlers import app

logging.basicConfig(level=logging.INFO, stream=sys.stdout)


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Silence noisy request logs


def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info("Health check server active on port %s", port)
    server.serve_forever()


async def run_bot():
    while True:
        try:
            logging.info("Menghubungkan ke Telegram...")
            await app.start()
            logging.info("Bot thumbnail film berjalan & siap melayani!")

            try:
                session_str = await app.export_session_string()
                if session_str:
                    logging.info(
                        "\n==================================================\n"
                        "💡 TIPS RENDER: Tambahkan Environment Variable:\n"
                        f"SESSION_STRING = {session_str}\n"
                        "Untuk bypass login MTProto selamanya & anti FloodWait!\n"
                        "=================================================="
                    )
            except Exception:
                pass

            await idle()
            await app.stop()
            break
        except FloodWait as e:
            wait_time = int(e.value)
            mins = wait_time / 60
            logging.warning(
                f"⚠️ Telegram FloodWait terdeteksi: Perlu menunggu {wait_time} detik (~{mins:.1f} menit).\n"
                f"ℹ️ Web server di port {os.getenv('PORT', '10000')} TETAP AKTIF menjaga agar Render TIDAK crash-loop!\n"
                f"💡 TIPS INSTAN: Untuk langsung aktif tanpa menunggu, buka @BotFather -> /revoke bot Anda, lalu masukkan BOT_TOKEN baru ke Environment Variables Render."
            )
            await asyncio.sleep(wait_time + 5)
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logging.exception(f"Error pada bot: {e}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    if os.getenv("PORT"):
        threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot())