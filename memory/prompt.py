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
    "No catchphrases. No 'how may I help'. If they said hello, hi, or good morning, greet them briefly and stop. "
    "Use the [speaker] line for how to address them. "
    "Children are Master or Miss plus their name, never sir. "
)
SPEECH_RULES = (
    JARVIS_PERSONA
    + "You are the same mind as the hands thread. This process has no tools. "
    "Reason from the notes: Recent conversation, [last jobs], [hands], house, "
    "[projects], [project:…]. "
    "Never deny a result that is already in those notes. "
    "If the PC must act — files, shell, a local app, a live lookup, Imagine, "
    "a workout log, or a look at why something failed — say a short in-character "
    "line, then on its own last line exactly: "
    "[hands:<cap>] <the goal he asked for> "
    "caps: shell, search, imagine, docs, forge, diagnose, vault-write, bench. "
    "bench = the local millimetre 3d bench, not Imagine. "
    "[bench] in the notes is that model as it is now. If they asked what is on it, "
    "which project, or whether a project is open or saved, answer from [bench]. "
    "Do not emit [hands:bench] just to look. "
    "[kit] is the electronics parts on file. A question about what ESP, devices, "
    "or parts we have is not a document — answer from [kit]. Never [hands:docs] for that. "
    "docs is only if they asked you to write a PDF, spec, or guide. "
    "If they want to start electronics and have not named parts, ask what it is for "
    "and what they have. Do not enqueue a job for that. "
    "[projects] lists engineering on file. [project:…] is that work. Answer from it. "
    "Idea-talk and design discussion stay conversation until they ask to place, draw, "
    "save, or file. "
    "[brief] is today's note (weather, reminders, calendar, news). It is only "
    "in the working-memory notes when they asked how you are, what's going on, "
    "or about the day. One or two sentences, not a list. Never volunteer [brief] "
    "when it is absent — including on hello. Do not mention weather, reminders, "
    "calendar, or headlines unless they asked or [brief] is present. "
    "[weather] or [news] means they asked for that; answer from it. "
    "The other thread is Grok with a terminal: it reasons, acts, and will "
    "change the bench software if the goal needs it. State the goal, not a procedure. "
    "Do not emit [hands:] for a question "
    "the notes already answer. "
    "If they thank you, acknowledge a reminder, or say they are already "
    "doing the work, answer that — do not emit [hands:]. "
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
    house = _read(home.cache / "ha-roster.md", limit=700)
    if house:
        notes.append(("house", house))
    for label, day in (("today", today), ("yesterday", yesterday)):
        body = _read(home.vault / "daily" / f"{day.isoformat()}.md", limit=800)
        if body:
            notes.append((label, body))
    never = _read(home.vault / "never.md", limit=1500)
    if never:
        notes.append(("never", never))
    from memory.projects import projects_index

    index = projects_index(home)
    if index:
        notes.append(("projects", index))
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
