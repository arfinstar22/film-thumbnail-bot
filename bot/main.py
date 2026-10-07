import asyncio
import logging
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from pyrogram import idle
from pyrogram.errors import FloodWait

from .handlers import app, on_bot_startup

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


async def start_with_hydration():
    await app.start()
    logging.info("Bot thumbnail film berjalan & siap melayani!")
    asyncio.create_task(on_bot_startup(app))
    await idle()
    await app.stop()


def run_bot():
    while True:
        try:
            app.run(start_with_hydration())
            break
        except FloodWait as e:
            wait_time = int(e.value)
            mins = wait_time / 60
            logging.warning(
                f"⚠️ Telegram FloodWait terdeteksi: Perlu menunggu {wait_time} detik (~{mins:.1f} menit).\n"
                f"ℹ️ Web server di port {os.getenv('PORT', '10000')} TETAP AKTIF menjaga agar Render TIDAK crash-loop!"
            )
            time.sleep(wait_time + 5)
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logging.exception(f"Error pada bot: {e}")
            time.sleep(5)


if __name__ == "__main__":
    if os.getenv("PORT"):
        threading.Thread(target=run_health_server, daemon=True).start()
    run_bot()