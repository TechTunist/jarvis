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


_NOISE = re.compile(
    r"\b(?:the|a|an|to|please|jarvis|your|my|our|me)\b",
    re.I,
)


def reminder_norm(text: str) -> str:
    t = " ".join((text or "").lower().split())
    t = t.strip(" .,-")
    t = _NOISE.sub(" ", t)
    return " ".join(t.split())


def similar_body(a: str, b: str) -> bool:
    na, nb = reminder_norm(a), reminder_norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short.split()) < 2:
        return False
    return short in long_


def similar_reminder(a: Reminder, b: Reminder) -> bool:
    if a.hhmm != b.hhmm or bool(a.daily) != bool(b.daily):
        return False
    if (a.once_on or "") != (b.once_on or ""):
        return False
    return similar_body(a.text, b.text)


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


def parse_one(text: str) -> Reminder | None:
    raw = " ".join((text or "").split()).lstrip("- ").strip()
    m = _LINE.match("- " + raw)
    if m:
        return Reminder(
            hhmm=m.group(2),
            text=m.group(4).strip(),
            daily=bool(m.group(3)),
            once_on=m.group(1),
        )
    return from_utterance(text)


def parse_file(path: Path) -> list[Reminder]:
    if not path.is_file():
        return []
    found: list[Reminder] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not _LINE.match(stripped):
            continue
        rem = parse_one(stripped)
        if rem:
            found.append(rem)
    return found


def _append_line(path: Path, bullet: str) -> bool:
    bullet = " ".join((bullet or "").split()).lstrip("- ").strip()
    if not bullet:
        return False
    line = f"- {bullet}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if bullet in text:
            return False
        with path.open("a", encoding="utf-8") as fh:
            if text and not text.endswith("\n"):
                fh.write("\n")
            fh.write(line)
    else:
        path.write_text(line, encoding="utf-8")
    return True


def collapse_file(path: Path) -> int:
    """Keep one bullet per similar reminder. Returns how many lines dropped."""
    if not path.is_file():
        return 0
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    kept: list[Reminder] = []
    out: list[str] = []
    dropped = 0
    for raw in raw_lines:
        stripped = raw.strip()
        if not _LINE.match(stripped):
            out.append(raw)
            continue
        rem = parse_one(stripped)
        if rem is None:
            out.append(raw)
            continue
        twin = next((k for k in kept if similar_reminder(rem, k)), None)
        if twin is None:
            kept.append(rem)
            out.append(f"- {rem.bullet()}")
            continue
        dropped += 1
        if len(rem.text) > len(twin.text):
            kept[kept.index(twin)] = rem
            for i, line in enumerate(out):
                if line.strip() == f"- {twin.bullet()}":
                    out[i] = f"- {rem.bullet()}"
                    break
    if dropped:
        text = "\n".join(out).rstrip() + "\n"
        path.write_text(text, encoding="utf-8")
    return dropped


def file_reminder(home: JarvisHome, text: str) -> bool:
    path = reminders_path(home)
    collapse_file(path)
    rem = parse_one(text)
    if rem is None:
        return _append_line(path, " ".join((text or "").split()).lstrip("- "))
    existing = parse_file(path)
    if any(similar_reminder(rem, e) for e in existing):
        return False
    return _append_line(path, rem.bullet())


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


def _is_due(rem: Reminder, today: str, cur: str) -> bool:
    if rem.daily:
        return cur >= rem.hhmm
    if rem.once_on:
        if today < rem.once_on:
            return False
        if today == rem.once_on:
            return cur >= rem.hhmm
        return True
    return cur >= rem.hhmm


def take_due(home: JarvisHome, now: datetime | None = None) -> list[str]:
    """Speakable lines for reminders due (or overdue) today, once each cluster."""
    now = now or datetime.now().astimezone()
    today = now.date().isoformat()
    cur = f"{now.hour:02d}:{now.minute:02d}"
    path = reminders_path(home)
    due = [rem for rem in parse_file(path) if _is_due(rem, today, cur)]
    if due:
        collapse_file(path)
        due = [rem for rem in parse_file(path) if _is_due(rem, today, cur)]
    fired = _load_fired(home)
    spoken: list[str] = []
    used: set[int] = set()
    for rem in due:
        if id(rem) in used:
            continue
        cluster = [other for other in due if similar_reminder(rem, other)]
        if all(fired.get(r.key) == today for r in cluster):
            used.update(id(r) for r in cluster)
            continue
        pick = max(cluster, key=lambda r: (len(r.text), r.text))
        for r in cluster:
            fired[r.key] = today
            used.add(id(r))
        spoken.append(f"It's time, sir. {pick.text}.")
    if spoken:
        _save_fired(home, fired)
    return spoken
