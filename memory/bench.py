"""Timber bench: millimetre boards Jarvis can add, move, rotate, duplicate, delete."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

from memory.grokrun import NO_MEDIA
from memory.home import JarvisHome
from memory.prompt import HANDS_RULES

PORT = 8770
URL = f"http://127.0.0.1:{PORT}/"
API = 4
_DIMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\b",
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
    r"(?:long\b|instead of)"
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
_OPEN = re.compile(
    r"(?:"
    r"\b(?:open|show|bring up)\b.{0,40}\bbench\b"
    r"|\b(?:work on|working on)\b.{0,24}\bbench\b"
    r"|\bbench\b.{0,40}\b(?:open|tab|window|browser)"
    r"|\b(?:browser\s+)?tab\b.{0,40}\bbench\b"
    r")",
    re.I,
)
_CLOSE = re.compile(
    r"(?:"
    r"\b(?:close|stop|quit|kill|shut(?:\s+down)?)\b.{0,40}\bbench\b"
    r"|\bbench\b.{0,24}\b(?:close|stop|quit)"
    r")",
    re.I,
)
_BENCH_PY = Path(__file__).resolve().parent.parent / "bench" / "bench.py"
BENCH_SYSTEM = (
    HANDS_RULES
    + "You are on Matt's PC. Use Grok Build tools — terminal, files, grep, edit. "
    "He spoke a goal. Reason about it. Then act. Do not pattern-match his English. "
    "The millimetre bench is a local app in this checkout (bench/), "
    f"HTTP {URL} (health GET {URL}api/health, scene GET {URL}api/scene, "
    f"ops POST {URL}api/ops). "
    "Camera look-at is millimetres (x along, y across, z up) on scene.camera. "
    "Pan: POST /api/ops {\"ops\":[{\"op\":\"pan\",\"dx_mm\":200}]}. "
    "Look at a board: {\"op\":\"look_at\",\"n\":3}. Frame all: {\"op\":\"frame\"}. "
    "If it is down, start it. If he wants a window, open one (DISPLAY=:0 if unset). "
    "If he wants it closed or stopped, kill the process and confirm health fails — "
    "that is close; do not recite the parts list. "
    "Do the job with the running app first: curl the scene, POST ops, open or kill "
    "the process. If a parser missed a number he already said, POST that number. "
    "Only edit the checkout if you cannot complete THIS request without it. "
    "Do not spend the turn rewriting parsers. If you must patch: branch "
    "jarvis/workshop-<short-slug>, edit, python3 -m unittest discover -s tests, then "
    "finish the job. Never git push, merge, commit to main, or restart Talk. "
    "No Imagine. Do not screenshot. Never touch ~/.jarvis/secrets. "
    "Do not invent millimetre coordinates when you can write a solver or use one. "
    "Never report success you did not verify. "
    "When finished, JSON only: "
    '{"speak":"<what you did; if it failed, why>","ok":true,"branch":"<name or empty>"}. '
    "ok is true only if the asked work actually happened. No markdown, no preamble."
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


def wants_open(text: str) -> bool:
    return bool(_OPEN.search(text or ""))


def wants_close(text: str) -> bool:
    return bool(_CLOSE.search(text or ""))


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
    err_path = home.root / "logs" / "bench.stderr"
    err_path.parent.mkdir(parents=True, exist_ok=True)
    with err_path.open("ab") as err:
        subprocess.Popen(
            [sys.executable, str(_BENCH_PY), "--data-dir", str(home.root), "--port", str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=err,
            start_new_session=True,
        )
    for _ in range(50):
        time.sleep(0.05)
        if api_ok():
            return True
    return False


def _desktop_env() -> dict[str, str]:
    env = dict(os.environ)
    if not env.get("DISPLAY") and Path("/tmp/.X11-unix/X0").exists():
        env["DISPLAY"] = ":0"
    uid = os.getuid()
    runtime = Path(f"/run/user/{uid}")
    if runtime.is_dir():
        env.setdefault("XDG_RUNTIME_DIR", str(runtime))
        bus = runtime / "bus"
        if bus.exists():
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus}")
    return env


def open_ui() -> bool:
    env = _desktop_env()
    for cmd in (("xdg-open", URL), ("gio", "open", URL)):
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            return True
        except OSError:
            continue
    try:
        return bool(webbrowser.open(URL))
    except Exception:
        return False


def close_server() -> bool:
    _stop_listener()
    if api_ok() or healthy():
        _stop_listener()
    return not (api_ok() or healthy())


def _board_n(text: str, default: int | None = None) -> int | None:
    found = [int(x) for x in _BOARD_N.findall(text or "")]
    if found:
        return found[0]
    return default


def parse_ops(asked: str, scene: dict) -> list[dict]:
    """Deterministic CAD ops. Empty means ask the hands model or report the scene."""
    from bench.design import is_design_request

    raw = " ".join((asked or "").split())
    if is_design_request(raw):
        return []
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


def reason(
    home: JarvisHome,
    asked: str,
    scene: dict,
    complete: Callable[..., str],
) -> tuple[str, str]:
    """Hands Grok with a terminal — same class of work as this coding window."""
    from memory.apps import brief_for_prompt
    from memory.shell import repo_root, speak_from_grok
    from memory.working import pack_recent

    root = repo_root()
    up = api_ok()
    chunks = [
        brief_for_prompt(home, asked),
        f"Checkout: {root}. Bench code: {root / 'bench'}.",
        f"Server is {'up' if up else 'down'} at {URL} (api {API}+).",
        f"Data dir: {home.root}",
        f"Start: {sys.executable} {_BENCH_PY} --data-dir {home.root} --port {PORT}",
        "Scene:\n" + json.dumps(scene, indent=2)[:6000],
    ]
    recent = pack_recent(home, limit=8, clip=400, span="day")
    if recent:
        chunks.append("Recent conversation:\n" + recent)
    chunks.append("Matt asked: " + " ".join((asked or "").split()))
    chunks.append(
        "Reason about that goal. Use the API now. Verify. Then the JSON."
    )
    try:
        raw = complete(
            "\n\n".join(chunks),
            system=BENCH_SYSTEM,
            web=False,
            max_turns=16,
            timeout=600,
            disallowed=NO_MEDIA,
            effort="high",
            cwd=root,
            subagents=True,
        )
    except TimeoutError:
        return (
            "I ran out of time on that, sir. I had started and didn't finish.",
            "timeout",
        )
    speak, status = speak_from_grok(raw or "")
    if not speak:
        speak = "I tried, sir, and I haven't got a clear result."
        status = "blocked"
    return speak, status


def _design_ops(asked: str, scene: dict) -> tuple[list[dict], str, str] | None:
    """Stock / site / a full layout. None means this is ordinary CAD."""
    from bench.design import (
        hints_to_scene,
        parse_brief,
        parse_site,
        parse_stock,
        site_to_scene,
        speak_stock,
        stock_to_scene,
    )

    brief = parse_brief(asked, scene)
    spoken_stock = parse_stock(asked)
    spoken_site = parse_site(asked)
    ops: list[dict] = []
    if spoken_stock:
        ops.append({"op": "set_stock", "stock": stock_to_scene(spoken_stock)})
    if spoken_site.any():
        ops.append({"op": "set_site", "site": site_to_scene(brief.site)})
    if brief.wants_design:
        if brief.hints.any():
            ops.append({"op": "set_hints", "hints": hints_to_scene(brief.hints)})
        if not brief.stock:
            return ops, "I haven't got the timber inventory, sir. Give me the pile first.", "need-stock"
        if brief.site.width_mm <= 0:
            return (
                ops,
                "How wide is the alley, sir, and what headroom at the midpoint?",
                "need-site",
            )
        ops.append({"op": "clear"})
        ops.append({"op": "design"})
        return ops, "", "design"
    if spoken_stock:
        return ops, speak_stock(brief.stock, brief.site), "stock"
    return None


def _run_ops(ops: list[dict], *, show: bool) -> tuple[str, str]:
    try:
        out = _post(f"{URL}api/ops", {"ops": ops})
    except Exception as exc:
        return f"The bench failed, sir. {exc}", "error"
    if show:
        open_ui()
    notes = out.get("notes") or []
    if not notes:
        return "On the bench, sir.", "ok"
    return "On the bench, sir. " + "; ".join(str(n) for n in notes) + ".", "ok"


def apply(
    home: JarvisHome,
    asked: str,
    complete: Callable[..., str] | None = None,
) -> tuple[str, str]:
    from bench.design import check_from_scene, clean, speak_design, stock_from_scene

    raw = clean(asked)
    scene = _get(f"{URL}api/scene") or {"parts": []} if api_ok() else {"parts": []}

    # Live hands get a Grok with a terminal. Tests without a model keep
    # the local close/open helpers.
    if complete is None and wants_close(raw):
        close_server()
        return "The bench is closed, sir.", "closed"

    planned = None if wants_close(raw) else _design_ops(raw, scene)
    ops = [] if planned is not None else parse_ops(raw, scene)
    cad = bool(ops) or (
        planned is not None
        and planned[2] in {"design", "stock", "need-stock", "need-site"}
    )

    if cad:
        started = ensure_server(home)
        if not api_ok():
            return "I haven't got the bench running, sir.", "down"
        show = started or wants_open(raw)
        scene = _get(f"{URL}api/scene") or scene
        if planned is not None:
            ops, speak, kind = planned
            if ops:
                try:
                    out = _post(f"{URL}api/ops", {"ops": ops})
                except Exception as exc:
                    return f"The bench failed, sir. {exc}", "error"
                scene = out.get("scene") or scene
            if show:
                open_ui()
            if kind == "design" and (scene.get("parts") or []):
                notes = list(scene.get("notes") or [])
                return (
                    speak_design(
                        check_from_scene(scene), notes, stock_from_scene(scene)
                    ),
                    "ok",
                )
            if kind == "design":
                notes = list(scene.get("notes") or [])
                why = notes[0] if notes else speak
                return why or "I couldn't place a structure with that pile, sir.", "blocked"
            if speak:
                return speak, kind
            return "Stock on file, sir.", kind
        return _run_ops(ops, show=show)

    if complete is not None:
        try:
            return reason(home, raw, scene, complete)
        except Exception as exc:
            return f"The bench failed, sir. {exc}", "error"

    if wants_close(raw):
        close_server()
        return "The bench is closed, sir.", "closed"
    started = ensure_server(home)
    if not api_ok():
        return "I haven't got the bench running, sir.", "down"
    if wants_open(raw):
        open_ui()
        return "The bench is open, sir.", "ok"
    names = ", ".join(
        str(p.get("name") or p.get("id")) for p in (scene.get("parts") or [])
    )
    if started:
        open_ui()
    if names:
        return (
            f"On the bench: {names}, sir. Say add, duplicate, move, rotate, or delete.",
            "idle",
        )
    return (
        "The bench is empty, sir. Give a board size, or duplicate one that is there.",
        "need-dims",
    )
