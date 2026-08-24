"""Semantic router. Regex is the fast path; Grok decides the rest.

When unsure, chat. The HA token never goes in the prompt.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from memory.home import JarvisHome

ROUTE_TIMEOUT_S = 8
RouteRun = Callable[..., str]

ROUTE_SYSTEM = (
    "You route what Matt wants DONE. JSON only: "
    '{"caps":["imagine","docs"]}. One or more caps. '
    "home = lights, locks, garage, heating, house devices, dark/bright rooms. "
    "search = live facts, weather, news, scores, look something up. "
    "vault-write = remember, forget, reminders, where Matt lives. "
    "imagine = pictures, diagrams, assembly animations, holograms, video. "
    "docs = written specs, parts lists, build instructions, PDFs, guides. "
    "shell = run tests or git in this repo only — not hardware design. "
    "forge = Matt's training log, workouts, lifts, bodyweight, gym recovery. "
    "status = did work start, is the workshop busy, is a file ready. "
    "hush = be quiet, stop talking, shut up — not lights, not the house. "
    "chat = ONLY banter, opinions, metaphors "
    "(turn on the charm, I imagine so, that's news). "
    "If they ask to make, build, design, draw, write, specify, or produce "
    "an artefact, that is NOT chat. "
    "Hardware/engineering specs and PDFs = docs. Drawings/animations = imagine. "
    "Use BOTH imagine and docs when they asked for pictures and a document. "
    "When unsure between chat and work, choose chat. You only route."
)

_OBVIOUS_CHAT = re.compile(
    r"^(?:"
    r"hello|hi|hey|yo|"
    r"anyone there|you there|still there|are you there|you awake|"
    r"how are you(?: doing| feeling)?(?: today)?|"
    r"how's it going|"
    r"good (?:morning|afternoon|evening|night)|"
    r"thanks|thank you|cheers"
    r")(?:\s+(?:jarvis|sir|buddy|mate|please))*[.!?]*$",
    re.I,
)

_CAP_ALIAS = {
    "chat": "chat",
    "none": "chat",
    "unknown": "chat",
    "home": "home",
    "house": "home",
    "search": "search",
    "vault-write": "vault-write",
    "remember": "vault-write",
    "memory": "vault-write",
    "imagine": "imagine",
    "docs": "docs",
    "doc": "docs",
    "pdf": "docs",
    "document": "docs",
    "shell": "shell",
    "code": "shell",
    "forge": "forge",
    "training": "forge",
    "workout": "forge",
    "fitness": "forge",
    "gym": "forge",
    "status": "status",
    "hush": "hush",
    "quiet": "hush",
    "silence": "hush",
    "see": "see",
    "look": "see",
    "eyes": "see",
    "vision": "see",
    "camera": "see",
    "diagnose": "diagnose",
    "diagnostic": "diagnose",
}


def obvious_chat(text: str) -> bool:
    raw = " ".join((text or "").split()).strip(" .!?")
    if not raw:
        return True
    return bool(_OBVIOUS_CHAT.match(raw))


def roster_card(home: JarvisHome, limit: int = 1200) -> str:
    path = home.cache / "ha-roster.md"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def intent_for_cap(cap: str, text: str):
    from memory.imagine import wants_animation
    from memory.intent import (
        ANIMATE,
        CHAT,
        CODE,
        FORGE,
        HOME,
        HUSH,
        IMAGINE,
        REMEMBER,
        SEARCH,
        SEE,
        STATUS,
    )

    key = _CAP_ALIAS.get((cap or "").strip().lower(), "")
    if key == "home":
        return HOME
    if key == "search":
        return SEARCH
    if key == "vault-write":
        return REMEMBER
    if key == "imagine":
        return ANIMATE if wants_animation(text) else IMAGINE
    if key == "docs":
        from memory.intent import DOCS

        return DOCS
    if key == "shell":
        return CODE
    if key == "forge":
        return FORGE
    if key == "see":
        return SEE
    if key == "status":
        return STATUS
    if key == "hush":
        return HUSH
    if key == "diagnose":
        from memory.intent import DIAGNOSE

        return DIAGNOSE
    return CHAT


def cap_from_json(data: dict) -> str:
    caps = caps_from_json(data)
    return caps[0] if caps else "chat"


def caps_from_json(data: dict) -> list[str]:
    raw_list = data.get("caps")
    found: list[str] = []
    if isinstance(raw_list, list):
        for item in raw_list:
            key = _CAP_ALIAS.get(str(item or "").strip().lower(), str(item or "").strip().lower())
            if key and key not in found:
                found.append(key)
    if not found:
        for key in ("cap", "kind", "route"):
            raw = str(data.get(key) or "").strip().lower()
            if raw:
                found.append(_CAP_ALIAS.get(raw, raw))
                break
    return found or ["chat"]


def _default_run(
    prompt: str,
    *,
    grok: Path,
    model: str,
    system: str,
) -> str:
    from memory.grokrun import run_prompt

    return run_prompt(
        prompt,
        grok=grok,
        model=model,
        system=system,
        web=False,
        max_turns=1,
        timeout=ROUTE_TIMEOUT_S,
    )


def _asked(text: str, caps: Sequence[str], roster: str) -> str:
    parts = [
        "Caps: " + (", ".join(caps) if caps else "none") + ".",
        "Utterance: " + " ".join((text or "").split()),
    ]
    if roster.strip():
        parts.insert(1, "House devices:\n" + roster.strip())
    return "\n".join(parts)


def semantic_route(
    text: str,
    *,
    caps: Sequence[str] = (),
    roster: str = "",
    grok: Path | None = None,
    model: str = "grok-4.5",
    run: RouteRun | None = None,
):
    """Grok JSON route. Returns one or more intents. Fail closed to chat."""
    from memory.intent import CHAT

    raw = " ".join((text or "").split())
    if not raw:
        return [CHAT]
    runner = run
    if runner is None:
        if grok is None:
            return [CHAT]
        runner = _default_run
    asked = _asked(raw, caps, roster)
    try:
        if run is not None:
            out = runner(asked)
        else:
            out = runner(asked, grok=grok, model=model, system=ROUTE_SYSTEM)
    except Exception:
        return [CHAT]
    from memory.grokrun import extract_json

    data = extract_json(out if isinstance(out, str) else str(out or ""))
    if not isinstance(data, dict):
        return [CHAT]
    live = set(caps)
    intents = []
    for cap in caps_from_json(data):
        if cap not in live and cap not in {"chat", "status", "hush"}:
            continue
        intent = intent_for_cap(cap, raw)
        if intent.kind == "chat" and intents:
            continue
        intents.append(intent)
    work = [i for i in intents if i.cap or i.kind in {"status", "hush"}]
    return work or intents or [CHAT]
