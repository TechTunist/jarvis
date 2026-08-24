"""Mouth may request hands. The model decides; regex does not enumerate English."""
from __future__ import annotations

import re

from memory.route import intent_for_cap

# Last line (or any line) the mouth uses to kick the other thread.
_LINE = re.compile(
    r"\[hands:([a-z][a-z0-9-]{0,24})\]\s*(.*)$",
    re.I | re.M,
)
_MARK = re.compile(r"\[hands:", re.I)
_SENT = re.compile(r"(?<=[.!?])(?:\s+|(?=[A-Z]))")
# Work-narration the hands model prefixes before the answer. Keep the answer.
_PLAN = re.compile(
    r"^(?:"
    r"checking\b"
    r"|searching\b"
    r"|fetching\b"
    r"|confirming\b"
    r"|looking (?:that|it|this|them)?\s*up\b"
    r"|let me\b"
    r"|i(?:'ll| will)\s+(?:check|search|look|fetch|find|get|confirm|judge)\b"
    r")",
    re.I,
)


def parse_hands(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for hit in _LINE.finditer(text or ""):
        cap = hit.group(1).lower()
        task = " ".join((hit.group(2) or "").split())
        found.append((cap, task))
    return found


def split_public(text: str) -> tuple[str, str]:
    """Speech for Matt vs the [hands:] block (never for ears)."""
    raw = text or ""
    hit = _MARK.search(raw)
    if not hit:
        return raw.strip(), ""
    return raw[: hit.start()].strip(), raw[hit.start() :].strip()


def strip_hands(text: str) -> str:
    public, _priv = split_public(text)
    return " ".join(public.split())


def audible(text: str) -> str:
    """Drop [hands:] and leading 'I'm checking…' asides. Keep the answer."""
    public = strip_hands(text)
    if not public:
        return ""
    parts: list[str] = []
    buf = public
    while buf:
        m = _SENT.search(buf)
        if not m:
            parts.append(buf.strip())
            break
        sent, buf = buf[: m.end()].strip(), buf[m.end() :]
        if sent:
            parts.append(sent)
    keep: list[str] = []
    skipping = True
    for sent in parts:
        if skipping and _PLAN.match(sent):
            continue
        skipping = False
        keep.append(sent)
    return " ".join(keep)


def intents_from_mouth(text: str, asked: str):
    """Caps the mouth named, as job intents. Unknown caps are ignored."""
    jobs = []
    for cap, task in parse_hands(text):
        intent = intent_for_cap(cap, task or asked)
        if not getattr(intent, "cap", None):
            continue
        jobs.append((task or asked, intent))
    return jobs
