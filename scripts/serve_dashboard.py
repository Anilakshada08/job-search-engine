"""Serve ONLY the dashboard (index.html) over HTTP, e.g. behind a Cloudflare tunnel.

Every other path returns 404, so nothing else in this folder (config/profile.yaml, .env, ...)
can ever be fetched. The file is re-read on each request, so dashboard updates show up live.

    python scripts/serve_dashboard.py            # http://127.0.0.1:8080
    python scripts/serve_dashboard.py --port 9000
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "index.html"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "dashboard"
    sys_version = ""

    def do_GET(self) -> None:
        self._respond(send_body=True)

    def do_HEAD(self) -> None:
        self._respond(send_body=False)

    def _respond(self, send_body: bool) -> None:
        if self.path.split("?", 1)[0] not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            body = DASHBOARD.read_bytes()
        except OSError:
            self.send_error(503, "dashboard not available")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_POST(self) -> None:  # read-only server
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = only reachable through the tunnel")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Serving {DASHBOARD.name} on http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
