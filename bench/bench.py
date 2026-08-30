#!/usr/bin/env python3
"""Millimetre timber bench. HTTP + three.js. Jarvis POSTs boards; you orbit them."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _repo_first() -> None:
    """Talk sets PYTHONPATH to the repo, but running this file as a script
    still puts bench/ first, so `import bench` would load this file."""
    root = str(ROOT)
    sys.path[:] = [p for p in sys.path if p != root]
    sys.path.insert(0, root)


_repo_first()
from bench.design import (
    Brief,
    StockItem,
    hints_from_scene,
    hints_to_scene,
    layout,
    merge_hints,
    merge_site,
    merge_stock,
    site_from_scene,
    site_to_scene,
    stock_from_scene,
    stock_to_scene,
)

VENDOR = ROOT / "receptionist" / "hud" / "vendor"
PORT = 8770


_SLUG = re.compile(r"[^a-z0-9]+")
PROJECT_OPS = frozenset({"save", "save_as", "save_project", "new", "new_project", "load", "switch", "list_projects", "projects"})
_LOAD_ALIASES = {
    "first": "first",
    "first one": "first",
    "first project": "first",
    "previous": "previous",
    "previous one": "previous",
    "previous project": "previous",
    "other": "previous",
    "other one": "previous",
    "other project": "previous",
    "last": "previous",
    "last one": "previous",
    "last project": "previous",
}


def bench_dir(data_dir: Path) -> Path:
    dest = data_dir / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def scene_path(data_dir: Path) -> Path:
    return bench_dir(data_dir) / "scene.json"


def projects_dir(data_dir: Path) -> Path:
    dest = bench_dir(data_dir) / "projects"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def index_path(data_dir: Path) -> Path:
    return bench_dir(data_dir) / "projects.json"


def empty_scene() -> dict:
    return {"units": "mm", "parts": [], "wires": [], "project": {"id": "", "name": ""}}


def load_scene(path: Path) -> dict:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("parts"), list):
                if not isinstance(data.get("wires"), list):
                    data["wires"] = []
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return empty_scene()


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    tmp.replace(path)


def save_scene(path: Path, scene: dict) -> None:
    out = dict(scene)
    out.pop("projects", None)
    _write_json(path, out)


def snapshot_scene(scene: dict) -> dict:
    out = copy.deepcopy(scene)
    out.pop("projects", None)
    return out


def has_work(scene: dict | None) -> bool:
    if not scene:
        return False
    if scene.get("parts") or scene.get("wires"):
        return True
    for row in scene.get("stock") or scene.get("pile") or []:
        if isinstance(row, dict):
            try:
                if int(row.get("qty") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def project_id(name: str) -> str:
    slug = _SLUG.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:80] or "project"


def load_index(data_dir: Path) -> dict:
    empty = {"current": "", "previous": "", "projects": []}
    path = index_path(data_dir)
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    rows: list[dict] = []
    for row in data.get("projects") or []:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or "").strip()
        if not ident:
            continue
        try:
            n = int(row.get("parts") or 0)
        except (TypeError, ValueError):
            n = 0
        rows.append(
            {
                "id": ident,
                "name": str(row.get("name") or ident),
                "saved_at": str(row.get("saved_at") or ""),
                "parts": n,
            }
        )
    return {
        "current": str(data.get("current") or ""),
        "previous": str(data.get("previous") or ""),
        "projects": rows,
    }


def save_index(data_dir: Path, idx: dict) -> None:
    _write_json(
        index_path(data_dir),
        {
            "current": str(idx.get("current") or ""),
            "previous": str(idx.get("previous") or ""),
            "projects": list(idx.get("projects") or []),
        },
    )


def scene_project(scene: dict | None, idx: dict | None = None) -> dict:
    raw = (scene or {}).get("project") if isinstance((scene or {}).get("project"), dict) else {}
    ident = str(raw.get("id") or "")
    name = str(raw.get("name") or "")
    if not ident and idx:
        ident = str(idx.get("current") or "")
    if not name and ident and idx:
        for row in idx.get("projects") or []:
            if row.get("id") == ident:
                name = str(row.get("name") or ident)
                break
    return {"id": ident, "name": name}


def scene_for_client(scene: dict, data_dir: Path) -> dict:
    idx = load_index(data_dir)
    out = dict(scene)
    out["project"] = scene_project(scene, idx)
    out["projects"] = list(idx.get("projects") or [])
    if not isinstance(out.get("wires"), list):
        out["wires"] = []
    return out


def _next_untitled(idx: dict) -> str:
    used = {str(p.get("id") or "") for p in idx.get("projects") or []}
    n = 1
    while f"project-{n}" in used:
        n += 1
    return f"project {n}"


def _upsert_index(idx: dict, ident: str, name: str, scene: dict) -> None:
    row = {
        "id": ident,
        "name": name,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parts": len(scene.get("parts") or []),
    }
    rows = list(idx.get("projects") or [])
    for i, existing in enumerate(rows):
        if existing.get("id") == ident:
            rows[i] = row
            break
    else:
        rows.append(row)
    idx["projects"] = rows
    idx["current"] = ident


def save_project(scene: dict, data_dir: Path, name: str = "") -> str:
    idx = load_index(data_dir)
    current = scene_project(scene, idx)
    label = " ".join((name or current.get("name") or "").split()).strip()
    if not label:
        label = _next_untitled(idx)
    ident = project_id(label)
    scene["project"] = {"id": ident, "name": label}
    snap = snapshot_scene(scene)
    dest = projects_dir(data_dir) / f"{ident}.json"
    save_scene(dest, snap)
    _upsert_index(idx, ident, label, snap)
    save_index(data_dir, idx)
    return f"saved as {label}"


def new_project(scene: dict, data_dir: Path, name: str = "") -> str:
    kept = ""
    if has_work(scene) or str((scene.get("project") or {}).get("id") or ""):
        kept = save_project(scene, data_dir)
        kept = str((scene.get("project") or {}).get("name") or "").strip() or kept
    idx = load_index(data_dir)
    old = str(idx.get("current") or "")
    rev = int(camera_of(scene).get("rev") or 0) + 1
    scene.clear()
    scene.update(empty_scene())
    cam = default_camera()
    cam["rev"] = rev
    scene["camera"] = cam
    label = " ".join((name or "").split()).strip()
    if label:
        ident = project_id(label)
        scene["project"] = {"id": ident, "name": label}
        save_scene(projects_dir(data_dir) / f"{ident}.json", snapshot_scene(scene))
        _upsert_index(idx, ident, label, scene)
        idx["current"] = ident
    else:
        idx["current"] = ""
    if old and old != idx.get("current"):
        idx["previous"] = old
    save_index(data_dir, idx)
    if kept:
        return f"started a new project; {kept} is on file"
    return "started a new project"


def resolve_project(idx: dict, name: str, current_id: str = "") -> str:
    raw = " ".join((name or "").split()).strip().lower()
    raw = re.sub(r"^(?:the|my|our)\s+", "", raw)
    alias = _LOAD_ALIASES.get(raw)
    rows = [p for p in idx.get("projects") or [] if p.get("id")]
    ids = [str(p["id"]) for p in rows]
    current_id = str(current_id or idx.get("current") or "")
    others = [i for i in ids if i != current_id]
    if alias == "first":
        if others:
            return others[0]
        return str(idx.get("previous") or "") if idx.get("previous") in ids else (others[0] if others else "")
    if alias == "previous" or raw == "":
        prev = str(idx.get("previous") or "")
        if prev and prev in ids and prev != current_id:
            return prev
        if others:
            return others[-1]
        return ""
    if raw in ids:
        return raw
    for row in rows:
        if str(row.get("name") or "").strip().lower() == raw:
            return str(row["id"])
    slug = project_id(raw)
    if slug in ids:
        return slug
    hits = [
        str(p["id"])
        for p in rows
        if raw in str(p.get("name") or "").lower() or raw in str(p.get("id") or "")
    ]
    if len(hits) == 1:
        return hits[0]
    return ""


def load_project(scene: dict, data_dir: Path, name: str = "") -> str:
    idx = load_index(data_dir)
    current = scene_project(scene, idx)
    ident = resolve_project(idx, name, current.get("id") or "")
    if not ident:
        raise ValueError("no such project")
    dest = projects_dir(data_dir) / f"{ident}.json"
    if not dest.is_file():
        raise ValueError("no such project")
    incoming = load_scene(dest)
    if ident != (current.get("id") or "") and (has_work(scene) or current.get("id")):
        save_project(scene, data_dir)
        idx = load_index(data_dir)
    old = str(idx.get("current") or "")
    scene.clear()
    scene.update(incoming)
    scene.setdefault("units", "mm")
    scene.setdefault("parts", [])
    meta = next((p for p in idx.get("projects") or [] if p.get("id") == ident), None)
    label = str((meta or {}).get("name") or (scene.get("project") or {}).get("name") or ident)
    scene["project"] = {"id": ident, "name": label}
    cam = camera_of(scene)
    cam["rev"] = int(cam.get("rev") or 0) + 1
    scene["camera"] = cam
    if old and old != ident:
        idx["previous"] = old
    idx["current"] = ident
    save_index(data_dir, idx)
    n = len(scene.get("parts") or [])
    return f"opened {label} with {n} part" + ("" if n == 1 else "s")


def list_projects(data_dir: Path, current_id: str = "") -> str:
    idx = load_index(data_dir)
    rows = list(idx.get("projects") or [])
    if not rows:
        return "no saved projects"
    cur = str(current_id or idx.get("current") or "")
    bits = []
    for row in rows:
        label = str(row.get("name") or row.get("id"))
        if row.get("id") == cur:
            bits.append(f"{label} (current)")
        else:
            bits.append(label)
    return "projects on file: " + ", ".join(bits)


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


def _next_wire_id(scene: dict) -> int:
    n = 0
    for w in scene.get("wires") or []:
        raw = str(w.get("id") or "").lstrip("w")
        if raw.isdigit():
            n = max(n, int(raw))
    return n + 1


def default_wire_color(net: str = "", from_pin: str = "", to_pin: str = "") -> str:
    blob = f"{net} {from_pin} {to_pin}".lower()
    if "gnd" in blob or blob.strip() in {"-", "b-", "k"}:
        return "#1a1a1a"
    if "vbat" in blob or "b+" in blob:
        return "#c0392b"
    if "vbus" in blob or "5v" in blob or "in+" in blob:
        return "#e74c3c"
    if "3v3" in blob or "vdd" in blob:
        return "#f4d03f"
    if "sck" in blob or "bclk" in blob:
        return "#3498db"
    if "ws" in blob or "lrcl" in blob:
        return "#ecf0f1"
    if "sd" in blob or "dout" in blob:
        return "#2ecc71"
    if "mute" in blob or "mic vdd" in blob:
        return "#9b59b6"
    if "led" in blob:
        return "#e67e22"
    return "#7f8c8d"


def resolve_part(scene: dict, raw) -> dict | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return find_part(scene, n=int(raw))
    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit():
        return find_part(scene, n=int(s))
    return find_part(scene, ident=s)


def _op_end(scene: dict, op: dict, *keys: str) -> dict | None:
    for k in keys:
        if k in op and op[k] is not None and str(op[k]) != "":
            found = resolve_part(scene, op[k])
            if found is not None:
                return found
    return None


def add_wire(
    scene: dict,
    from_part: dict,
    to_part: dict,
    *,
    net: str = "",
    from_pin: str = "",
    to_pin: str = "",
    color: str = "",
) -> dict:
    src = str(from_part.get("id") or "")
    dst = str(to_part.get("id") or "")
    if not src or not dst or src == dst:
        raise ValueError("wire needs two parts")
    net_s = str(net or "").strip()
    a_pin = str(from_pin or "").strip()
    b_pin = str(to_pin or "").strip()
    hex_color = parse_hex_color(color) if str(color or "").strip() else ""
    if not hex_color:
        hex_color = default_wire_color(net_s, a_pin, b_pin)
    wires = list(scene.get("wires") or [])
    for w in wires:
        if (
            str(w.get("from")) == src
            and str(w.get("to")) == dst
            and str(w.get("net") or "") == net_s
            and str(w.get("from_pin") or "") == a_pin
            and str(w.get("to_pin") or "") == b_pin
        ):
            w["color"] = hex_color
            scene["wires"] = wires
            return w
    n = _next_wire_id(scene)
    row = {
        "id": f"w{n}",
        "kind": "wire",
        "from": src,
        "to": dst,
        "from_pin": a_pin,
        "to_pin": b_pin,
        "net": net_s or f"net {n}",
        "color": hex_color,
    }
    wires.append(row)
    scene["wires"] = wires
    return row


def prune_wires(scene: dict) -> None:
    ids = {str(p.get("id") or "") for p in scene.get("parts") or []}
    ids.discard("")
    keep = []
    for w in scene.get("wires") or []:
        if not isinstance(w, dict):
            continue
        if str(w.get("from") or "") in ids and str(w.get("to") or "") in ids:
            keep.append(w)
    scene["wires"] = keep


def find_wire(scene: dict, n: int | None = None, ident: str = "") -> dict | None:
    wires = list(scene.get("wires") or [])
    if not wires:
        return None
    if ident:
        key = ident.strip().lower()
        for w in wires:
            if key in {str(w.get("id") or "").lower(), str(w.get("net") or "").lower()}:
                return w
    if n is not None and 1 <= n <= len(wires):
        return wires[n - 1]
    return None


KIT_NETS = (
    ("psu", "usb", "5V", "VBUS", "VBUS"),
    ("usb", "bms", "5V", "VBUS", "IN+"),
    ("cell", "bms", "VBAT", "B+", "B+"),
    ("cell", "bms", "GND", "B-", "GND"),
    ("bms", "mcu", "5V", "OUT+", "5V"),
    ("bms", "mcu", "GND", "GND", "GND"),
    ("mcu", "mic", "3V3", "3V3", "VDD"),
    ("mcu", "mic", "GND", "GND", "GND"),
    ("mcu", "mic", "I2S_SCK", "SCK", "SCK"),
    ("mcu", "mic", "I2S_WS", "WS", "WS"),
    ("mcu", "mic", "I2S_SD", "SD", "SD"),
    ("mcu", "mute", "MUTE", "GPIO", "SW"),
    ("mcu", "led", "LED", "GPIO", "A"),
)


def part_by_role(scene: dict, role: str) -> dict | None:
    want = (role or "").strip().lower()
    for p in scene.get("parts") or []:
        if str(p.get("role") or "").strip().lower() == want:
            return p
    return None


def wire_kit(scene: dict) -> str:
    n = 0
    missing: list[str] = []
    for src_role, dst_role, net, a_pin, b_pin in KIT_NETS:
        src = part_by_role(scene, src_role)
        dst = part_by_role(scene, dst_role)
        if src is None or dst is None:
            if src is None and src_role not in missing:
                missing.append(src_role)
            if dst is None and dst_role not in missing:
                missing.append(dst_role)
            continue
        add_wire(scene, src, dst, net=net, from_pin=a_pin, to_pin=b_pin)
        n += 1
    if not n:
        why = ", ".join(missing) if missing else "no kit parts"
        raise ValueError(f"no kit to wire ({why})")
    return f"wired {n} nets"


def delete_wire(scene: dict, wire: dict) -> bool:
    wires = list(scene.get("wires") or [])
    keep = [w for w in wires if w is not wire and w.get("id") != wire.get("id")]
    if len(keep) == len(wires):
        return False
    scene["wires"] = keep
    return True


FINISHES = frozenset(
    {
        "wood",
        "abs",
        "lid",
        "devkit",
        "pcb",
        "bms",
        "cell",
        "mems",
        "switch",
        "led",
        "usb",
        "brick",
        "metal",
    }
)
ROLE_FINISH = {
    "board": "wood",
    "enclosure": "abs",
    "mcu": "devkit",
    "cell": "cell",
    "bms": "bms",
    "mic": "mems",
    "mute": "switch",
    "switch": "switch",
    "led": "led",
    "usb": "usb",
    "psu": "brick",
}
_HEX6 = re.compile(r"^[0-9a-f]{6}$")
_HEX3 = re.compile(r"^[0-9a-f]{3}$")


def parse_hex_color(raw) -> str:
    if raw is None or raw == "":
        return ""
    s = str(raw).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if s.startswith("#"):
        s = s[1:]
    if _HEX3.fullmatch(s):
        s = "".join(ch * 2 for ch in s)
    if not _HEX6.fullmatch(s):
        raise ValueError("need a hex colour")
    return "#" + s


def default_finish(role: str = "", name: str = "", thickness_mm: float = 0.0) -> str:
    role = str(role or "").strip().lower()
    name = str(name or "").strip().lower()
    if role in ROLE_FINISH:
        finish = ROLE_FINISH[role]
        if finish == "abs" and ("lid" in name or (thickness_mm and thickness_mm <= 5)):
            return "lid"
        return finish
    if "esp" in name or "devkit" in name:
        return "devkit"
    if "18650" in name or "cell" in name:
        return "cell"
    if "tp4056" in name or "bms" in name:
        return "bms"
    if "inmp" in name or "mems" in name or "mic" in name:
        return "mems"
    if "mute" in name or "switch" in name:
        return "switch"
    if "led" in name:
        return "led"
    if "usb" in name and "psu" not in name and "supply" not in name:
        return "usb"
    if "psu" in name or "charger" in name:
        return "brick"
    if "lid" in name:
        return "lid"
    if "enclosure" in name or "box" in name:
        return "abs"
    return "wood"


def apply_look(part: dict, *, finish: str | None = None, color: str | None = None) -> dict:
    if finish is not None:
        key = str(finish or "wood").strip().lower()
        if key not in FINISHES:
            raise ValueError(f"unknown finish {finish!r}")
        if key == "wood":
            part.pop("finish", None)
        else:
            part["finish"] = key
    if color is not None:
        hex_color = parse_hex_color(color) if str(color).strip() else ""
        if hex_color:
            part["color"] = hex_color
        else:
            part.pop("color", None)
    return part


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
    role: str = "",
    finish: str = "",
    color: str = "",
) -> dict:
    parts = list(scene.get("parts") or [])
    n = _next_id(scene)
    if y_mm is None:
        y = 0.0
        for p in parts:
            y = max(y, float(p.get("y_mm") or 0) + float(p.get("width_mm") or 0) + 20)
        y_mm = y if parts else 0.0
    role_s = str(role or "board")
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
        "role": role_s,
    }
    look = str(finish or "").strip().lower() or default_finish(
        role_s, part["name"], float(thickness_mm)
    )
    apply_look(part, finish=look, color=color)
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
        name=str(part.get("name") or ""),
        upright=bool(part.get("upright")),
        x_mm=float(part.get("x_mm") or 0) + dx_mm,
        y_mm=float(part.get("y_mm") or 0) + dy_mm,
        z_mm=float(part.get("z_mm") or 0) + dz_mm,
        rx_deg=float(part.get("rx_deg") or 0),
        ry_deg=float(part.get("ry_deg") or 0),
        rz_deg=float(part.get("rz_deg") or 0),
        role=str(part.get("role") or ""),
        finish=str(part.get("finish") or ""),
        color=str(part.get("color") or ""),
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


def default_camera() -> dict:
    return {
        "look_x_mm": 800.0,
        "look_y_mm": 0.0,
        "look_z_mm": 0.0,
        "az": 0.7,
        "el": 0.45,
        "dist_mm": 2200.0,
        "rev": 0,
    }


def camera_of(scene: dict | None) -> dict:
    cam = default_camera()
    raw = (scene or {}).get("camera") or {}
    if not isinstance(raw, dict):
        return cam
    for key in ("look_x_mm", "look_y_mm", "look_z_mm", "az", "el", "dist_mm"):
        try:
            if raw.get(key) is not None:
                cam[key] = float(raw[key])
        except (TypeError, ValueError):
            pass
    try:
        cam["rev"] = int(raw.get("rev") or 0)
    except (TypeError, ValueError):
        cam["rev"] = 0
    cam["el"] = max(0.08, min(1.2, float(cam["el"])))
    cam["dist_mm"] = max(200.0, min(12000.0, float(cam["dist_mm"])))
    return cam


def set_camera(scene: dict, fields: dict | None = None, *, bump: bool = True) -> dict:
    cam = camera_of(scene)
    body = fields or {}
    mapping = (
        ("look_x_mm", ("look_x_mm", "x_mm")),
        ("look_y_mm", ("look_y_mm", "y_mm")),
        ("look_z_mm", ("look_z_mm", "z_mm")),
        ("az", ("az", "az_rad")),
        ("el", ("el", "el_rad")),
        ("dist_mm", ("dist_mm", "distance_mm")),
    )
    for key, aliases in mapping:
        val = _num(body, *aliases)
        if val is not None:
            cam[key] = val
    cam["el"] = max(0.08, min(1.2, float(cam["el"])))
    cam["dist_mm"] = max(200.0, min(12000.0, float(cam["dist_mm"])))
    if bump:
        cam["rev"] = int(cam.get("rev") or 0) + 1
    for key in ("look_x_mm", "look_y_mm", "look_z_mm", "az", "el", "dist_mm"):
        cam[key] = round(float(cam[key]), 2)
    scene["camera"] = cam
    return cam


def pan_camera(
    scene: dict,
    dx_mm: float = 0.0,
    dy_mm: float = 0.0,
    dz_mm: float = 0.0,
) -> dict:
    cam = camera_of(scene)
    return set_camera(
        scene,
        {
            "look_x_mm": cam["look_x_mm"] + float(dx_mm or 0),
            "look_y_mm": cam["look_y_mm"] + float(dy_mm or 0),
            "look_z_mm": cam["look_z_mm"] + float(dz_mm or 0),
        },
    )


def look_at_part(scene: dict, part: dict) -> dict:
    from bench.design import aabb

    xmin, ymin, zmin, xmax, ymax, zmax = aabb(part)
    return set_camera(
        scene,
        {
            "look_x_mm": (xmin + xmax) / 2,
            "look_y_mm": (ymin + ymax) / 2,
            "look_z_mm": (zmin + zmax) / 2,
        },
    )


def frame_camera(scene: dict) -> dict:
    from bench.design import structure_aabb

    parts = list(scene.get("parts") or [])
    if not parts:
        return set_camera(
            scene,
            {
                "look_x_mm": 800,
                "look_y_mm": 0,
                "look_z_mm": 0,
                "dist_mm": 2200,
            },
        )
    xmin, ymin, zmin, xmax, ymax, zmax = structure_aabb(parts)
    span = max(xmax - xmin, ymax - ymin, zmax - zmin, 400.0)
    return set_camera(
        scene,
        {
            "look_x_mm": (xmin + xmax) / 2,
            "look_y_mm": (ymin + ymax) / 2,
            "look_z_mm": (zmin + zmax) / 2,
            "dist_mm": max(900.0, span * 1.6),
        },
    )


def merge_site_op(scene: dict, raw: dict) -> dict:
    over = site_from_scene({"site": raw})
    return site_to_scene(merge_site(site_from_scene(scene), over))


def merge_hints_op(scene: dict, raw: dict) -> dict:
    over = hints_from_scene({"hints": raw})
    return hints_to_scene(merge_hints(hints_from_scene(scene), over))


def apply_op(scene: dict, op: dict, *, data_dir: Path | None = None) -> str:
    name = str(op.get("op") or "").lower()
    if name in ("save", "save_as", "save_project"):
        if data_dir is None:
            raise ValueError("no data dir")
        label = str(op.get("as") or op.get("name") or op.get("to") or "")
        return save_project(scene, data_dir, label)
    if name in ("new", "new_project"):
        if data_dir is None:
            raise ValueError("no data dir")
        label = str(op.get("as") or op.get("name") or op.get("to") or "")
        return new_project(scene, data_dir, label)
    if name in ("load", "switch"):
        if data_dir is None:
            raise ValueError("no data dir")
        label = str(op.get("name") or op.get("as") or op.get("id") or op.get("to") or "")
        return load_project(scene, data_dir, label)
    if name in ("list_projects", "projects"):
        if data_dir is None:
            raise ValueError("no data dir")
        current = str((scene.get("project") or {}).get("id") or "")
        return list_projects(data_dir, current)
    if name == "clear":
        scene["parts"] = []
        scene["wires"] = []
        scene.pop("check", None)
        return "cleared the bench"
    if name == "set_parts":
        incoming = op.get("parts")
        if not isinstance(incoming, list):
            raise ValueError("need parts")
        scene["parts"] = incoming
        prune_wires(scene)
        return f"set {len(incoming)} parts"
    if name in ("wire", "connect", "add_wire"):
        src = _op_end(scene, op, "from", "from_id", "a", "src")
        dst = _op_end(scene, op, "to", "to_id", "b", "dst")
        if src is None:
            src = _op_end(scene, op, "from_n", "n")
        if dst is None:
            dst = _op_end(scene, op, "to_n")
        if src is None or dst is None:
            raise ValueError("wire needs from and to")
        wire = add_wire(
            scene,
            src,
            dst,
            net=str(op.get("net") or op.get("name") or ""),
            from_pin=str(op.get("from_pin") or op.get("a_pin") or ""),
            to_pin=str(op.get("to_pin") or op.get("b_pin") or ""),
            color=str(op.get("color") or op.get("colour") or ""),
        )
        a = wire.get("from_pin") or ""
        b = wire.get("to_pin") or ""
        pins = f" {a} → {b}" if a or b else ""
        return f"wired {wire.get('net')}: {src.get('name') or src.get('id')} → {dst.get('name') or dst.get('id')}{pins}"
    if name in ("wire_kit", "wire_room_node"):
        return wire_kit(scene)
    if name == "set_wires":
        incoming = op.get("wires")
        if not isinstance(incoming, list):
            raise ValueError("need wires")
        scene["wires"] = []
        for raw in incoming:
            if not isinstance(raw, dict):
                continue
            src = resolve_part(scene, raw.get("from") or raw.get("from_id"))
            dst = resolve_part(scene, raw.get("to") or raw.get("to_id"))
            if src is None or dst is None:
                raise ValueError("wire needs from and to")
            add_wire(
                scene,
                src,
                dst,
                net=str(raw.get("net") or raw.get("name") or ""),
                from_pin=str(raw.get("from_pin") or ""),
                to_pin=str(raw.get("to_pin") or ""),
                color=str(raw.get("color") or raw.get("colour") or ""),
            )
        return f"set {len(scene.get('wires') or [])} wires"
    if name in ("unwire", "disconnect", "delete_wire"):
        n = op.get("n")
        try:
            n = int(n) if n is not None and str(n) != "" else None
        except (TypeError, ValueError):
            n = None
        ident = str(op.get("id") or op.get("net") or op.get("name") or "")
        wire = find_wire(scene, n=n, ident=ident)
        if wire is None:
            src = _op_end(scene, op, "from", "from_id", "a")
            dst = _op_end(scene, op, "to", "to_id", "b")
            net = str(op.get("net") or "")
            if src and dst:
                for w in list(scene.get("wires") or []):
                    if str(w.get("from")) == src.get("id") and str(w.get("to")) == dst.get("id"):
                        if not net or str(w.get("net") or "") == net:
                            wire = w
                            break
        if wire is None:
            raise ValueError("no such wire")
        label = wire.get("net") or wire.get("id")
        delete_wire(scene, wire)
        return f"removed {label}"
    if name == "clear_wires":
        n = len(scene.get("wires") or [])
        scene["wires"] = []
        return f"cleared {n} wires"
    if name == "set_stock":
        incoming = op.get("stock") or []
        if op.get("merge"):
            cur = stock_from_scene(scene)
            for raw in incoming:
                try:
                    merge_stock(
                        cur,
                        StockItem(
                            length_mm=float(raw["length_mm"]),
                            width_mm=float(raw.get("width_mm") or 70),
                            thickness_mm=float(raw.get("thickness_mm") or 15),
                            qty=int(raw.get("qty") or 0),
                        ),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            scene["stock"] = stock_to_scene(cur)
        else:
            scene["stock"] = incoming if isinstance(incoming, list) else []
        scene["pile"] = list(scene.get("stock") or [])
        n = sum(int(s.get("qty") or 0) for s in scene.get("stock") or [])
        return f"stock on file, {n} pieces"
    if name == "set_site":
        site = merge_site_op(scene, op.get("site") or {})
        scene["site"] = site
        return (
            f"site {site.get('width_mm') or 0:.0f} across, "
            f"{site.get('length_mm') or 0:.0f} along"
        )
    if name == "set_hints":
        hints = merge_hints_op(scene, op.get("hints") or op)
        scene["hints"] = hints
        return (
            f"{hints.get('uprights') or 0} uprights at "
            f"{hints.get('centres_mm') or 0:.0f} centres"
        )
    if name in ("camera", "look", "look_at"):
        n = op.get("n")
        ident = str(op.get("id") or op.get("name") or "")
        if n is not None or ident:
            try:
                n = int(n) if n is not None and str(n) != "" else None
            except (TypeError, ValueError):
                n = None
            part = find_part(scene, n=n, ident=ident)
            if part is None:
                raise ValueError("no such board")
            look_at_part(scene, part)
            return f"looking at {part.get('name') or part.get('id')}"
        cam = set_camera(scene, op)
        return (
            f"looking at {cam['look_x_mm']:.0f}, {cam['look_y_mm']:.0f}, "
            f"{cam['look_z_mm']:.0f} mm"
        )
    if name == "pan":
        cam = pan_camera(
            scene,
            dx_mm=_num(op, "dx_mm") or 0.0,
            dy_mm=_num(op, "dy_mm") or 0.0,
            dz_mm=_num(op, "dz_mm") or 0.0,
        )
        return (
            f"panned to {cam['look_x_mm']:.0f}, {cam['look_y_mm']:.0f}, "
            f"{cam['look_z_mm']:.0f} mm"
        )
    if name == "frame":
        cam = frame_camera(scene)
        return (
            f"framed at {cam['look_x_mm']:.0f}, {cam['look_y_mm']:.0f}, "
            f"{cam['look_z_mm']:.0f} mm"
        )
    if name == "design":
        pile = scene.get("pile") or scene.get("stock")
        brief = Brief(
            stock=stock_from_scene({"stock": pile}),
            site=site_from_scene(scene),
            hints=hints_from_scene(scene),
            wants_design=True,
        )
        specs, remaining, check, notes = layout(brief)
        scene["parts"] = []
        for spec in specs:
            add_board(
                scene,
                spec["length_mm"],
                spec["width_mm"],
                spec["thickness_mm"],
                name=str(spec.get("name") or ""),
                upright=bool(spec.get("upright")),
                x_mm=spec.get("x_mm"),
                y_mm=spec.get("y_mm"),
                z_mm=spec.get("z_mm"),
                rx_deg=float(spec.get("rx_deg") or 0),
                ry_deg=float(spec.get("ry_deg") or 0),
                rz_deg=float(spec.get("rz_deg") or 0),
                role=str(spec.get("role") or ""),
            )
        scene["stock"] = stock_to_scene(remaining)
        scene["check"] = check.as_dict()
        scene["notes"] = notes
        if not specs:
            return notes[0] if notes else "could not place a structure"
        return notes[-1] if notes else f"placed {len(specs)} members"
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
            role=str(op.get("role") or ""),
            finish=str(op.get("finish") or ""),
            color=str(op.get("color") or ""),
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
    if name == "rename":
        to = str(op.get("to") or op.get("new_name") or op.get("as") or "").strip()
        if not to and op.get("id"):
            to = str(op.get("name") or "").strip()
        if not to:
            raise ValueError("need a name")
        part["name"] = to
        return f"named {to}"
    if name in ("set_look", "paint"):
        finish = op.get("finish")
        if finish is None:
            finish = op.get("look") or op.get("as") or op.get("to")
        color = op.get("color") if "color" in op else op.get("colour")
        if finish is None and color is None:
            raise ValueError("need a finish or colour")
        apply_look(part, finish=None if finish is None else str(finish), color=color)
        shown = part.get("finish") or "wood"
        return f"{part.get('name')} {shown}"
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
    prune_wires(scene)
    return True


class Handler(BaseHTTPRequestHandler):
    data_dir: Path = Path.home() / ".jarvis"
    _lock = threading.Lock()

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

    def _client_scene(self, scene: dict) -> dict:
        return scene_for_client(scene, self.data_dir)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"ok": True, "api": 9})
            return
        if path == "/api/scene":
            self._json(scene_for_client(load_scene(scene_path(self.data_dir)), self.data_dir))
            return
        if path == "/api/projects":
            idx = load_index(self.data_dir)
            self._json(idx)
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
        with self._lock:
            scene = load_scene(dest)
            self._post_locked(path, body, dest, scene)

    def _post_locked(self, path: str, body: dict, dest: Path, scene: dict) -> None:
        if path == "/api/clear":
            scene["parts"] = []
            scene["wires"] = []
            scene.pop("check", None)
            save_scene(dest, scene)
            self._json(self._client_scene(scene))
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
                    role=str(body.get("role") or ""),
                    finish=str(body.get("finish") or ""),
                    color=str(body.get("color") or body.get("colour") or ""),
                )
            except (KeyError, TypeError, ValueError):
                self._json({"error": "need length_mm, width_mm, thickness_mm"}, 400)
                return
            save_scene(dest, scene)
            self._json({"part": part, "scene": self._client_scene(scene)})
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
            self._json({"part": part, "scene": self._client_scene(scene)})
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
            self._json({"deleted": part.get("name") or part.get("id"), "scene": self._client_scene(scene)})
            return
        if path in ("/api/ops", "/api/command"):
            notes: list[str] = []
            try:
                for op in body.get("ops") or [body]:
                    if not op or not op.get("op"):
                        continue
                    notes.append(apply_op(scene, op, data_dir=self.data_dir))
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": self._client_scene(scene)})
            return
        if path == "/api/duplicate":
            try:
                notes = [apply_op(scene, {"op": "duplicate", **body}, data_dir=self.data_dir)]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": self._client_scene(scene)})
            return
        if path == "/api/move":
            try:
                notes = [apply_op(scene, {"op": "move", **body}, data_dir=self.data_dir)]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": self._client_scene(scene)})
            return
        if path == "/api/camera":
            cam = set_camera(scene, body)
            save_scene(dest, scene)
            self._json({"camera": cam, "scene": self._client_scene(scene)})
            return
        if path == "/api/resize":
            try:
                notes = [apply_op(scene, {"op": "resize", **body}, data_dir=self.data_dir)]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": self._client_scene(scene)})
            return
        if path == "/api/rename":
            try:
                notes = [apply_op(scene, {"op": "rename", **body}, data_dir=self.data_dir)]
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            save_scene(dest, scene)
            self._json({"notes": notes, "scene": self._client_scene(scene)})
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
