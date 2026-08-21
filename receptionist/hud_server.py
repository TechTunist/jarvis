"""Tiny localhost HUD for Talk. Iron Man–style page at http://127.0.0.1:8791/"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HUD_DIR = Path(__file__).resolve().parent / "hud"
PORT = 8791

_state = {"state": "idle", "level": 0.0, "line": "", "name": "J.A.R.V.I.S."}
_lock = threading.Lock()
_httpd: ThreadingHTTPServer | None = None


def set_state(state: str, line: str = "", level: float = 0.0) -> None:
    with _lock:
        _state["state"] = state
        _state["line"] = (line or "")[:80]
        _state["level"] = float(level)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/state":
            with _lock:
                body = json.dumps(_state).encode()
            self._send(body, "application/json")
            return
        if path in ("/", "/index.html"):
            target = HUD_DIR / "index.html"
        else:
            target = (HUD_DIR / path.lstrip("/")).resolve()
            if HUD_DIR not in target.parents and target != HUD_DIR:
                self._send(b"not found", "text/plain", 404)
                return
        if not target.is_file():
            self._send(b"not found", "text/plain", 404)
            return
        ctype = "text/html" if target.suffix == ".html" else "application/octet-stream"
        self._send(target.read_bytes(), ctype)

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a) -> None:
        pass


def start_hud(open_browser: bool = True) -> None:
    global _httpd
    _httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    _httpd.allow_reuse_address = True
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"[hud] {url}  (F for fullscreen)", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()


def stop_hud() -> None:
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd = None
