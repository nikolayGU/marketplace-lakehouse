"""Tiny HTTP surface: `/health` for the container, `/status` for a human, `/metrics` to scrape."""

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

EVENTS = Counter("replayer_events_total", "Replayed source events, by kind", ["kind"])
VIRTUAL_NOW = Gauge("replayer_virtual_now_seconds", "Virtual clock position, unix seconds")
PENDING = Gauge("replayer_pending_events", "Scheduled events not emitted yet")
SPEED = Gauge("replayer_speed", "Virtual seconds per real second")


def serve(port: int, status: Callable[[], dict[str, Any]]) -> ThreadingHTTPServer:
    """Start the server on its own thread and hand back the handle so callers can shut it down."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/metrics"):
                self._send(200, CONTENT_TYPE_LATEST, generate_latest())
            elif self.path.startswith("/status"):
                self._send(200, "application/json", json.dumps(status(), default=str).encode())
            elif self.path.startswith("/health"):
                self._send(200, "text/plain", b"ok\n")
            else:
                self._send(404, "text/plain", b"not found\n")

        def _send(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            """Silence per-request logging; the healthcheck alone would flood the log."""

    # Binds inside the container only; compose publishes it on ${BIND_IP}.
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
