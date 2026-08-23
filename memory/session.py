"""Append-only session log. The live Grok chat is not memory; this file is."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from memory.home import JarvisHome


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sid(when: datetime) -> str:
    return f"{when.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SessionLog:
    home: JarvisHome
    session_id: str
    started: datetime
    path: Path
    turns: list[dict] = field(default_factory=list)

    @classmethod
    def start(cls, home: JarvisHome, when: datetime | None = None) -> SessionLog:
        when = when or _now()
        home.sessions.mkdir(parents=True, exist_ok=True)
        sid = _sid(when)
        path = home.sessions / f"{when.date().isoformat()}.jsonl"
        log = cls(home=home, session_id=sid, started=when, path=path)
        log._write(
            {
                "ts": iso(when),
                "session": sid,
                "event": "start",
            }
        )
        return log

    def record(self, user: str, reply: str, **metrics) -> dict:
        when = _now()
        row = {
            "ts": iso(when),
            "session": self.session_id,
            "event": "turn",
            "user": user,
            "reply": reply,
        }
        for key in (
            "stt_ms",
            "ttfb_ms",
            "first_sentence_ms",
            "first_audio_ms",
            "total_ms",
            "model",
            "brain",
        ):
            if key in metrics and metrics[key] is not None:
                row[key] = metrics[key]
        self.turns.append(row)
        self._write(row)
        return row

    def close(self) -> None:
        self._write(
            {
                "ts": iso(_now()),
                "session": self.session_id,
                "event": "end",
                "turns": len(self.turns),
            }
        )

    def _write(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
