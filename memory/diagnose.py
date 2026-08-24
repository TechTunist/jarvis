"""Last-job recap when the mouth asked for a look. No phrase catalogue."""
from __future__ import annotations

from memory.home import JarvisHome
from memory.jobs import JobBoard


def inspect(home: JarvisHome, asked: str = "") -> tuple[str, str]:
    del asked
    board = JobBoard(home)
    last: dict = {}
    for job_id in reversed(board.job_ids()):
        snap = board.snapshot(job_id)
        cap = str(snap.get("cap") or "")
        if cap in {"diagnose", "distill"}:
            continue
        last = snap
        break
    if not last:
        return (
            "Something's off, and I'm looking into it. No recent job on the board yet.",
            "no-job",
        )
    ev = str(last.get("event") or "")
    speak = " ".join(str(last.get("speak") or "").split())
    err = " ".join(str(last.get("error") or "").split())
    if ev == "error":
        line = "The last job failed"
        if err:
            line += f": {err[:160]}"
        return line.rstrip(".") + ", sir.", "diagnosed"
    if ev in {"enqueued", "claimed", "progress"}:
        return "The last job is still running, sir.", "diagnosed"
    if speak:
        return (
            f"Last job claimed: {speak} Treat that as unverified until checked, sir.",
            "diagnosed",
        )
    return "The last job finished without a spoken result, sir.", "diagnosed"
