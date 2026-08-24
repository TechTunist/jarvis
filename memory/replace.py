"""Replace in-flight hands work only after Matt confirms.

Not cap-specific. If the worker that would take the new job is already busy,
ask using his own words for both jobs, then cancel or keep going.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import IN_FLIGHT, JobBoard
from memory.workshops import WorkshopRegistry

PENDING_S = 90
PENDING_NAME = "pending-replace.json"

_TRAIL = re.compile(r"^(?:please\s+)?(?:jarvis[,:]?\s+)*", re.I)
_TAIL = re.compile(r"[\s,]+(?:jarvis|sir)+\s*$", re.I)
_PUNCT = re.compile(r"[.!?]+$")


def pending_path(home: JarvisHome) -> Path:
    return home.cache / PENDING_NAME


def job_label(prompt: str, *, words: int = 10) -> str:
    """Short name from what he said — no per-job vocabulary."""
    t = " ".join((prompt or "").split())
    t = _PUNCT.sub("", t)
    t = _TRAIL.sub("", t)
    t = _TAIL.sub("", t)
    t = " ".join(t.split())
    parts = t.split()
    if len(parts) > words:
        t = " ".join(parts[:words])
    return t or "that"


def confirm_line(current: str, incoming: str) -> str:
    cur = (current or "that").strip() or "that"
    nxt = (incoming or "that").strip() or "that"
    return (
        f"Are you sure you want me to cancel {cur} "
        f"and {nxt} instead, sir?"
    )


def keep_line(current: str) -> str:
    cur = (current or "that").strip() or "that"
    return f"Very well, I'll keep on with {cur}, sir."


def contended(
    board: JobBoard,
    registry: WorkshopRegistry,
    cap: str | None,
) -> list[dict]:
    """In-flight jobs on the worker that would run this cap. Empty = no conflict."""
    if not cap:
        return []
    holders = [
        w for w in registry.live() if cap in (w.get("caps") or [])
    ]
    if not holders:
        return []
    busy_caps: set[str] = set()
    for w in holders:
        for item in w.get("caps") or []:
            if item:
                busy_caps.add(str(item))
    found: list[dict] = []
    seen: set[str] = set()
    for snap in board.active():
        job_id = str(snap.get("id") or "")
        if not job_id or job_id in seen:
            continue
        if str(snap.get("cap") or "") not in busy_caps:
            continue
        if str(snap.get("event") or "") not in IN_FLIGHT:
            continue
        seen.add(job_id)
        found.append(snap)
    return found


def pending(home: JarvisHome) -> dict | None:
    path = pending_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = float(doc.get("ts") or 0)
    if time.time() - ts > PENDING_S:
        clear(home)
        return None
    return doc if isinstance(doc, dict) else None


def ask(
    home: JarvisHome,
    *,
    current: list[dict],
    next_prompt: str,
    next_cap: str,
) -> str:
    labels = [job_label(str(s.get("prompt") or "")) for s in current]
    current_label = " and ".join(l for l in labels if l) or "that"
    next_label = job_label(next_prompt)
    doc = {
        "ts": time.time(),
        "cancel_ids": [str(s.get("id") or "") for s in current if s.get("id")],
        "current_label": current_label,
        "next_label": next_label,
        "next_prompt": next_prompt,
        "next_cap": next_cap,
    }
    home.cache.mkdir(parents=True, exist_ok=True)
    pending_path(home).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return confirm_line(current_label, next_label)


def clear(home: JarvisHome) -> None:
    try:
        pending_path(home).unlink()
    except OSError:
        pass
