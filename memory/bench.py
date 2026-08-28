"""Timber bench: millimetre boards Jarvis can place. GUI is a local page."""
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
_DIMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm\b",
    re.I,
)
_DIMS_BY = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm)?\s+by\s+(\d+(?:\.\d+)?)\s*(?:mm)?\s+by\s+(\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.I,
)
_BENCH_PY = Path(__file__).resolve().parent.parent / "bench" / "bench.py"


def parse_board(text: str) -> tuple[float, float, float] | None:
    raw = " ".join((text or "").split())
    hit = _DIMS.search(raw) or _DIMS_BY.search(raw)
    if not hit:
        return None
    return float(hit.group(1)), float(hit.group(2)), float(hit.group(3))


def _get(path: str, timeout: float = 0.6) -> dict | None:
    try:
        with urllib.request.urlopen(path, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def healthy() -> bool:
    return _get(f"{URL}api/scene") is not None


def ensure_server(home: JarvisHome) -> bool:
    if healthy():
        return True
    if not _BENCH_PY.is_file():
        return False
    subprocess.Popen(
        [sys.executable, str(_BENCH_PY), "--data-dir", str(home.root), "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(40):
        time.sleep(0.05)
        if healthy():
            return True
    return False


def add_board(
    home: JarvisHome,
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    name: str = "",
) -> dict:
    if not ensure_server(home):
        raise RuntimeError("bench is not running")
    payload = json.dumps(
        {
            "kind": "board",
            "length_mm": length_mm,
            "width_mm": width_mm,
            "thickness_mm": thickness_mm,
            "name": name,
        }
    ).encode()
    req = urllib.request.Request(
        f"{URL}api/parts",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return json.loads(resp.read().decode())


def open_ui() -> None:
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def apply(home: JarvisHome, asked: str) -> tuple[str, str]:
    """Place a board from the utterance. Opens the bench page."""
    dims = parse_board(asked)
    if dims is None:
        if ensure_server(home):
            open_ui()
            return "The bench is open, sir. Give me length, width, and thickness in millimetres.", "need-dims"
        return "I haven't got the bench running, sir.", "down"
    length_mm, width_mm, thickness_mm = dims
    try:
        add_board(home, length_mm, width_mm, thickness_mm)
    except Exception as exc:
        return f"The bench failed, sir. {exc}", "error"
    open_ui()
    speak = (
        f"On the bench, sir. {length_mm:g} by {width_mm:g} by {thickness_mm:g} millimetres."
    )
    return speak, "ok"
