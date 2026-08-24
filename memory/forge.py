"""Read-only BearJacked / Supabase training log.

Secrets live in ~/.jarvis/secrets/forge.json — never this git repo.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from memory.home import JarvisHome


def secrets_path(home: JarvisHome) -> Path:
    return home.root / "secrets" / "forge.json"


def session_path(home: JarvisHome) -> Path:
    return home.cache / "forge-session.json"


def load_secrets(home: JarvisHome) -> dict:
    path = secrets_path(home)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _headers(anon: str, token: str = "") -> dict[str, str]:
    h = {
        "apikey": anon,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    else:
        h["Authorization"] = f"Bearer {anon}"
    return h


def _read(req: urllib.request.Request, timeout: float) -> str:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"Forge HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Forge unreachable: {exc.reason}") from exc


def _post_json(url: str, body: dict, headers: dict, timeout: float = 20) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    raw = _read(req, timeout)
    data = json.loads(raw) if raw else {}
    return data if isinstance(data, dict) else {}


def _get_json(url: str, headers: dict, timeout: float = 20) -> list | dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    raw = _read(req, timeout)
    data = json.loads(raw) if raw else []
    return data


def login(home: JarvisHome, secrets: dict | None = None) -> str:
    secrets = secrets if secrets is not None else load_secrets(home)
    url = str(secrets.get("url") or "").rstrip("/")
    anon = str(secrets.get("anon_key") or secrets.get("anon") or "")
    email = str(secrets.get("email") or "")
    password = str(secrets.get("password") or os.environ.get("JARVIS_FORGE_PASSWORD") or "")
    if not url or not anon:
        raise RuntimeError("Forge secrets missing url or anon_key")
    if not email or not password:
        raise RuntimeError("Forge login is not on file")
    dest = f"{url}/auth/v1/token?grant_type=password"
    data = _post_json(
        dest,
        {"email": email, "password": password},
        _headers(anon),
    )
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError("Forge login failed")
    home.cache.mkdir(parents=True, exist_ok=True)
    session_path(home).write_text(
        json.dumps(
            {
                "access_token": token,
                "refresh_token": data.get("refresh_token") or "",
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return token


def access_token(home: JarvisHome) -> str:
    path = session_path(home)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            token = str((data or {}).get("access_token") or "")
            if token:
                return token
        except (OSError, json.JSONDecodeError):
            pass
    return login(home)


def _rest(home: JarvisHome, table: str, query: str, secrets: dict, token: str):
    url = str(secrets.get("url") or "").rstrip("/")
    anon = str(secrets.get("anon_key") or secrets.get("anon") or "")
    dest = f"{url}/rest/v1/{table}?{query}"
    return _get_json(dest, _headers(anon, token))


def _exercise_line(ex: dict) -> str:
    name = str(ex.get("name") or ex.get("exerciseId") or "exercise")
    bits: list[str] = []
    for s in ex.get("sets") or []:
        if not isinstance(s, dict):
            continue
        if s.get("completed") is False:
            continue
        reps = s.get("reps")
        weight = s.get("weight")
        if weight and reps:
            bits.append(f"{weight}×{reps}")
        elif reps:
            bits.append(f"{reps} reps")
        elif s.get("time"):
            bits.append(f"{s.get('time')} min")
    if not bits:
        return name
    return f"{name} " + ", ".join(bits[:8])


def compact_log(
    workouts: list,
    weights: list,
    *,
    limit: int = 6,
) -> str:
    lines: list[str] = []
    for w in (workouts or [])[:limit]:
        if not isinstance(w, dict):
            continue
        day = str(w.get("date") or "")[:10]
        name = str(w.get("name") or "session")
        mins = w.get("duration") or w.get("durationMinutes") or ""
        head = f"{day} {name}".strip()
        if mins:
            head += f" {mins}m"
        lifts = [
            _exercise_line(ex)
            for ex in (w.get("exercises") or [])[:8]
            if isinstance(ex, dict)
        ]
        if lifts:
            head += ": " + "; ".join(lifts)
        lines.append(head)
    for row in (weights or [])[:4]:
        if not isinstance(row, dict):
            continue
        day = str(row.get("logged_date") or row.get("date") or "")[:10]
        kg = row.get("weight")
        if kg is not None:
            lines.append(f"bodyweight {day}: {kg} kg")
    return "\n".join(lines) if lines else "No training rows."


def fetch_brief(home: JarvisHome) -> str:
    secrets = load_secrets(home)
    token = access_token(home)
    workouts = _rest(
        home,
        "workouts",
        "select=date,name,duration,exercises,completed&completed=eq.true&order=date.desc&limit=8",
        secrets,
        token,
    )
    weights = _rest(
        home,
        "bodyweight_logs",
        "select=logged_date,weight&order=logged_date.desc&limit=5",
        secrets,
        token,
    )
    if not isinstance(workouts, list):
        workouts = []
    if not isinstance(weights, list):
        weights = []
    return compact_log(workouts, weights)
