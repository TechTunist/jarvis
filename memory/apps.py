"""Catalogue of local apps. Facts for the hands, not a phrase router."""
from __future__ import annotations

import json
from pathlib import Path

from memory.home import JarvisHome

_DEFAULT = (
    {
        "id": "bench",
        "names": ("bench", "timber", "lumber", "3d model", "bit of wood"),
        "root": str(Path(__file__).resolve().parent.parent / "bench"),
        "start": "python3 bench.py",
        "url": "http://127.0.0.1:8770",
        "health": "http://127.0.0.1:8770/api/scene",
        "hint": (
            "Millimetre timber bench. If down, python3 bench.py (port 8770). "
            "Add: POST /api/parts JSON length_mm,width_mm,thickness_mm, optional upright true. "
            "Stand a board: POST /api/orient {\"n\":1,\"upright\":true}. "
            "Delete: POST /api/delete {\"n\":2}. Scene: GET /api/scene. "
            "Open UI: xdg-open http://127.0.0.1:8770 ."
        ),
    },
    {
        "id": "watcher",
        "names": ("watcher", "deal hunter", "outlier"),
        "root": str(Path.home() / "watcher"),
        "start": "./run.sh",
        "url": "http://127.0.0.1:8765",
        "health": "http://127.0.0.1:8765/api/health",
        "hint": (
            "If down, start with ./run.sh (background). "
            "Hunt: curl -sS -X POST http://127.0.0.1:8765/api/hunt/run . "
            "Deals: curl -sS http://127.0.0.1:8765/api/deals . "
            "Dashboard: curl -sS http://127.0.0.1:8765/api/dashboard . "
            "Open UI: xdg-open or brave-browser http://127.0.0.1:8765 ."
        ),
    },
    {
        "id": "architectural",
        "names": ("architectural", "sitebrief", "site brief"),
        "root": str(Path.home() / "architectural"),
        "start": "python3 run.py",
        "url": "http://127.0.0.1:8001",
        "health": "http://127.0.0.1:8001/api/reports",
        "hint": (
            "If down, start with python3 run.py (background, port 8001). "
            "Reports: curl -sS http://127.0.0.1:8001/api/reports . "
            "Open UI: xdg-open http://127.0.0.1:8001 ."
        ),
    },
    {
        "id": "reporting",
        "names": ("reporting", "dossiers", "crime dossiers"),
        "root": str(Path.home() / "reporting" / "policy-crime-dossiers"),
        "start": "",
        "url": str(Path.home() / "reporting" / "policy-crime-dossiers" / "index.html"),
        "health": "",
        "hint": (
            "Static page. Data is data/cases.json — read that file, do not dump the whole dossier. "
            "Open: xdg-open index.html in that folder."
        ),
    },
)


def _path(home: JarvisHome) -> Path:
    return home.root / "apps.json"


def load_apps(home: JarvisHome) -> list[dict]:
    dest = _path(home)
    if dest.is_file():
        try:
            raw = json.loads(dest.read_text(encoding="utf-8"))
            if isinstance(raw, list) and raw:
                return raw
        except (OSError, json.JSONDecodeError):
            pass
    return [dict(row) for row in _DEFAULT]


def match_app(text: str, home: JarvisHome | None = None) -> dict | None:
    raw = " ".join((text or "").lower().split())
    if not raw:
        return None
    apps = load_apps(home) if home is not None else [dict(row) for row in _DEFAULT]
    for app in apps:
        names = app.get("names") or (app.get("id"),)
        for name in names:
            n = str(name or "").lower()
            if n and n in raw:
                return app
    return None


def roots_for_shell(home: JarvisHome, repo: Path) -> list[str]:
    found = [str(repo.resolve())]
    for app in load_apps(home):
        root = Path(str(app.get("root") or "")).expanduser()
        if root.is_dir():
            s = str(root.resolve())
            if s not in found:
                found.append(s)
    return found


def brief_for_prompt(home: JarvisHome, asked: str = "") -> str:
    app = match_app(asked, home)
    rows = [app] if app else load_apps(home)
    lines = [
        "Local apps (use curl on localhost or read JSON files — do not screenshot, "
        "do not send pictures off the machine):"
    ]
    for app in rows:
        if not app:
            continue
        bit = f"- {app.get('id')}: root {app.get('root')}. {app.get('hint') or ''}"
        lines.append(bit.strip())
    return "\n".join(lines)
