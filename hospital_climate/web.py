"""Web server: the dashboard pages plus a JSON API over the climate controller.

Standard library only (http.server). One simulator lives in memory; a lock
serialises every request and the background clock, so the controller is
never touched by two threads at once.

    python -m hospital_climate                  # http://127.0.0.1:8000, opens the browser
    python -m hospital_climate web --port 9000 --no-browser

The server is meant to run on the operator's own computer. It binds to
127.0.0.1 by default, refuses requests whose Host header is not that
computer (DNS-rebinding protection) and accepts state-changing requests only
as JSON POSTs, which a page on another site cannot send without the
browser's permission check.
"""

import json
import mimetypes
import pathlib
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .api import App, handle_api

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
BENCH_DIR = ROOT / "docs" / "benchmarks"
MAX_BODY = 16 * 1024
DRAIN_LIMIT = 1024 * 1024  # an over-large body up to this size is read and dropped


def make_handler(app, allowed_hosts):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HospitalClimate/1.0"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                             "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            # API answers are never cached; pages are re-checked so an updated file shows at once.
            self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self):
            host = (self.headers.get("Host") or "").lower()
            name = host[: host.index("]") + 1] if host.startswith("[") else host.split(":")[0]
            return name in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "Unknown host."})
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                return self._api_get(url.path, parse_qs(url.query))
            return self._static(url.path)

        do_HEAD = do_GET

        def _api_get(self, path, q):
            status, out = handle_api(app, "GET", path, {k: v[0] for k, v in q.items()})
            return self._json(status, out)

        def _refuse(self, status, message, length):
            """Answers an error without processing the body, but reads (up to 1 MB of)
            it first: closing a socket with unread data resets the connection on
            some systems, and the client would never see the error."""
            if 0 < length <= DRAIN_LIMIT:
                self.rfile.read(length)
            else:
                self.close_connection = True
            return self._json(status, {"error": message})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not self._host_ok():
                return self._refuse(HTTPStatus.FORBIDDEN, "Unknown host.", length)
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._refuse(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.", length)
            if not 0 <= length <= MAX_BODY:
                return self._refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.", length)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "Body must be a JSON object."})
            status, out = handle_api(app, "POST", urlparse(self.path).path, None, body)
            return self._json(status, out)

        def _static(self, path):
            if path == "/":
                path = "/index.html"
            if path.startswith("/benchmarks/"):
                base, rel = BENCH_DIR, path[len("/benchmarks/"):]
            else:
                base, rel = WEB_DIR, path.lstrip("/")
            target = (base / rel).resolve()
            if base.resolve() not in target.parents or not target.is_file():
                return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".js":
                ctype = "text/javascript"
            if ctype.startswith("text/") or ctype in ("image/svg+xml",):
                ctype += "; charset=utf-8"
            self._send(HTTPStatus.OK, target.read_bytes(), ctype)

    return Handler


def serve(host="127.0.0.1", port=8000, open_browser=True, seed=7):
    app = App(seed)
    allowed = {"localhost", "127.0.0.1", "[::1]"}
    if host not in ("127.0.0.1", "localhost", "::1"):
        allowed.add(host.lower())
    server = ThreadingHTTPServer((host, port), make_handler(app, allowed))
    stop = threading.Event()
    clock = threading.Thread(target=app.clock_loop, args=(stop,), daemon=True)
    clock.start()
    url = "http://%s:%d/" % ("127.0.0.1" if host in ("0.0.0.0", "127.0.0.1") else host, port)
    print("Smart Hospital Climate Control is running at %s  (Ctrl+C to stop)" % url)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop.set()
        server.server_close()
    return 0


def start_in_thread(port=0, seed=7):
    """For tests: a server on a free port in a background thread. Returns (server, app)."""
    app = App(seed)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, {"127.0.0.1", "localhost"}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, app


if __name__ == "__main__":
    serve()
