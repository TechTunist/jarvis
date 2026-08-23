"""Session close: a tiny daily stub. Facts are a workshop distill job.

Full text stays in the session jsonl. Boot must not be stuffed with transcripts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from memory.jobs import JobBoard
from memory.session import SessionLog


def daily_path(session: SessionLog) -> Path:
    day = session.started.date().isoformat()
    return session.home.vault / "daily" / f"{day}.md"


def distill_session(
    session: SessionLog,
    board: JobBoard | None = None,
) -> Path | None:
    """Append a header-only stub and enqueue a distill job. No transcript dump."""
    if not session.turns:
        return None
    dest = daily_path(session)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ended = datetime.now(timezone.utc)
    rel = session.path.name
    header = (
        f"## {session.started.strftime('%H:%M')}–{ended.strftime('%H:%M')} "
        f"UTC · {len(session.turns)} turns · `{session.session_id}`\n"
        f"Transcript: `{rel}` (not loaded into the desk prompt).\n\n"
    )
    if not dest.exists():
        dest.write_text(
            f"# {session.started.date().isoformat()}\n\n{header}",
            encoding="utf-8",
        )
    else:
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(header)
    if board is not None:
        board.enqueue(
            "distill",
            f"File durable facts from session {session.session_id}",
            path=str(session.path),
            extra={
                "session": session.session_id,
                "turns": len(session.turns),
            },
        )
    return dest
