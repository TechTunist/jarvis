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


def _next_id(scene: dict) -> int:
    n = 0
    for p in scene.get("parts") or []:
        raw = str(p.get("id") or "").lstrip("p")
        if raw.isdigit():
            n = max(n, int(raw))
        name = str(p.get("name") or "")
        m = name.rsplit(" ", 1)
        if len(m) == 2 and m[1].isdigit():
            n = max(n, int(m[1]))
    return n + 1


def add_board(
    scene: dict,
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    name: str = "",
    upright: bool = False,
    x_mm: float | None = None,
    y_mm: float | None = None,
    z_mm: float | None = None,
    rx_deg: float = 0.0,
    ry_deg: float = 0.0,
    rz_deg: float = 0.0,
) -> dict:
    parts = list(scene.get("parts") or [])
    n = _next_id(scene)
    if y_mm is None:
        y = 0.0
        for p in parts:
            y = max(y, float(p.get("y_mm") or 0) + float(p.get("width_mm") or 0) + 20)
        y_mm = y if parts else 0.0
    part = {
        "id": f"p{n}",
        "kind": "board",
        "name": name or f"board {n}",
        "length_mm": round(float(length_mm), 2),
        "width_mm": round(float(width_mm), 2),
        "thickness_mm": round(float(thickness_mm), 2),
        "x_mm": round(float(x_mm or 0.0), 2),
        "y_mm": round(float(y_mm), 2),
        "z_mm": round(float(z_mm or 0.0), 2),
        "rx_deg": round(float(rx_deg or 0.0), 2),
        "ry_deg": round(float(ry_deg or 0.0), 2),
        "rz_deg": round(float(rz_deg or 0.0), 2),
        "upright": bool(upright),
    }
    parts.append(part)
    scene["parts"] = parts
    scene["units"] = "mm"
    return part


def duplicate_part(
    scene: dict,
    part: dict,
    dx_mm: float = 0.0,
    dy_mm: float = 0.0,
    dz_mm: float = 0.0,
) -> dict:
    return add_board(
        scene,
        float(part.get("length_mm") or 0),
        float(part.get("width_mm") or 0),
        float(part.get("thickness_mm") or 0),
        upright=bool(part.get("upright")),
        x_mm=float(part.get("x_mm") or 0) + dx_mm,
        y_mm=float(part.get("y_mm") or 0) + dy_mm,
        z_mm=float(part.get("z_mm") or 0) + dz_mm,
        rx_deg=float(part.get("rx_deg") or 0),
        ry_deg=float(part.get("ry_deg") or 0),
        rz_deg=float(part.get("rz_deg") or 0),
    )


def move_part(
    part: dict,
    *,
    x_mm: float | None = None,
    y_mm: float | None = None,
    z_mm: float | None = None,
    dx_mm: float = 0.0,
    dy_mm: float = 0.0,
    dz_mm: float = 0.0,
) -> dict:
    if x_mm is not None:
        part["x_mm"] = round(float(x_mm), 2)
    else:
        part["x_mm"] = round(float(part.get("x_mm") or 0) + dx_mm, 2)
    if y_mm is not None:
        part["y_mm"] = round(float(y_mm), 2)
    else:
        part["y_mm"] = round(float(part.get("y_mm") or 0) + dy_mm, 2)
    if z_mm is not None:
        part["z_mm"] = round(float(z_mm), 2)
    else:
        part["z_mm"] = round(float(part.get("z_mm") or 0) + dz_mm, 2)
    return part


def rotate_part(
    part: dict,
    *,
    upright: bool | None = None,
    rx_deg: float | None = None,
    ry_deg: float | None = None,
    rz_deg: float | None = None,
) -> dict:
    if upright is not None:
        part["upright"] = bool(upright)
    if rx_deg is not None:
        part["rx_deg"] = round(float(rx_deg), 2)
    if ry_deg is not None:
        part["ry_deg"] = round(float(ry_deg), 2)
    if rz_deg is not None:
        part["rz_deg"] = round(float(rz_deg), 2)
    return part


def resize_part(
    part: dict,
    *,
    length_mm: float | None = None,
    width_mm: float | None = None,
    thickness_mm: float | None = None,
) -> dict:
    if length_mm is not None:
        part["length_mm"] = round(float(length_mm), 2)
    if width_mm is not None:
        part["width_mm"] = round(float(width_mm), 2)
    if thickness_mm is not None:
        part["thickness_mm"] = round(float(thickness_mm), 2)
    return part


