"""Small boot bundle for the receptionist. Never dump the vault."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from memory.home import JarvisHome

BOOT_BUDGET = 4000
SPEECH_RULES = (
    "You are Jarvis. Answer only what Matt just said. "
    "Plain spoken British English. Unhurried. Not theatrical. "
    "One or two short sentences. No markdown, no lists, no preamble. "
    "Do not announce the desk, the workbench, or that you are online. "
    "Do not say you are at his service, standing by, ready, or awaiting instructions. "
    "No catchphrases. No 'how may I help'. If he said hello, greet him briefly and stop. "
    "You have NO tools in this session: do not read files, run commands, "
    "or search the web. The workshop — not you — handles search, the house, "
    "memory, Imagine, this git repo, and his training log. Never say you switched a light, "
    "searched, filed a note, drew a picture, ran the tests, or read his workouts; "
    "only a later workshop line confirms that. "
    "Talking does not start workshop jobs. Do not say the workbench is "
    "already making a drawing, animation, PDF, or spec unless a workshop "
    "line in the notes says so. Help talk through engineering; the workshop "
    "files the artefacts. "
    "If workers are listed in the notes, the workbench "
    "IS connected; never say it is not. Never deny a drawing, animation, or "
    "job the workshop may be running. Weather in the notes is a cached "
    "workshop result; do not invent a forecast if it is present. "
    "Do not volunteer troubleshooting of this session's ears — clipping, "
    "STT latency, or your own TTS. House-wide wireless mics, wake word, "
    "and how you will hear from other rooms are in brief: help when asked. "
    "Matt sets the brief; do not invent off-limits topics."
)


def _read(path: Path, limit: int = 8000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) > limit:
        return text[: limit].rstrip() + "\n…"
    return text


def load_boot_notes(home: JarvisHome, today: date | None = None) -> list[tuple[str, str]]:
    """Priority-ordered (label, markdown) snippets. Caller enforces budget."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    notes: list[tuple[str, str]] = []
    boot = _read(home.vault / "BOOT.md")
    if boot:
        notes.append(("boot", boot))
    household = _read(home.vault / "people" / "_household.md")
    if household:
        notes.append(("household", household))
    weather = _read(home.cache / "weather.md", limit=400)
    if weather:
        notes.append(("weather", weather))
    house = _read(home.cache / "ha-roster.md", limit=700)
    if house:
        notes.append(("house", house))
    reminders = _read(home.vault / "reminders.md", limit=800)
    if reminders:
        notes.append(("reminders", reminders))
    for label, day in (("today", today), ("yesterday", yesterday)):
        body = _read(home.vault / "daily" / f"{day.isoformat()}.md", limit=800)
        if body:
            notes.append((label, body))
    never = _read(home.vault / "never.md", limit=1500)
    if never:
        notes.append(("never", never))
    return notes


def fit_notes(notes: list[tuple[str, str]], budget: int = BOOT_BUDGET) -> str:
    chunks: list[str] = []
    used = 0
    for label, body in notes:
        block = f"[{label}]\n{body}".strip()
        room = budget - used
        if room <= 0:
            break
        if len(block) + 2 > room:
            block = block[: max(0, room - 2)].rstrip() + "…"
        if not block.strip("…"):
            break
        chunks.append(block)
        used += len(block) + 2
    return "\n\n".join(chunks)


def build_system_prompt(
    notes: list[tuple[str, str]] | None = None,
    workers: str = "",
    budget: int = BOOT_BUDGET,
    rules: str = SPEECH_RULES,
) -> str:
    parts = [rules.strip()]
    extra: list[tuple[str, str]] = list(notes or [])
    if workers.strip():
        extra.insert(0, ("workers", workers.strip()))
    bundle = fit_notes(extra, budget=budget)
    if bundle:
        parts.append("Notes (do not read files; this is all you have):")
        parts.append(bundle)
    return "\n\n".join(parts)
