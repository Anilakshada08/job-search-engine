"""Serve ONLY the dashboard (index.html) over HTTP, e.g. behind a Cloudflare tunnel.

Every other path returns 404, so nothing else in this folder (config/profile.yaml, .env, ...)
can ever be fetched. The file is re-read on each request, and open pages reload themselves
within a few seconds of index.html changing. With --git-pull-minutes the server also pulls
main from GitHub on a timer, so pushes from any machine show up without a restart.

    python scripts/serve_dashboard.py                         # http://127.0.0.1:8080
    python scripts/serve_dashboard.py --git-pull-minutes 5
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DASHBOARD = REPO / "index.html"
VERSION_PATH = "/__dashboard_version"

# Injected before </body>: polls the version endpoint and reloads when the file changes.
LIVE_RELOAD = (
    "<script>(function(){var v=null;function c(){fetch('" + VERSION_PATH + "',{cache:'no-store'})"
    ".then(function(r){return r.text()}).then(function(t){if(v&&t&&t!==v){location.reload()}v=t})"
    ".catch(function(){})}c();setInterval(c,15000)})();</script>"
)


def version() -> str:
    try:
        return hashlib.sha256(DASHBOARD.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "dashboard"
    sys_version = ""

    def do_GET(self) -> None:
        self._respond(send_body=True)

    def do_HEAD(self) -> None:
        self._respond(send_body=False)

    def _respond(self, send_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        if path == VERSION_PATH:
            self._send(version().encode(), "text/plain; charset=utf-8", send_body)
            return
        if path not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            html = DASHBOARD.read_text(encoding="utf-8")
        except OSError:
            self.send_error(503, "dashboard not available")
            return
        idx = html.lower().rfind("</body>")
        html = html[:idx] + LIVE_RELOAD + html[idx:] if idx != -1 else html + LIVE_RELOAD
        self._send(html.encode("utf-8"), "text/html; charset=utf-8", send_body)

    def _send(self, body: bytes, ctype: str, send_body: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_POST(self) -> None:  # read-only server
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        pass


def git_pull_loop(minutes: float) -> None:
    """Fast-forward main from GitHub so pushes from the scheduled runs appear automatically."""
    while True:
        time.sleep(minutes * 60)
        try:
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO,
                                    capture_output=True, text=True, timeout=30).stdout.strip()
            if branch == "main":
                subprocess.run(["git", "pull", "--ff-only", "--quiet", "origin", "main"], cwd=REPO,
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            pass  # try again next cycle


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = only reachable through the tunnel")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--git-pull-minutes", type=float, default=0, help="pull main from GitHub every N minutes (0 = off)")
    args = ap.parse_args()
    if args.git_pull_minutes > 0:
        threading.Thread(target=git_pull_loop, args=(args.git_pull_minutes,), daemon=True).start()
    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Serving {DASHBOARD.name} on http://{args.host}:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
