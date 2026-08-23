"""Jarvis filing cabinet: vault, jobs, workshops, session logs.

Talk stays tool-free. It loads a small boot bundle, appends logs, and
enqueues workshop jobs through a local intent gate.
"""
from memory.distill import distill_session
from memory.home import JarvisHome
from memory.intent import Intent, classify, maybe_enqueue
from memory.jobs import JobBoard
from memory.prompt import BOOT_BUDGET, SPEECH_RULES, build_system_prompt, load_boot_notes
from memory.session import SessionLog
from memory.workshops import WorkshopRegistry

__all__ = [
    "BOOT_BUDGET",
    "Intent",
    "JarvisHome",
    "JobBoard",
    "SPEECH_RULES",
    "SessionLog",
    "WorkshopRegistry",
    "build_system_prompt",
    "classify",
    "distill_session",
    "load_boot_notes",
    "maybe_enqueue",
]
