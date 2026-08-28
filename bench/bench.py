#!/usr/bin/env python3
"""Millimetre timber bench. HTTP + three.js. Jarvis POSTs boards; you orbit them."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENDOR = ROOT / "receptionist" / "hud" / "vendor"
PORT = 8770


def scene_path(data_dir: Path) -> Path:
    dest = data_dir / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    return dest / "scene.json"


def load_scene(path: Path) -> dict:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("parts"), list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"units": "mm", "parts": []}


def save_scene(path: Path, scene: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")


def add_board(
    scene: dict,
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    name: str = "",
    upright: bool = False,
) -> dict:
    parts = list(scene.get("parts") or [])
    n = len(parts) + 1
    y = 0.0
    for p in parts:
        y = max(y, float(p.get("y_mm") or 0) + float(p.get("width_mm") or 0) + 20)
    part = {
        "id": f"p{n}",
        "kind": "board",
        "name": name or f"board {n}",
        "length_mm": round(float(length_mm), 2),
        "width_mm": round(float(width_mm), 2),
        "thickness_mm": round(float(thickness_mm), 2),
        "x_mm": 0.0,
        "y_mm": y,
        "z_mm": 0.0,
        "upright": bool(upright),
    }
    parts.append(part)
    scene["parts"] = parts
    scene["units"] = "mm"
    return part


def find_part(scene: dict, n: int | None = None, ident: str = "") -> dict | None:
    parts = list(scene.get("parts") or [])
    if not parts:
        return None
    if ident:
        key = ident.strip().lower()
        for p in parts:
            if key in {str(p.get("id") or "").lower(), str(p.get("name") or "").lower()}:
                return p
    if n is not None:
        for p in parts:
            if str(p.get("id") or "") == f"p{n}":
                return p
            name = str(p.get("name") or "").lower()
            if name == f"board {n}" or name.endswith(f" {n}"):
                return p
        if 1 <= n <= len(parts):
            return parts[n - 1]
    return parts[-1]


def set_upright(part: dict, upright: bool = True) -> dict:
    part["upright"] = bool(upright)
    return part


def delete_part(scene: dict, part: dict) -> bool:
    parts = list(scene.get("parts") or [])
    keep = [p for p in parts if p is not part and p.get("id") != part.get("id")]
    if len(keep) == len(parts):
        return False
    scene["parts"] = keep
    return True


class Handler(BaseHTTPRequestHandler):
    data_dir: Path = Path.home() / ".jarvis"

    def log_message(self, *a) -> None:
        return

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200) -> None:
        self._send(json.dumps(data).encode(), "application/json", code)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"ok": True, "api": 2})
            return
        if path == "/api/scene":
            self._json(load_scene(scene_path(self.data_dir)))
            return
        if path in ("/", "/index.html"):
            target = HERE / "index.html"
        elif path == "/bench.js":
            target = HERE / "bench.js"
        elif path.startswith("/vendor/"):
            target = (VENDOR / path[len("/vendor/") :]).resolve()
            if VENDOR not in target.parents and target != VENDOR:
                self._send(b"not found", "text/plain", 404)
                return
        else:
            self._send(b"not found", "text/plain", 404)
            return
        if not target.is_file():
            self._send(b"not found", "text/plain", 404)
            return
        ctypes = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json",
        }
        self._send(target.read_bytes(), ctypes.get(target.suffix.lower(), "application/octet-stream"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(n) if n > 0 else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        dest = scene_path(self.data_dir)
        scene = load_scene(dest)
        if path == "/api/clear":
            scene["parts"] = []
            save_scene(dest, scene)
            self._json(scene)
            return
        if path == "/api/parts":
            kind = str(body.get("kind") or "board").lower()
            if kind != "board":
                self._json({"error": "only board for now"}, 400)
                return
            try:
                part = add_board(
                    scene,
                    float(body["length_mm"]),
                    float(body["width_mm"]),
                    float(body["thickness_mm"]),
                    str(body.get("name") or ""),
                    upright=bool(body.get("upright")),
                )
            except (KeyError, TypeError, ValueError):
                self._json({"error": "need length_mm, width_mm, thickness_mm"}, 400)
                return
            save_scene(dest, scene)
            self._json({"part": part, "scene": scene})
            return
        if path == "/api/orient":
            part = find_part(
                scene,
                n=int(body["n"]) if str(body.get("n") or "").isdigit() else None,
                ident=str(body.get("id") or body.get("name") or ""),
            )
            if part is None:
                self._json({"error": "no such board"}, 404)
                return
            set_upright(part, body.get("upright", True) is not False)
            save_scene(dest, scene)
            self._json({"part": part, "scene": scene})
            return
        if path == "/api/delete":
            part = find_part(
                scene,
                n=int(body["n"]) if str(body.get("n") or "").isdigit() else None,
                ident=str(body.get("id") or body.get("name") or ""),
            )
            if part is None:
                self._json({"error": "no such board"}, 404)
                return
            delete_part(scene, part)
            save_scene(dest, scene)
            self._json({"deleted": part.get("name") or part.get("id"), "scene": scene})
            return
        self._send(b"not found", "text/plain", 404)


def serve(data_dir: Path, port: int = PORT) -> ThreadingHTTPServer:
    Handler.data_dir = data_dir
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> None:
    p = argparse.ArgumentParser(description="Jarvis timber bench")
    p.add_argument("--data-dir", default=os.environ.get("JARVIS_HOME", str(Path.home() / ".jarvis")))
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()
    data = Path(args.data_dir).expanduser()
    data.mkdir(parents=True, exist_ok=True)
    Handler.data_dir = data
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    httpd.allow_reuse_address = True
    print(f"[bench] http://127.0.0.1:{args.port}/  data={data}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
