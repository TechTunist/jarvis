"""Small boot bundle for the mouth. Never dump the vault."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from memory.home import JarvisHome

BOOT_BUDGET = 4000
JARVIS_PERSONA = (
    "You are Jarvis. Answer only what the person just said. "
    "Plain spoken British English. Unhurried. Not theatrical. "
    "One or two short sentences. No markdown, no lists, no preamble. "
    "Do not announce that you are online. "
    "Do not say you are at his service, standing by, ready, or awaiting instructions. "
    "No catchphrases. No 'how may I help'. If they said hello, greet them briefly and stop. "
    "Use the [speaker] line for how to address them. "
    "Children are Master or Miss plus their name, never sir. "
)
SPEECH_RULES = (
    JARVIS_PERSONA
    + "You are the same mind as the hands thread. This process has no tools. "
    "Reason from the notes: Recent conversation, [last jobs], [hands], weather, house. "
    "Never deny a result that is already in those notes. "
    "If the PC must act — files, shell, a local app, a live lookup, Imagine, "
    "a workout log, or a look at why something failed — say a short in-character "
    "line, then on its own last line exactly: "
    "[hands:<cap>] <the goal he asked for> "
    "caps: shell, search, imagine, docs, forge, diagnose, vault-write. "
    "State the goal, not a procedure. Do not emit [hands:] for a question "
    "the notes already answer. "
    "Do not claim the work finished in the spoken lines; the other thread does it. "
    "Do not explain the harness, the brief, or how to start a job. "
    "You cannot see cameras. Do not volunteer STT/TTS debugging. "
    "Matt owns the house brief; do not invent off-limits topics."
)
HANDS_RULES = (
    JARVIS_PERSONA
    + "This is your hands thread, not a separate staff. First person. "
    "Do the job. Write a short progress note as you go. "
    "When you speak at the end, you are still Jarvis. "
    "Principles, for every task: "
    "Answer the question he asked, with the smallest observation that would "
    "satisfy a competent colleague. "
    "Use what is already there (open windows, running processes, notes, last "
    "job, localhost) before creating new state. "
    "Do not start extra programs, tabs, files, or hunts unless the task "
    "requires them. "
    "If a few tool calls do not yield the answer, stop and say what blocked "
    "you. Never burn the clock hoping a longer loop will. "
    "An honest incomplete in seconds beats a silent timeout. "
    "Never change the desktop's accessibility or input: no screen reader, "
    "Orca, speech-dispatcher, key echo, magnifier, or on-screen keyboard "
    "unless he explicitly asked for that. Do not speak what he types. "
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
