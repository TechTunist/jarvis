"""Timber bench: millimetre boards Jarvis can place, stand, and delete."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from memory.home import JarvisHome

PORT = 8770
URL = f"http://127.0.0.1:{PORT}/"
API = 2
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
_NEW = re.compile(
    r"\b(?:add|create|make me|another|new)\b",
    re.I,
)
_ORIENT = re.compile(
    r"\b(?:stand(?:ing)?|stood|upright|vertical|on end|orient(?:ed|ation)?)\b",
    re.I,
)
_DELETE = re.compile(
    r"\b(?:delete|remove|drop|get rid of|clear)\b",
    re.I,
)
_BOARD_N = re.compile(
    r"\b(?:board|part|plate|model)\s*(\d+)\b",
    re.I,
)
_DEL_N = re.compile(
    r"\b(?:delete|remove|drop|get rid of)\s+(?:the\s+)?(?:board|part|plate|model)\s*(\d+)\b",
    re.I,
)
_ORIENT_N = re.compile(
    r"\b(?:board|part|plate|model)\s*(\d+)\b.{0,40}\b(?:vertical|upright|stand|end|orient)",
    re.I,
)
_BENCH_PY = Path(__file__).resolve().parent.parent / "bench" / "bench.py"


def parse_board(text: str) -> tuple[float, float, float] | None:
    raw = " ".join((text or "").split())
    hit = _DIMS.search(raw) or _DIMS_BY.search(raw)
    if not hit:
        return None
    return float(hit.group(1)), float(hit.group(2)), float(hit.group(3))


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


def _post(path: str, payload: dict, timeout: float = 2.0) -> dict:
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
    if api_ok():
        return True
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


def apply(home: JarvisHome, asked: str) -> tuple[str, str]:
    """Add, stand, or delete boards from the utterance."""
    raw = " ".join((asked or "").split())
    if not ensure_server(home):
        return "I haven't got the bench running, sir.", "down"
    bits: list[str] = []
    try:
        if wants_delete(raw):
            n = None
            hit = _DEL_N.search(raw)
            if hit:
                n = int(hit.group(1))
            else:
                found = _BOARD_N.findall(raw)
                if found and not wants_orient(raw):
                    n = int(found[0])
                elif len(found) >= 2:
                    n = int(found[1]) if "board 2" in raw.lower() or "board two" in raw.lower() else int(found[-1])
            body = {"n": n} if n is not None else {}
            out = _post(f"{URL}api/delete", body)
            bits.append(f"removed {out.get('deleted') or 'a board'}")
        if wants_orient(raw):
            n = None
            hit = _ORIENT_N.search(raw)
            if hit:
                n = int(hit.group(1))
            else:
                hit = re.search(
                    r"\b(?:make|stand|orient)\s+(?:the\s+)?(?:board|part|plate)\s*(\d+)\b",
                    raw,
                    re.I,
                )
                if hit:
                    n = int(hit.group(1))
                elif re.search(r"\bboard\s*1\b", raw, re.I):
                    n = 1
            dims = parse_board(raw)
            adding = bool(dims) and wants_new(raw)
            if not adding:
                body: dict = {"upright": True}
                if n is not None:
                    body["n"] = n
                out = _post(f"{URL}api/orient", body)
                name = (out.get("part") or {}).get("name") or "the board"
                bits.append(f"{name} standing on end")
        dims = parse_board(raw)
        mutate = wants_delete(raw) or wants_orient(raw)
        if dims and (wants_new(raw) or not mutate):
            length_mm, width_mm, thickness_mm = dims
            _post(
                f"{URL}api/parts",
                {
                    "kind": "board",
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "thickness_mm": thickness_mm,
                    "upright": wants_orient(raw) and wants_new(raw),
                },
            )
            how = "vertical " if wants_orient(raw) and wants_new(raw) else ""
            bits.append(
                f"{how}{length_mm:g} by {width_mm:g} by {thickness_mm:g} millimetres"
            )
    except Exception as exc:
        return f"The bench failed, sir. {exc}", "error"
    open_ui()
    if not bits:
        return (
            "The bench is open, sir. I can add a board, stand one on end, or delete one.",
            "need-dims",
        )
    return "On the bench, sir. " + "; ".join(bits) + ".", "ok"
