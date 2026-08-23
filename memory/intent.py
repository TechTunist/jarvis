"""Local intent gate. False positives steal hellos — prefer chat.

No Grok call. The receptionist stays tool-free; this only decides whether
Talk should enqueue a workshop job or send the turn to the desk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from memory.jobs import JobBoard
from memory.workshops import WorkshopRegistry


@dataclass(frozen=True)
class Intent:
    kind: str
    cap: str | None
    ack: str
    wait_s: float


CHAT = Intent("chat", None, "", 0.0)
SEARCH = Intent("search", "search", "I'll look into that, sir.", 75.0)
REMEMBER = Intent("remember", "vault-write", "I'll file that, sir.", 20.0)
HOME = Intent("home", "home", "I'll see to the house, sir.", 25.0)
CODE = Intent("code", "shell", "I'll send that to the workshop, sir.", 75.0)

_REMEMBER = re.compile(
    r"(?:please\s+)?(?:"
    r"remember[,:]?\s+(?:that|this|i|we|my)\b"
    r"|remind me\b"
    r"|set a reminder\b"
    r"|a reminder\s+(?:for|at|to)\b"
    r"|don't\s+forget\b"
    r"|do\s+not\s+forget\b"
    r"|file\s+this\b"
    r"|add\s+this\s+to\s+(?:the\s+)?(?:vault|notes|memory)\b"
    r"|never\s+(?:do|say|call|remind|ask)\b"
    r")",
    re.I,
)
_REMEMBER_PREFIX = re.compile(
    r"^(?:please\s+)?(?:"
    r"remember[,:]?\s+(?:that\s+|this\s+)?"
    r"|remind me(?:\s+to)?\s+"
    r"|set a reminder(?:\s+(?:for|to))?\s+"
    r"|don't\s+forget\s+(?:that\s+|to\s+)?"
    r"|do\s+not\s+forget\s+(?:that\s+|to\s+)?"
    r"|file\s+this(?:\s*:)?\s*"
    r")",
    re.I,
)
_HOME_NOUN = (
    r"lights?|lamps?|locks?|doors?|garage|gate|thermostat|"
    r"heating|boiler|blinds?|curtains?|alarm|outlet"
)
_HOME = re.compile(
    r"(?:"
    r"\b(?:turn(?:ed)?\s+(?:on|off)|switch(?:ed)?\s+(?:on|off)|dim|unlock|lock)\b"
    r".{0,40}\b(?:" + _HOME_NOUN + r")\b"
    r"|"
    r"\bturn\s+(?:the\s+)?(?:\w+\s+){0,3}(?:" + _HOME_NOUN + r")\s+(?:on|off)\b"
    r"|"
    r"\b(?:" + _HOME_NOUN + r")\b"
    r".{0,40}\b(?:turn\s+(?:on|off)|switch\s+(?:on|off)|lock|unlock|open|close|dim)\b"
    r"|"
    r"\b(?:lights?|lamps?)\s+(?:on|off)\b"
    r"|"
    r"\b(?:open|close|shut)\s+(?:the\s+)?(?:garage|gate|door)s?\b"
    r"|"
    r"\b(?:is|are)\s+the\s+(?:garage|doors?|lights?|lamps?|gate|thermostat|heating)\b"
    r"|"
    r"\b(?:set|what's|what is)\s+(?:the\s+)?(?:thermostat|heating|boiler)\b"
    r")",
    re.I,
)

_CODE = re.compile(
    r"(?:"
    r"\b(?:run\s+(?:the\s+)?tests?|pytest|git\s+commit|pull\s+request)\b"
    r"|\b(?:this|the|our)\s+repo\b"
    r"|\b(?:ableton|fusion(?:\s*360)?)\b"
    r")",
    re.I,
)

_SEARCH = re.compile(
    r"(?:"
    r"\bweather\b"
    r"|\bforecast\b"
    r"|\b(?:look(?:ing)?\s+up|look\s+it\s+up|search\s+for|google)\b"
    r"|\bheadlines\b"
    r"|\bthe\s+news\b"
    r"|\bstock\s+price\b"
    r"|\bshare\s+price\b"
    r"|\bwhat(?:'s| is) the score\b"
    r")",
    re.I,
)


def classify(text: str) -> Intent:
    raw = " ".join((text or "").split())
    if len(raw) < 2:
        return CHAT
    if _REMEMBER.search(raw):
        return REMEMBER
    if _HOME.search(raw):
        return HOME
    if _CODE.search(raw):
        return CODE
    if _SEARCH.search(raw):
        return SEARCH
    return CHAT


def file_line(text: str) -> str:
    """Utterance minus the 'remember that' wrapper, for a vault bullet."""
    t = " ".join((text or "").split())
    t = _REMEMBER_PREFIX.sub("", t).strip()
    t = t.strip(" .")
    if not t:
        return ""
    return t[0].upper() + t[1:]


def remember_dest(text: str) -> str:
    raw = text or ""
    if re.search(r"\bnever\s+(?:do|say|call|remind|ask)\b", raw, re.I):
        return "never"
    if re.search(r"\bremind(?:er|ers)?\b", raw, re.I):
        return "reminders"
    if re.search(r"\b(?:every\s+day|each\s+day|daily)\b", raw, re.I):
        return "reminders"
    if re.search(r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b", raw, re.I):
        return "reminders"
    if re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", raw):
        return "reminders"
    if re.search(r"\bnever\b", raw, re.I):
        return "never"
    return "household"


def maybe_enqueue(
    text: str,
    board: JobBoard,
    registry: WorkshopRegistry,
    extra: dict | None = None,
) -> tuple[Intent, str] | None:
    """Enqueue if this is work and a live worker has the cap. Else None (desk)."""
    payload = dict(extra or {})
    if registry.has_cap("home"):
        from memory.ha import (
            is_house_followup,
            is_no,
            is_yes,
            pending_clarify,
            pending_confirm,
        )

        if pending_confirm(board.home):
            if is_yes(text) or is_no(text):
                payload["kind"] = "home"
                payload["confirm"] = is_yes(text)
                job_id = board.enqueue("home", text, extra=payload)
                return HOME, job_id
        if pending_clarify(board.home) and is_house_followup(text):
            payload["kind"] = "home"
            job_id = board.enqueue("home", text, extra=payload)
            return HOME, job_id
    intent = classify(text)
    if not intent.cap or not registry.has_cap(intent.cap):
        return None
    payload["kind"] = intent.kind
    if intent.cap == "vault-write" and "dest" not in payload:
        payload["dest"] = remember_dest(text)
    job_id = board.enqueue(intent.cap, text, extra=payload)
    return intent, job_id
