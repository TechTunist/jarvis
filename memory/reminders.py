"""Timed reminders in the vault. Talk may speak one when due; boot still loads the file."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from memory.home import JarvisHome
from memory.intent import file_line

_TIME_AMPM = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", re.I
)
_TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_DAILY = re.compile(
    r"\b(?:every\s+day|each\s+day|daily|every\s+night|every\s+morning|every\s+evening)\b",
    re.I,
)
_LINE = re.compile(
    r"^-\s*(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2})(?:\s+(daily))?\s+[—-]\s*(.+)$"
)
_STRIP_LEAD = re.compile(
    r"^(?:please\s+)?(?:remind me(?:\s+to)?|set a reminder(?:\s+(?:for|to))?)\s*",
    re.I,
)


@dataclass(frozen=True)
class Reminder:
    hhmm: str
    text: str
    daily: bool = False
    once_on: str | None = None

    @property
    def key(self) -> str:
        if self.daily:
            return f"{self.hhmm} daily - {self.text}"
        if self.once_on:
            return f"{self.once_on} {self.hhmm} - {self.text}"
        return f"{self.hhmm} - {self.text}"

    def bullet(self) -> str:
        return self.key


def reminders_path(home: JarvisHome) -> Path:
    return home.vault / "reminders.md"


def _hhmm(hour: int, minute: int, ampm: str | None = None) -> str:
    h = hour
    m = minute
    if ampm:
        ap = ampm.lower().replace(".", "")
        if ap.startswith("p") and h != 12:
            h += 12
        elif ap.startswith("a") and h == 12:
            h = 0
    if h > 23 or m > 59:
        return ""
    return f"{h:02d}:{m:02d}"


def parse_time(text: str) -> str | None:
    m = _TIME_AMPM.search(text or "")
    if m:
        return _hhmm(int(m.group(1)), int(m.group(2) or 0), m.group(3)) or None
    m = _TIME_24.search(text or "")
    if m:
        return _hhmm(int(m.group(1)), int(m.group(2))) or None
    return None


def is_daily(text: str) -> bool:
    return bool(_DAILY.search(text or ""))


def reminder_body(text: str) -> str:
    t = file_line(text)
    t = _STRIP_LEAD.sub("", t).strip()
    t = _TIME_AMPM.sub("", t)
    t = _TIME_24.sub("", t)
    t = _DAILY.sub("", t)
    t = re.sub(r"\b(?:at|for)\b", " ", t, flags=re.I)
    t = re.sub(r"\b(?:i need to|i have to|i've got to)\b", " ", t, flags=re.I)
    t = " ".join(t.split()).strip(" ,.-")
    if t.lower().startswith("to "):
        t = t[3:].strip()
    if not t:
        return "Reminder"
    return t[0].upper() + t[1:]


def from_utterance(text: str, *, today: str | None = None) -> Reminder | None:
    hhmm = parse_time(text)
    if not hhmm:
        return None
    daily = is_daily(text)
    body = reminder_body(text)
    once = None if daily else (today or datetime.now().date().isoformat())
    return Reminder(hhmm=hhmm, text=body, daily=daily, once_on=once)


def format_from_utterance(text: str, fallback: str = "") -> str:
    rem = from_utterance(text)
    if rem:
        return rem.bullet()
    return fallback or file_line(text)


def parse_file(path: Path) -> list[Reminder]:
    if not path.is_file():
        return []
    found: list[Reminder] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            continue
        found.append(
            Reminder(
                hhmm=m.group(2),
                text=m.group(4).strip(),
                daily=bool(m.group(3)),
                once_on=m.group(1),
            )
        )
    return found


def _fired_path(home: JarvisHome) -> Path:
    return home.cache / "reminders-fired.json"


def _load_fired(home: JarvisHome) -> dict:
    path = _fired_path(home)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_fired(home: JarvisHome, data: dict) -> None:
    home.cache.mkdir(parents=True, exist_ok=True)
    _fired_path(home).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def take_due(home: JarvisHome, now: datetime | None = None) -> list[str]:
    """Speakable lines for reminders due (or overdue) today, once each."""
    now = now or datetime.now().astimezone()
    today = now.date().isoformat()
    cur = f"{now.hour:02d}:{now.minute:02d}"
    fired = _load_fired(home)
    spoken: list[str] = []
    for rem in parse_file(reminders_path(home)):
        if rem.daily:
            if cur < rem.hhmm:
                continue
        elif rem.once_on:
            if today < rem.once_on:
                continue
            if today == rem.once_on and cur < rem.hhmm:
                continue
            if today > rem.once_on:
                pass
        else:
            if cur < rem.hhmm:
                continue
        stamp_key = rem.key
        if fired.get(stamp_key) == today:
            continue
        fired[stamp_key] = today
        spoken.append(f"It's time, sir. {rem.text}.")
    if spoken:
        _save_fired(home, fired)
    return spoken