def _num(body: dict, *keys: str) -> float | None:
    for k in keys:
        if k in body and body[k] is not None and str(body[k]) != "":
            try:
                return float(body[k])
            except (TypeError, ValueError):
                return None
    return None


def apply_op(scene: dict, op: dict) -> str:
    name = str(op.get("op") or "").lower()
    if name == "clear":
        scene["parts"] = []
        return "cleared the bench"
    n = op.get("n")
    if n is not None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = None
    ident = str(op.get("id") or op.get("name") or "")
    if name == "add":
        part = add_board(
            scene,
            float(op["length_mm"]),
            float(op.get("width_mm") or 70),
            float(op.get("thickness_mm") or 15),
            str(op.get("name") or ""),
            upright=bool(op.get("upright")),
            x_mm=_num(op, "x_mm"),
            y_mm=_num(op, "y_mm"),
            z_mm=_num(op, "z_mm"),
            rx_deg=_num(op, "rx_deg") or 0.0,
            ry_deg=_num(op, "ry_deg") or 0.0,
            rz_deg=_num(op, "rz_deg") or 0.0,
        )
        return f"added {part['name']}"
    part = find_part(scene, n=n, ident=ident)
    if part is None:
        raise ValueError("no such board")
    if name == "duplicate":
        copy = duplicate_part(
            scene,
            part,
            dx_mm=_num(op, "dx_mm") or 0.0,
            dy_mm=_num(op, "dy_mm") or 0.0,
            dz_mm=_num(op, "dz_mm") or 0.0,
        )
        return f"duplicated {part.get('name')} as {copy['name']}"
    if name == "move":
        move_part(
            part,
            x_mm=_num(op, "x_mm"),
            y_mm=_num(op, "y_mm"),
            z_mm=_num(op, "z_mm"),
            dx_mm=_num(op, "dx_mm") or 0.0,
            dy_mm=_num(op, "dy_mm") or 0.0,
            dz_mm=_num(op, "dz_mm") or 0.0,
        )
        return f"moved {part.get('name')}"
    if name in ("rotate", "orient"):
        up = op.get("upright")
        rotate_part(
            part,
            upright=None if up is None else bool(up),
            rx_deg=_num(op, "rx_deg"),
            ry_deg=_num(op, "ry_deg"),
            rz_deg=_num(op, "rz_deg"),
        )
        how = "vertical" if part.get("upright") else "flat"
        return f"{part.get('name')} {how}"
    if name == "resize":
        resize_part(
            part,
            length_mm=_num(op, "length_mm"),
            width_mm=_num(op, "width_mm"),
            thickness_mm=_num(op, "thickness_mm"),
        )
        return f"resized {part.get('name')}"
    if name == "delete":
        label = part.get("name") or part.get("id")
        delete_part(scene, part)
        return f"removed {label}"
    raise ValueError(f"unknown op {name!r}")


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
            self._json({"ok": True, "api": 3})
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
                    float(body.get("width_mm") or 70),
                    float(body.get("thickness_mm") or 15),
                    str(body.get("name") or ""),
                    upright=bool(body.get("upright")),
                    x_mm=body.get("x_mm"),
                    y_mm=body.get("y_mm"),
                    z_mm=body.get("z_mm"),
                    rx_deg=float(body.get("rx_deg") or 0),
                    ry_deg=float(body.get("ry_deg") or 0),
                    rz_deg=float(body.get("rz_deg") or 0),
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
        if path in ("/api/ops", "/api/command"):
            notes: list[str] = []
            try:
                for op in body.get("ops") or [body]:
                    if not op or not op.get("op"):
                        continue
                    notes.append(apply_op(scene, op))
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": scene})
            return
        if path == "/api/duplicate":
            try:
                notes = [apply_op(scene, {"op": "duplicate", **body})]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": scene})
            return
        if path == "/api/move":
            try:
                notes = [apply_op(scene, {"op": "move", **body})]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": scene})
            return
        if path == "/api/resize":
            try:
                notes = [apply_op(scene, {"op": "resize", **body})]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": scene})
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
