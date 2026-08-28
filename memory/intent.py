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
CODE = Intent("code", "shell", "I'll take that, sir.", 0.0)
FORGE = Intent("forge", "forge", "I'll check the log, sir.", 0.0)
SEE = Intent("see", "see", "I'll have a look, sir.", 40.0)
BENCH = Intent("bench", "bench", "I'll put that on the bench, sir.", 20.0)
DIAGNOSE = Intent(
    "diagnose",
    "diagnose",
    "Something's off. I'm looking into it, sir.",
    0.0,
)

_ACKS = {
    "search": (
        "I'll have a look at that now, sir.",
        "I'll look into that, sir.",
        "One moment, sir.",
        "Checking now, sir.",
        "On it, sir.",
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
        "I'll have a look at that now, sir.",
        "I'll take that, sir.",
        "On it, sir.",
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
    "see": (
        "I'll have a look, sir.",
        "Looking now, sir.",
        "One moment, sir.",
    ),
    "diagnose": (
        "Something's off. I'm looking into it, sir.",
        "That didn't sit right. Checking it, sir.",
        "I'm running a look at that now, sir.",
    ),
    "bench": (
        "I'll put that on the bench, sir.",
        "On the bench, sir.",
        "Modelling that now, sir.",
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
    r"\b(?:kill|cut)\s+(?:the\s+)?(?:glow|glare)\b"
    r"|"
    r"\bgloomy\b"
    r")",
    re.I,
)

_BENCH = re.compile(
    r"(?:"
    r"\b(?:bit|piece|length|plank|board|batten)\s+of\s+wood\b"
    r"|\b(?:timber|lumber)\b"
    r"|\b(?:on|in)\s+(?:the\s+)?bench\b"
    r"|\bport\s+8770\b"
    r"|\bmillimet(?:er|re)s?\s+bench\b"
    r"|\b(?:3d|three[- ]dimensional)\s+model\b.{0,80}\b(?:wood|timber|board|plank|shape|bench)\b"
    r"|\b(?:wood|timber|board|plank|shape|bench)\b.{0,80}\b(?:3d|three[- ]dimensional)\s+model\b"
    r"|\b\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?)?\s+by\s+\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?)?\s+by\s+\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?)?\b"
    r")",
    re.I,
)
_BENCH_MUTATE = re.compile(
    r"(?:"
    r"\b(?:delete|remove|drop|get rid of)\b.{0,40}\b(?:board|part|plate|model)s?\b"
    r"|\b(?:board|part|plate)\s+\d+\b.{0,40}\b(?:delete|remove|vertical|upright|stand|end)"
    r"|\bstand(?:ing)?\s+(?:it|that|the|this|up)\b"
    r"|\bon end\b|\bupright\b"
    r"|\b(?:make|stand|orient).{0,40}\bvertical\b"
    r"|\bvertical\b.{0,40}\b(?:board|plate|end|bench)"
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
    r"|\b(?:go\s+)?(?:implement|patch)\b"
    r"|\bfix\s+(?:the\s+)?(?:bug|tests?|code|repo)\b"
    r"|\bdirector(?:y|ies)\b"
    r"|\bfolders?\b"
    r"|\bcode\s*base\b"
    r"|\blines of code\b"
    r"|\b(?:processor|cpu|ram|hardware)\b"
    r"|\b(?:laptop|machine|host)\s+(?:spec|hardware|cpu|processor)\b"
    r"|\brunning on\b"
    r"|\blist(?:ing)?\s+(?:the\s+)?files\b"
    r"|\bwhat(?:'s| is) in (?:the )?(?:dir|folder|repo|code|checkout|directory)\b"
    r"|\bdisk space\b"
    r"|\bhostname\b"
    r")",
    re.I,
)

_DOCS = re.compile(
    r"(?:"
    r"\b(?:pdf|parts\s+list|build\s+instructions?)\b"
    r"|\bwrite\s+(?:me\s+|a\s+)?(?:guide|spec|document)\b"
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

_SEE = re.compile(
    r"(?:"
    r"\bhave a look\b"
    r"|\btake a look\b"
    r"|\blook at (?:this|that|me)\b"
    r"|\bwhat do you see\b"
    r"|\bwhat am i (?:holding|doing|showing|wearing)\b"
    r"|\bcan you see (?:this|that|what)\b"
    r"|\buse (?:your |the )?eyes\b"
    r"|\buse (?:the |your )?camera\b"
    r"|\blook at (?:the |my )?screen\b"
    r"|\bwhat(?:'s| is) on (?:the |my )?screen\b"
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
    r"|\b(?:coin|crypto)\s+price\b"
    r"|\bprice of\b"
    r"|\b(?:bitcoin|btc|ethereum|eth)\b"
    r"|\bexchange rate\b"
    r"|\bwhat(?:'s| is) the score\b"
    r")",
    re.I,
)

# Matt is speaking, not asking Jarvis to act. Topic words must not steal this.
_THANKS = re.compile(
    r"\b(?:thanks|thank you|cheers|got it|will do|understood)\b",
    re.I,
)
_USER_AGENT = re.compile(
    r"\b(?:I(?:'m| am|'ll| will|'ve| have been)|I\s+am|im)\b",
    re.I,
)
_ASKING = re.compile(
    r"(?:"
    r"\b(?:can|could|would|will)\s+you\b"
    r"|\bI (?:need|want) you\b"
    r"|\?"
    r"|(?:^|[\s,;:])(?:what|who|where|when|how|why|which)\b"
    r")",
    re.I,
)
_ASK_HIM_TO = re.compile(
    r"(?:"
    r"\b(?:run\s+(?:the\s+)?tests?|pytest|git\s+commit|pull\s+request)\b"
    r"|\b(?:go\s+)?(?:implement|patch)\b"
    r"|\bfix\s+(?:the\s+)?(?:bug|tests?|code|repo)\b"
    r"|\b(?:look(?:ing)?\s+up|look\s+it\s+up|search\s+for|google)\b"
    r"|\b(?:generate|create|make|draw|paint|render|imagine)\b"
    r"|\b(?:write|draft)\s+(?:me\s+|a\s+)?(?:guide|spec|document|pdf)\b"
    r")",
    re.I,
)


def is_reply_not_request(text: str) -> bool:
    """Thanks or first-person progress — conversation, not a hands job."""
    raw = " ".join((text or "").split())
    if not raw:
        return False
    if not (_THANKS.search(raw) or _USER_AGENT.search(raw)):
        return False
    if _ASKING.search(raw) or _ASK_HIM_TO.search(raw):
        return False
    return True


_HOME_QUERY = re.compile(
    r"\b(?:what(?:'s|s| is| are)?|which|how many|list|do we have)\b"
    r".{0,40}\b(?:lights?|lamps?|devices?|rooms?)\b",
    re.I,
)
_HOME_ACT = re.compile(
    r"\b(?:turn|switch|dim|unlock|lock|open|close|shut|brighten|darken|"
    r"kill|cut)\b",
    re.I,
)


def classify(text: str) -> Intent:
    """High-precision regex. Prefer chat over a wrong hands job."""
    raw = " ".join((text or "").split())
    if len(raw) < 2:
        return CHAT
    if _HUSH.search(raw):
        return HUSH
    if _BENCH.search(raw) or _BENCH_MUTATE.search(raw):
        return BENCH
    if _REMEMBER.search(raw) or _FORGET.search(raw) or _PLACE_UPDATE.search(raw):
        return REMEMBER
    if _HOME_QUERY.search(raw) and not _HOME_ACT.search(raw):
        return CHAT
    if _HOME.search(raw):
        return HOME
    if _STATUS.search(raw):
        return STATUS
    if is_reply_not_request(raw):
        return CHAT
    if _IMAGINE.search(raw):
        return ANIMATE if wants_animation(raw) else IMAGINE
    if _SEE.search(raw):
        return SEE
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
    home=None,
) -> Intent:
    return resolve_intents(
        text,
        caps=caps,
        roster=roster,
        grok=grok,
        model=model,
        run=run,
        home=home,
    )[0]


def resolve_intents(
    text: str,
    *,
    caps: Sequence[str] = (),
    roster: str = "",
    grok: Path | None = None,
    model: str = "grok-4.5",
    run: Callable[..., str] | None = None,
    home=None,
) -> list[Intent]:
    """Regex / local only. Fail closed to chat. Unsure is conversation."""
    from memory.route import obvious_chat

    del grok, model, run
    raw = " ".join((text or "").split())
    fast = classify(raw)
    if fast.kind in {"status", "hush"}:
        return [fast]
    if obvious_chat(raw) and not fast.cap:
        return [CHAT]
    if fast.cap == "vault-write":
        return [fast]
    if fast.cap == "home":
        return [fast]
    if fast.cap == "bench":
        return [fast]
    if fast.kind == "diagnose":
        return [fast]
    if is_reply_not_request(raw):
        return [CHAT]
    found: list[Intent] = []
    if _BENCH.search(raw):
        found.append(BENCH)
    if _IMAGINE.search(raw) and not _BENCH.search(raw):
        found.append(ANIMATE if wants_animation(raw) else IMAGINE)
    if _SEE.search(raw):
        found.append(SEE)
    if _DOCS.search(raw):
        found.append(DOCS)
    if _CODE.search(raw):
        found.append(CODE)
    if _FORGE.search(raw):
        found.append(FORGE)
    if _SEARCH.search(raw):
        from memory.working import looks_like_weather, weather_fresh

        if (
            looks_like_weather(raw)
            and home is not None
            and weather_fresh(home)
            and not re.search(
                r"\b(?:look(?:ing)?\s+up|search\s+for|google|headlines|the\s+news)\b",
                raw,
                re.I,
            )
        ):
            pass
        else:
            found.append(SEARCH)
    live = set(caps) if caps else None
    if live is not None:
        found = [i for i in found if not i.cap or i.cap in live]
    if found:
        return found
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
            home=board.home,
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
        root = _shell_root(registry, text)
        if root:
            payload["root"] = root
    job_id = board.enqueue(intent.cap, text, extra=payload)
    return intent, job_id


def _shell_root(registry: WorkshopRegistry, text: str = "") -> str:
    from memory.apps import match_app

    app = match_app(text)
    want = ""
    if app and app.get("root"):
        want = str(Path(str(app["root"])).expanduser())
    for worker in registry.live():
        if "shell" not in (worker.get("caps") or []):
            continue
        roots = [str(r) for r in (worker.get("roots") or []) if r]
        if want:
            for root in roots:
                if root.rstrip("/") == want.rstrip("/") or want in root or root in want:
                    return root
            return want
        if roots:
            return roots[0]
    return want


def _roster(board: JobBoard) -> str:
    from memory.route import roster_card

    try:
        return roster_card(board.home)
    except Exception:
        return ""
