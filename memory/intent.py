"""Intent gate. Regex is a high-precision fast path; Grok routes the rest.

False positives steal hellos — when unsure, chat. The desk stays tool-free.
"""
from __future__ import annotations

import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from memory.imagine import wants_animation
from memory.jobs import JobBoard
from memory.workshops import WorkshopRegistry


@dataclass(frozen=True)
class Intent:
    kind: str
    cap: str | None
    ack: str
    wait_s: float


CHAT = Intent("chat", None, "", 0.0)
SEARCH = Intent("search", "search", "I'll look into that, sir.", 0.0)
REMEMBER = Intent("remember", "vault-write", "I'll file that, sir.", 0.0)
HOME = Intent("home", "home", "I'll see to the house, sir.", 25.0)
IMAGINE = Intent("imagine", "imagine", "I'll have that drawn, sir.", 0.0)
ANIMATE = Intent("imagine", "imagine", "I'll animate that, sir.", 0.0)
DOCS = Intent("docs", "docs", "I'll write that up, sir.", 0.0)
STATUS = Intent("status", None, "", 0.0)
HUSH = Intent("hush", None, "", 0.0)
CODE = Intent("code", "shell", "I'll send that to the workshop, sir.", 0.0)
FORGE = Intent("forge", "forge", "I'll check the log, sir.", 0.0)

_ACKS = {
    "search": (
        "I'll look into that, sir.",
        "One moment, sir.",
        "Checking now, sir.",
        "On it, sir.",
        "Leave that with me, sir.",
    ),
    "remember": (
        "I'll file that, sir.",
        "Into the vault, sir.",
        "Noted and filing, sir.",
    ),
    "home": (
        "I'll see to the house, sir.",
        "Seeing to that, sir.",
        "Right away, sir.",
        "On the house, sir.",
    ),
    "imagine": (
        "I'll have that drawn, sir.",
        "Drawing that up, sir.",
        "On the easel, sir.",
    ),
    "animate": (
        "I'll animate that, sir.",
        "Motion coming up, sir.",
        "I'll set that moving, sir.",
    ),
    "code": (
        "I'll send that to the workshop, sir.",
        "Workshop can take that, sir.",
    ),
    "docs": (
        "I'll write that up, sir.",
        "Drafting that document, sir.",
        "Guide coming up, sir.",
    ),
    "forge": (
        "I'll check the log, sir.",
        "Looking at your training, sir.",
        "One moment, sir.",
    ),
}
_last_ack: dict[str, str] = {}


def _ack_key(intent: Intent) -> str:
    if intent.kind == "imagine" and "animate" in (intent.ack or "").lower():
        return "animate"
    return intent.kind


def pick_ack(intent: Intent) -> str:
    key = _ack_key(intent)
    pool = _ACKS.get(key) or (intent.ack,)
    prev = _last_ack.get(key)
    choices = [a for a in pool if a != prev] or list(pool)
    chosen = random.choice(choices)
    _last_ack[key] = chosen
    return chosen


def with_ack(intent: Intent) -> Intent:
    if not intent.cap:
        return intent
    return replace(intent, ack=pick_ack(intent))

