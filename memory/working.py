"""Short-term working memory. Session dialogue, not the whole vault."""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import IN_FLIGHT, JobBoard

WEATHER_FRESH_S = 6 * 3600

_PLACE = re.compile(
    r"weather location is\s+(.+?)(?:\s*$)",
    re.I,
)
_MATT_LINE = re.compile(r"(?i)(?:^|\n)[A-Za-z][A-Za-z'-]{1,24}:\s*(.+)\s*$")


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


def weather_fresh(home: JarvisHome, *, now: float | None = None) -> bool:
    path = home.cache / "weather.md"
    if not path.is_file():
        return False
    try:
        age = (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return False
    return 0 <= age < WEATHER_FRESH_S


def looks_like_weather(text: str) -> bool:
    raw = " ".join((text or "").split())
    if not raw:
        return False
    if re.search(r"\b(?:look(?:ing)?\s+up|search\s+for|google|headlines|the\s+news)\b", raw, re.I):
        if not re.search(r"\b(?:weather|forecast)\b", raw, re.I):
            return False
    return bool(re.search(r"\b(?:weather|forecast)\b", raw, re.I))


def hands_brief(home: JarvisHome, *, limit: int = 4, clip: int = 120) -> str:
    board = JobBoard(home)
    lines: list[str] = []
    seen: set[str] = set()
    for job_id in reversed(board.job_ids()):
        snap = board.snapshot(job_id)
        ev = str(snap.get("event") or "")
        if ev not in IN_FLIGHT:
            continue
        if job_id in seen:
            continue
        seen.add(job_id)
        cap = str(snap.get("cap") or "job")
        note = " ".join(str(snap.get("note") or ev).split())[:clip]
        asked = " ".join(str(snap.get("prompt") or "").split())[:clip]
        bit = f"{cap}: {note}"
        if asked:
            bit += f" — {asked}"
        lines.append(bit)
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "Busy: " + "; ".join(reversed(lines)) + "."


def last_jobs(home: JarvisHome, *, limit: int = 3, clip: int = 220) -> str:
    """Finished work the mouth may treat as already said."""
    board = JobBoard(home)
    lines: list[str] = []
    for job_id in reversed(board.job_ids()):
        snap = board.snapshot(job_id)
        if str(snap.get("event") or "") != "done":
            continue
        speak = " ".join(str(snap.get("speak") or "").split())[:clip]
        if not speak:
            continue
        cap = str(snap.get("cap") or "job")
        lines.append(f"{cap}: {speak}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "Last jobs: " + " ".join(reversed(lines))


def desk_prefix(home: JarvisHome, person=None) -> str:
    parts: list[str] = []
    if person is not None:
        from memory.people import speaker_note

        note = speaker_note(person)
        if note:
            parts.append(note)
    place = weather_place(home)
    if place:
        parts.append(f"Weather location: {place}.")
    hands = hands_brief(home)
    if hands:
        parts.append("[hands]\n" + hands)
    done = last_jobs(home)
    if done:
        parts.append("[last jobs]\n" + done)
    recent = pack_recent(home)
    if recent:
        parts.append("Recent conversation:\n" + recent)
    if not parts:
        return ""
    return (
        "[working memory — this session only]\n"
        + "\n".join(parts)
        + "\nUse this if they refer to something just said. "
        "Do not claim you have no location when Weather location is set. "
        "If [hands] is present, that work is running — report it if asked; "
        "do not invent extra progress. [last jobs] and Recent conversation "
        "are already true; never deny them."
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
