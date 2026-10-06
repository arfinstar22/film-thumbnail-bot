import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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


if __name__ == "__main__":
    if os.getenv("PORT"):
        threading.Thread(target=run_health_server, daemon=True).start()
    logging.info("Bot thumbnail film berjalan...")
    app.run()