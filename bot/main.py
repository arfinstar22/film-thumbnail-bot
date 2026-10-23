import asyncio
import logging
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

from pyrogram import idle
from pyrogram.errors import FloodWait

from .handlers import app, on_bot_startup

logging.basicConfig(level=logging.INFO, stream=sys.stdout)


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/keepalive", "/ping-supabase"):
            import json
            from .handlers import _engine
            res = {"success": False, "error": "Engine not ready"}
            if _engine and hasattr(_engine, "cache"):
                res = _engine.cache.ping_supabase_keepalive()
            code = 200 if res.get("success") else 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Silence noisy request logs


def run_health_server():
    try:
        port = int(os.getenv("PORT", "8080").strip())
    except (ValueError, AttributeError):
        port = 8080
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logging.info("Health check server active on port %s", port)
        server.serve_forever()
    except Exception as e:
        logging.warning("Could not start health check server on port %s: %s", port, e)


def run_self_ping():
    """Ping own health endpoint every 10 min to prevent Render free-tier spin-down (15 min timeout)."""
    time.sleep(30)  # Wait for health server to start
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    port = os.getenv("PORT", "8080").strip()
    targets = [f"http://localhost:{port}/"]
    if render_url:
        targets.append(f"{render_url.rstrip('/')}/")
    while True:
        for url in targets:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SelfPing/1.0"})
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass
        time.sleep(600)  # 10 minutes



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
        threading.Thread(target=run_self_ping, daemon=True).start()
    run_bot()