"""Short-term working memory. Session dialogue, not the whole vault."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from memory.home import JarvisHome

_PLACE = re.compile(
    r"weather location is\s+(.+?)(?:\s*$)",
    re.I,
)
_MATT_LINE = re.compile(r"(?i)(?:^|\n)Matt:\s*(.+)\s*$")


def spoken_user(raw: str) -> str:
    """The words Matt said, without a working-memory prefix stuffed into the log."""
    t = (raw or "").strip()
    if t.startswith("[working memory"):
        hit = _MATT_LINE.search(t)
        if hit:
            t = hit.group(1).strip()
        else:
            return ""
    return " ".join(t.split())


def weather_place(home: JarvisHome) -> str:
    path = home.vault / "people" / "_household.md"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        hit = _PLACE.search(line.lstrip("- ").strip())
        if hit:
            return hit.group(1).strip(" .")
    return ""


def recent_turns(
    home: JarvisHome,
    limit: int = 8,
    clip: int = 240,
    *,
    span: str = "session",
) -> list[tuple[str, str]]:
    path = home.sessions / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"
    if not path.is_file():
        return []
    current: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "start":
            if span == "session":
                current = []
            continue
        if ev.get("event") != "turn":
            continue
        user = spoken_user(str(ev.get("user") or ""))
        if not user or user.startswith("[job ") or user.startswith("[reminder]"):
            continue
        reply = " ".join(str(ev.get("reply") or "").split())
        if user:
            current.append((user[:clip], reply[:clip]))
    return current[-limit:]


def pack_recent(
    home: JarvisHome, limit: int = 8, clip: int = 240, *, span: str = "session"
) -> str:
    rows = []
    for user, reply in recent_turns(home, limit=limit, clip=clip, span=span):
        rows.append(f"You: {user}")
        if reply:
            rows.append(f"Jarvis: {reply}")
    return "\n".join(rows)


def desk_prefix(home: JarvisHome) -> str:
    parts: list[str] = []
    place = weather_place(home)
    if place:
        parts.append(f"Weather location: {place}.")
    recent = pack_recent(home)
    if recent:
        parts.append("Recent conversation:\n" + recent)
    if not parts:
        return ""
    return (
        "[working memory — this session only]\n"
        + "\n".join(parts)
        + "\nUse this if Matt refers to something he just said. "
        "Do not claim you have no location when Weather location is set."
    )


def workshop_brief(home: JarvisHome, asked: str, *, limit: int = 10, clip: int = 1600) -> str:
    """What the workshop needs: this ask plus the conversation it refers to."""
    recent = pack_recent(home, limit=limit, clip=clip, span="day")
    chunks: list[str] = []
    if recent:
        chunks.append(
            "Recent conversation (the project brief is in here — use it):\n" + recent
        )
    chunks.append("Matt asked: " + " ".join((asked or "").split()))
    chunks.append(
        "Use the parts, power, radio, and enclosure already chosen in the "
        "conversation. Do not invent a different product. Do not search a "
        "workspace or ask for details that are already above."
    )
    return "\n\n".join(chunks)


def search_prompt(home: JarvisHome, asked: str) -> str:
    place = weather_place(home)
    recent = pack_recent(home, limit=6)
    chunks: list[str] = []
    if place:
        chunks.append(
            f"Default weather location: {place}. "
            "If Matt does not name a city, use this. Do not ask which city."
        )
    if recent:
        chunks.append("Recent conversation:\n" + recent)
    chunks.append("Matt asked: " + asked)
    return "\n\n".join(chunks)
