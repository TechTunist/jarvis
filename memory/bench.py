"""Timber bench: millimetre boards Jarvis can add, move, rotate, duplicate, delete."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

from memory.home import JarvisHome

PORT = 8770
URL = f"http://127.0.0.1:{PORT}/"
API = 3
_DIMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)\b",
    re.I,
)
_DIMS_BY = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s+by\s+"
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s+by\s+"
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\b",
    re.I,
)
_LONG = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s+"
    r"(?:long|length|instead of)"
    r"|\blength\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?",
    re.I,
)
_OFFSET = re.compile(
    r"\boffset\s+(?:of\s+|at\s+|by\s+)?(\d+(?:\.\d+)?)\s*(?:mm)?"
    r"|\b(\d+(?:\.\d+)?)\s*mm\s*(?:offset|centres?|centers?)\b"
    r"|\b(\d+(?:\.\d+)?)\s*(?:centres?|centers?)\b",
    re.I,
)
_NEW = re.compile(r"\b(?:add|create|make me|another|new|second)\b", re.I)
_ORIENT = re.compile(
    r"\b(?:stand(?:ing)?|stood|upright|vertical|on end|orient(?:ed|ation)?)\b",
    re.I,
)
_FLAT = re.compile(r"\b(?:horizontal|flat|lying|laying)\b", re.I)
_DELETE = re.compile(r"\b(?:delete|remove|drop|get rid of|clear)\b", re.I)
_DUP = re.compile(r"\b(?:duplicate|copy|clone|same dimensions|same size|same as)\b", re.I)
_BOARD_N = re.compile(r"\b(?:board|part|plate|model)\s*(\d+)\b", re.I)
_DEL_N = re.compile(
    r"\b(?:delete|remove|drop|get rid of)\s+(?:the\s+)?(?:board|part|plate|model)\s*(\d+)\b",
    re.I,
)
_BENCH_PY = Path(__file__).resolve().parent.parent / "bench" / "bench.py"
OPS_SYSTEM = (
    "You drive a millimetre 3d timber bench. JSON only: "
    '{"ops":[{"op":"add|duplicate|move|rotate|resize|delete|clear", ...}]}. '
    "Y across the plan is y_mm; z_mm is up; x_mm is along. "
    "add: length_mm, optional width_mm, thickness_mm, x_mm,y_mm,z_mm, upright. "
    "duplicate: n, optional dx_mm,dy_mm,dz_mm. 900 centres = dy_mm 900. "
    "move: n plus x_mm/y_mm/z_mm or dx_mm/dy_mm/dz_mm. "
    "rotate: n, upright true|false. "
    "resize: n, length_mm and/or width_mm and/or thickness_mm. "
    "delete: n. Horizontal on top of an upright board: z_mm = that board's length. "
    "Do not no-op. No markdown."
)


def parse_board(text: str) -> tuple[float, float, float] | None:
    raw = " ".join((text or "").split())
    hit = _DIMS.search(raw) or _DIMS_BY.search(raw)
    if not hit:
        return None
    return float(hit.group(1)), float(hit.group(2)), float(hit.group(3))


def parse_length(text: str) -> float | None:
    hit = _LONG.search(text or "")
    if not hit:
        return None
    for g in hit.groups():
        if g:
            return float(g)
    return None


def parse_offset(text: str) -> float | None:
    hit = _OFFSET.search(text or "")
    if not hit:
        return None
    for g in hit.groups():
        if g:
            return float(g)
    return None


def wants_orient(text: str) -> bool:
    return bool(_ORIENT.search(text or ""))


def wants_delete(text: str) -> bool:
    return bool(_DELETE.search(text or "")) and bool(
        re.search(r"\b(?:board|part|plate|model|bench)\b", text or "", re.I)
    )


def wants_new(text: str) -> bool:
    return bool(_NEW.search(text or ""))


def _get(path: str, timeout: float = 0.6) -> dict | None:
    try:
        with urllib.request.urlopen(path, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _post(path: str, payload: dict, timeout: float = 4.0) -> dict:
    raw = json.dumps(payload).encode()
    req = urllib.request.Request(
        path,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def api_ok() -> bool:
    hit = _get(f"{URL}api/health")
    try:
        return bool(hit) and int(hit.get("api") or 0) >= API
    except (TypeError, ValueError):
        return False


def _stop_listener() -> None:
    try:
        subprocess.run(
            ["fuser", "-k", f"{PORT}/tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    time.sleep(0.15)


def healthy() -> bool:
    return _get(f"{URL}api/scene") is not None


def ensure_server(home: JarvisHome) -> bool:
    """True if a new process was started."""
    if api_ok():
        return False
    if healthy():
        _stop_listener()
    if not _BENCH_PY.is_file():
        return False
    subprocess.Popen(
        [sys.executable, str(_BENCH_PY), "--data-dir", str(home.root), "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(50):
        time.sleep(0.05)
        if api_ok():
            return True
    return False


def open_ui() -> None:
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def _board_n(text: str, default: int | None = None) -> int | None:
    found = [int(x) for x in _BOARD_N.findall(text or "")]
    if found:
        return found[0]
    return default


def parse_ops(asked: str, scene: dict) -> list[dict]:
    """Deterministic CAD ops. Empty means ask the hands model or report the scene."""
    raw = " ".join((asked or "").split())
    parts = list(scene.get("parts") or [])
    ops: list[dict] = []
    if re.search(r"\bclear(?:\s+the)?\s+bench\b|\bempty the bench\b", raw, re.I):
        return [{"op": "clear"}]
    if wants_delete(raw):
        hit = _DEL_N.search(raw)
        n = int(hit.group(1)) if hit else _board_n(raw)
        ops.append({"op": "delete", "n": n} if n else {"op": "delete"})
    if wants_orient(raw) and not _FLAT.search(raw):
        n = None
        hit = re.search(
            r"\b(?:board|part|plate)\s*(\d+)\b.{0,40}\b(?:vertical|upright|stand|end|orient)",
            raw,
            re.I,
        )
        if hit:
            n = int(hit.group(1))
        else:
            hit = re.search(
                r"\b(?:make|stand|orient)\s+(?:the\s+)?(?:board|part|plate)\s*(\d+)\b",
                raw,
                re.I,
            )
            n = int(hit.group(1)) if hit else _board_n(raw)
        op = {"op": "rotate", "upright": True}
        if n:
            op["n"] = n
        ops.append(op)
    offset = parse_offset(raw)
    if _DUP.search(raw) or (offset is not None and parts and not parse_board(raw)):
        n = _board_n(raw, 1 if parts else None)
        op = {"op": "duplicate", "n": n or 1, "dy_mm": offset or 0.0}
        ops.append(op)
        return ops
    dims = parse_board(raw)
    length = parse_length(raw)
    src = parts[0] if parts else None
    if src and re.search(r"\bboard\s*1\b", raw, re.I):
        src = next((p for p in parts if str(p.get("name") or "").endswith(" 1") or p.get("id") == "p1"), src)
    if dims and (wants_new(raw) or not ops):
        op = {
            "op": "add",
            "length_mm": dims[0],
            "width_mm": dims[1],
            "thickness_mm": dims[2],
            "upright": wants_orient(raw) and not _FLAT.search(raw),
        }
        ops.append(op)
        return ops
    if length is not None and (wants_new(raw) or src):
        w = float((src or {}).get("width_mm") or 70)
        t = float((src or {}).get("thickness_mm") or 15)
        op = {
            "op": "add",
            "length_mm": length,
            "width_mm": w,
            "thickness_mm": t,
            "upright": wants_orient(raw) and not _FLAT.search(raw),
        }
        if src and re.search(r"\btop of\b", raw, re.I):
            up = bool(src.get("upright"))
            height = float(src.get("length_mm") if up else src.get("thickness_mm") or 0)
            op["x_mm"] = float(src.get("x_mm") or 0)
            op["y_mm"] = float(src.get("y_mm") or 0)
            op["z_mm"] = float(src.get("z_mm") or 0) + height
            op["upright"] = False
        ops.append(op)
        return ops
    return ops


def _plan_with_model(
    asked: str,
    scene: dict,
    complete: Callable[..., str],
) -> list[dict]:
    from memory.grokrun import extract_json

    prompt = (
        "Scene (millimetres):\n"
        + json.dumps(scene.get("parts") or [], indent=2)
        + "\n\nMatt asked: "
        + asked
        + "\nReturn ops that change the scene."
    )
    raw = complete(
        prompt,
        system=OPS_SYSTEM,
        web=False,
        max_turns=1,
        tools="",
        effort="low",
    )
    data = extract_json(raw or "") or {}
    ops = data.get("ops")
    return ops if isinstance(ops, list) else []


def apply(
    home: JarvisHome,
    asked: str,
    complete: Callable[..., str] | None = None,
) -> tuple[str, str]:
    raw = " ".join((asked or "").split())
    started = ensure_server(home)
    if not api_ok():
        return "I haven't got the bench running, sir.", "down"
    scene = _get(f"{URL}api/scene") or {"parts": []}
    ops = parse_ops(raw, scene)
    if not ops and complete is not None and re.search(
        r"\b(?:add|create|delete|stand|duplicate|copy|offset|move|rotate|resize|"
        r"place|contact|top|horizontal|vertical|board)\b",
        raw,
        re.I,
    ):
        try:
            ops = _plan_with_model(raw, scene, complete)
        except Exception:
            ops = []
    if not ops:
        names = ", ".join(str(p.get("name") or p.get("id")) for p in (scene.get("parts") or []))
        if started:
            open_ui()
        if names:
            return f"On the bench: {names}, sir. Say add, duplicate, move, rotate, or delete.", "idle"
        return (
            "The bench is empty, sir. Give a board size, or duplicate one that is there.",
            "need-dims",
        )
    try:
        out = _post(f"{URL}api/ops", {"ops": ops})
    except Exception as exc:
        return f"The bench failed, sir. {exc}", "error"
    if started:
        open_ui()
    notes = out.get("notes") or []
    if not notes:
        return "On the bench, sir.", "ok"
    return "On the bench, sir. " + "; ".join(str(n) for n in notes) + ".", "ok"