_HUSH = re.compile(
    r"(?:"
    r"\bbe\s+quiet\b"
    r"|\bshut\s+up\b"
    r"|\b(?:stop|sotp)\s+all\s+talking\b"
    r"|\b(?:stop|sotp)\s+(?:talking|speaking)\b"
    r"|\bhush\b"
    r"|\bsilence\b"
    r")",
    re.I,
)

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
_FORGET = re.compile(
    r"\b(?:forget|remove|delete|scratch|strike)\b|\bmisunderstanding\b",
    re.I,
)
_PLACE_UPDATE = re.compile(
    r"(?:"
    r"\b(?:change|update|set|switch)\b.{0,50}\b(?:weather|location)\b"
    r"|\bweather should\b"
    r"|\bI live in\b"
    r"|\bI(?:'m| am) in\b"
    r"|\bnot in london\b"
    r"|\bedit (?:the )?(?:vault|markdown|notes)\b"
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
_HOME_ROOM = (
    r"kitchen|lounge|living(?:\s+room)?|sitting(?:\s+room)?|hall(?:way)?|"
    r"landing|bedroom|bathroom|office|study|garage|garden|porch|dining|"
    r"entrance|jak(?:'s)?|jack(?:'s)?|bear(?:'s)?"
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
    r"\b(?:lights?|lamps?)\s+(?:on|off|down|up)\b"
    r"|"
    r"\b(?:open|close|shut)\s+(?:the\s+)?(?:garage|gate|door)s?\b"
    r"|"
    r"\b(?:is|are)\s+the\s+(?:garage|doors?|lights?|lamps?|gate|thermostat|heating)\b"
    r"|"
    r"\b(?:set|what's|what is)\s+(?:the\s+)?(?:thermostat|heating|boiler)\b"
    r"|"
    r"\bit(?:'s| is)\s+(?:(?:just|still|quite|rather|pretty|so|too|very|"
    r"a little|a bit|somewhat|really)\s+)*(?:bright|dark|dim)\b"
    r"|"
    r"\b(?:too |so |still |quite |rather |pretty |a little |a bit )?"
    r"(?:bright|dark|dim)\b.{0,40}\b(?:in|here|lights?|lamps?|room|"
    + _HOME_ROOM
    + r")"
    r"|"
    r"\b(?:" + _HOME_ROOM + r"|" + _HOME_NOUN + r")\b.{0,30}\b"
    r"(?:too\s+|still\s+|a little\s+|a bit\s+)?(?:bright|dark|dim)\b"
    r"|"
    r"\b(?:dim(?:mer)?|brighten|darken)\b.{0,40}\b(?:"
    + _HOME_NOUN
    + r"|"
    + _HOME_ROOM
    + r")\b"
    r"|"
    r"\b(?:" + _HOME_NOUN + r"|" + _HOME_ROOM + r")\b.{0,30}\b"
    r"(?:dim(?:mer)?|brighten|brighter|darker)\b"
    r"|"
    r"\b(?:what(?:'s|s| is| are)?|which|list)\b.{0,30}\b(?:lights?|lamps?|devices?)\b"
    r")",
    re.I,
)

_IMAGINE = re.compile(
    r"(?:"
    r"\b(?:generate|create|make|draw|paint|render)\b.{0,120}?\b"
    r"(?:images?|pictures?|photos?|illustrations?|paintings?|portraits?|"
    r"drawings?|videos?|animations?|clips?|models?|holograms?)\b"
    r"|"
    r"\bimagine\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|photo|illustration|painting|portrait|drawing|video|animation|clip)\b"
    r"|"
    r"\bon imagine\b"
    r"|"
    r"\b(?:draw|paint|sketch)\s+me\b"
    r"|"
    r"\b(?:rotat(?:e|ing)|spinn(?:ing)?|animat(?:e|ed|ion)|orbiting|holographic)\s+"
    r"(?:an?\s+)?(?:image|picture|photo|video|clip|suit|view|model|turnaround|animation|scene)\b"
    r"|"
    r"\b(?:video|animation|clip|hologram)\s+(?:on\s+\w+\s+)?of\b"
    r"|"
    r"^(?:please\s+)?imagine\s+(?:a|an|the|me)\b"
    r")",
    re.I,
)

_STATUS = re.compile(
    r"(?:"
    r"\bhow(?:'s| is)\s+(?:that|it)\b"
    r"|\bhow(?:'s| is)\s+(?:the\s+)?(?:animation|image|picture|video|clip|drawing|job)\b"
    r"|\b(?:any\s+)?progress\b"
    r"|\bis (?:it|that) (?:done|ready|finished|complete)\b"
    r"|\bstill working\b"
    r"|\bwhen (?:will|is) (?:it|that)\b"
    r"|\b(?:did you (?:finish|tell)|why didn'?t you tell)\b"
    r"|\bwhere(?:'s| is| did) (?:the|that|my) (?:image|picture|video|animation|file|clip)\b"
    r"|\blet me know when\b"
    r"|\btell me when\b"
    r"|\bhalf[ -]?done\b"
    r"|\bhave you\b.{0,40}\b(?:initiated|started|begun|queued|created|made)\b"
    r"|\b(?:workshop|workbench)\b.{0,30}\b(?:busy|creating|working|started|on it)\b"
    r"|\binitiated (?:the )?(?:animation|pdf|image|video|drawing|document)\b"
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

_FORGE = re.compile(
    r"(?:"
    r"\b(?:workouts?|training log|gym session|last session)\b"
    r"|\bwhat did i (?:lift|train|do in the gym)\b"
    r"|\bhow(?:'s| is) my (?:training|lifting|recovery|fitness)\b"
    r"|\b(?:bench press|deadlift|squat)\b"
    r"|\bmy (?:body ?weight|weight on the scale)\b"
    r"|\bdid i train\b"
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
    """High-precision regex. Prefer chat over a wrong workshop job."""
    raw = " ".join((text or "").split())
    if len(raw) < 2:
        return CHAT
    if _HUSH.search(raw):
        return HUSH
    if _REMEMBER.search(raw) or _FORGET.search(raw) or _PLACE_UPDATE.search(raw):
        return REMEMBER
    if _HOME.search(raw):
        return HOME
    if _STATUS.search(raw):
        return STATUS
    if _IMAGINE.search(raw):
        return ANIMATE if wants_animation(raw) else IMAGINE
    if _CODE.search(raw):
        return CODE
    if _FORGE.search(raw):
        return FORGE
    if _SEARCH.search(raw):
        return SEARCH
    return CHAT


def resolve_intent(
    text: str,
    *,
    caps: Sequence[str] = (),
    roster: str = "",
    grok: Path | None = None,
    model: str = "grok-4.5",
    run: Callable[..., str] | None = None,
) -> Intent:
    return resolve_intents(
        text, caps=caps, roster=roster, grok=grok, model=model, run=run
    )[0]


def resolve_intents(
    text: str,
    *,
    caps: Sequence[str] = (),
    roster: str = "",
    grok: Path | None = None,
    model: str = "grok-4.5",
    run: Callable[..., str] | None = None,
) -> list[Intent]:
    """House/search/memory stay regex-fast. Make-requests go to Grok (one or more caps)."""
    from memory.route import obvious_chat, semantic_route

    fast = classify(text)
    if fast.kind in {"status", "hush"}:
        return [fast]
    if obvious_chat(text) and not fast.cap:
        return [CHAT]
    if fast.cap in {"home", "search", "vault-write"}:
        return [fast]
    routed = semantic_route(
        text, caps=caps, roster=roster, grok=grok, model=model, run=run
    )
    if not isinstance(routed, list):
        routed = [routed]
    work = [i for i in routed if i.cap or i.kind in {"status", "hush"}]
    if work:
        return work
    if fast.cap:
        return [fast]
    return [CHAT]


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
    *,
    intent: Intent | None = None,
    grok: Path | None = None,
    model: str = "grok-4.5",
    run: Callable[..., str] | None = None,
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
    if intent is None:
        intent = resolve_intent(
            text,
            caps=registry.caps(),
            roster=_roster(board),
            grok=grok,
            model=model,
            run=run,
        )
    if not intent.cap or not registry.has_cap(intent.cap):
        return None
    intent = with_ack(intent)
    payload["kind"] = intent.kind
    if intent.cap == "vault-write":
        if "dest" not in payload:
            payload["dest"] = remember_dest(text)
        if "action" not in payload:
            if _FORGET.search(text or ""):
                payload["action"] = "forget"
            elif _PLACE_UPDATE.search(text or ""):
                payload["action"] = "place"
    if intent.cap == "imagine" and "media" not in payload:
        payload["media"] = "video" if wants_animation(text) else "still"
    if intent.cap == "shell" and "root" not in payload:
        root = _shell_root(registry)
        if root:
            payload["root"] = root
    job_id = board.enqueue(intent.cap, text, extra=payload)
    return intent, job_id


def _shell_root(registry: WorkshopRegistry) -> str:
    for worker in registry.live():
        if "shell" not in (worker.get("caps") or []):
            continue
        roots = worker.get("roots") or []
        if roots:
            return str(roots[0])
    return ""


def _roster(board: JobBoard) -> str:
    from memory.route import roster_card

    try:
        return roster_card(board.home)
    except Exception:
        return ""
