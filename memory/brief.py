"""Today's note for the mouth. Only injected when he asked, or a check-in."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from memory.home import JarvisHome

NEWS_FRESH_S = 12 * 3600
_CHECKIN = re.compile(
    r"^(?:(?:so|well|hey|um|uh)\s+)*"
    r"(?:"
    r"how are you(?: doing| feeling)?"
    r"(?: today| this morning| this evening| tonight)?"
    r"|how(?:'s| is) it going"
    r"|how(?:'s| are) things(?: going)?"
    r"|how is everything"
    r"|how you doing"
    r"|how(?:'s| is) (?:your|the) day(?: looking)?"
    r"|what(?:'s| is) going on"
    r"|what(?:'s| is) happening(?: today)?"
    r"|what(?:'s| is) up(?: today)?"
    r"|what(?:'s| is) on(?: today)?"
    r"|what(?:'s| is) the day(?: looking like)?"
    r"|anything I should know"
    r"|what should I know"
    r"|catch me up"
    r"|fill me in"
    r"|bring me up to speed"
    r"|what(?:'s| is) new"
    r"|brief me"
    r")"
    r"(?:[,.]?\s+(?:jarvis|sir|please|then))*[.!?]*$",
    re.I,
)
_DAY = re.compile(
    r"(?:"
    r"\b(?:daily brief|morning brief)\b"
    r"|\bwhat(?:'s| is) on (?:today|this morning|the calendar)\b"
    r"|\banything on (?:today|this morning)\b"
    r"|\b(?:plans today|reminders?(?:\s+today)?)\b"
    r"|\bthe calendar\b"
    r")",
    re.I,
)
_NEWS = re.compile(
    r"(?:"
    r"\bheadlines\b"
    r"|\bthe news\b"
    r"|\bmarkets?\b"
    r"|\bspcx\b"
    r"|\bspace ?x\b"
    r")",
    re.I,
)
_CAL = re.compile(
    r"^-\s*(\d{4}-\d{2}-\d{2}|weekly\s+\w+)\s+[—-]\s*(.+)$",
    re.I,
)
_CACHED = re.compile(r"\n*_cached[^\n]*\s*$", re.I)


def wants_checkin(text: str) -> bool:
    raw = " ".join((text or "").split()).strip()
    return bool(_CHECKIN.match(raw))


def wants_brief(text: str) -> bool:
    """Full day's note: check-in, or they asked about today / the calendar."""
    raw = " ".join((text or "").split()).strip()
    if not raw:
        return False
    return bool(_CHECKIN.match(raw) or _DAY.search(raw))


def looks_like_news(text: str) -> bool:
    raw = " ".join((text or "").split())
    return bool(_NEWS.search(raw))


def news_path(home: JarvisHome) -> Path:
    return home.cache / "news.md"


def calendar_path(home: JarvisHome) -> Path:
    return home.vault / "calendar.md"


def news_fresh(home: JarvisHome, *, now: float | None = None) -> bool:
    path = news_path(home)
    if not path.is_file():
        return False
    try:
        age = (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return False
    return 0 <= age < NEWS_FRESH_S


def _clip(text: str, limit: int) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def weather_note(home: JarvisHome) -> str:
    return _cache_body(home.cache / "weather.md")


def news_note(home: JarvisHome) -> str:
    return _cache_body(news_path(home))


def _cache_body(path: Path, limit: int = 280) -> str:
    if not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    raw = _CACHED.sub("", raw).strip()
    return _clip(raw, limit)


def _reminders_line(home: JarvisHome) -> str:
    from memory.reminders import parse_file, reminders_path

    rows = parse_file(reminders_path(home))
    if not rows:
        return ""
    bits = []
    for rem in rows:
        if rem.daily:
            bits.append(f"{rem.hhmm} daily {rem.text}")
        elif rem.once_on == date.today().isoformat():
            bits.append(f"{rem.hhmm} {rem.text}")
    if not bits:
        return ""
    return "Reminders: " + "; ".join(bits) + "."


def _calendar_line(home: JarvisHome, today: date) -> str:
    path = calendar_path(home)
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    weekday = today.strftime("%a")
    hits: list[str] = []
    for raw in lines:
        m = _CAL.match(raw.strip())
        if not m:
            continue
        when, what = m.group(1), m.group(2).strip()
        if when.lower().startswith("weekly"):
            day = when.split(None, 1)[-1][:3]
            if day.lower() == weekday.lower():
                hits.append(what)
        elif when == today.isoformat():
            hits.append(what)
    if not hits:
        return ""
    return "Calendar: " + "; ".join(hits) + "."


def assemble_brief(home: JarvisHome, *, today: date | None = None, now: float | None = None) -> str:
    """Local snapshot. No web. Empty bits are omitted."""
    today = today or date.today()
    bits = [f"Today {today.strftime('%A')} {today.day} {today.strftime('%b %Y')}."]
    rem = _reminders_line(home)
    if rem:
        bits.append(rem)
    cal = _calendar_line(home, today)
    if cal:
        bits.append(cal)
    weather = _cache_body(home.cache / "weather.md")
    if weather:
        bits.append("Weather: " + weather)
    if news_fresh(home, now=now):
        news = _cache_body(news_path(home))
        if news:
            bits.append("News: " + news)
    text = " ".join(bits)
    return _clip(text, 700)
