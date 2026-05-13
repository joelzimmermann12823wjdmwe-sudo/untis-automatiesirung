"""
Web-Service-Wrapper für den Untis-Monitor (Render Web Service).
Startet einen minimale HTTP-Server (Health-Check) und den Monitor im Hintergrund.
"""
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from untis_monitor import log, run as run_monitor

PORT = int(os.getenv("PORT", "8000"))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        log.debug("HTTP %s", format % args)


def run_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    log.info("Health-Server läuft auf Port %d", PORT)
    server.serve_forever()


if __name__ == "__main__":
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()

    run_http()
