"""Job board: jobs/<id>.jsonl. Receptionist will enqueue; workers append."""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from memory.home import JarvisHome
from memory.session import iso

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
TERMINAL = frozenset({"done", "error", "cancelled"})
CLAIM_STALE_S = 90
_RESERVED = frozenset({"event", "id"})


def _job_id(when: datetime, cap: str) -> str:
    cap = _SAFE.sub("-", cap.lower())[:24].strip("-") or "job"
    return f"{when.strftime('%Y%m%dT%H%M%SZ')}-{cap}-{secrets.token_hex(2)}"


class JobBoard:
    def __init__(self, home: JarvisHome):
        self.home = home
        self.root = home.jobs

    def path_for(self, job_id: str) -> Path:
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            raise ValueError(f"bad job id: {job_id!r}")
        return self.root / f"{job_id}.jsonl"

    def enqueue(
        self,
        cap: str,
        prompt: str,
        *,
        path: str | None = None,
        extra: dict | None = None,
    ) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        when = datetime.now(timezone.utc)
        job_id = _job_id(when, cap)
        event = {
            "ts": iso(when),
            "event": "enqueued",
            "id": job_id,
            "cap": cap,
            "prompt": prompt,
        }
        if path:
            event["path"] = path
        if extra:
            for key, val in extra.items():
                if key not in _RESERVED:
                    event[key] = val
        self.append(job_id, event)
        return job_id

    def append(self, job_id: str, event: dict) -> None:
        dest = self.path_for(job_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        row = dict(event)
        row.setdefault("ts", iso(datetime.now(timezone.utc)))
        row.setdefault("id", job_id)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def events(self, job_id: str) -> list[dict]:
        dest = self.path_for(job_id)
        if not dest.is_file():
            return []
        out: list[dict] = []
        for line in dest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def latest_status(self, job_id: str) -> str:
        evs = self.events(job_id)
        if not evs:
            return "missing"
        return str(evs[-1].get("event") or "unknown")

    def job_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.stem for p in self.root.glob("*.jsonl"))

    def snapshot(self, job_id: str) -> dict:
        merged: dict = {}
        for ev in self.events(job_id):
            merged.update(ev)
        if merged:
            merged.setdefault("id", job_id)
        return merged

    def _age_s(self, ts: str, now: datetime) -> float:
        try:
            then = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            return max(0.0, (now - then).total_seconds())
        except (TypeError, ValueError):
            return 0.0

    def runnable(
        self,
        caps: list[str] | None = None,
        *,
        stale_claim_s: float = CLAIM_STALE_S,
        now: datetime | None = None,
    ) -> list[dict]:
        """Jobs a worker may claim: enqueued, or claimed long enough to retry."""
        now = now or datetime.now(timezone.utc)
        want = set(caps) if caps is not None else None
        found: list[dict] = []
        for job_id in self.job_ids():
            snap = self.snapshot(job_id)
            if not snap:
                continue
            if want is not None and snap.get("cap") not in want:
                continue
            ev = snap.get("event")
            if ev == "enqueued":
                found.append(snap)
            elif ev == "claimed" and self._age_s(str(snap.get("ts") or ""), now) >= stale_claim_s:
                found.append(snap)
        return found

    def status_line(self, asked: str = "", pending_ids: set[str] | None = None) -> str:
        """Honest spoken status from the board. The desk Grok must not invent this."""
        pending_ids = set(pending_ids or ())
        asked_l = (asked or "").lower()
        active: list[dict] = []
        seen: set[str] = set()
        for jid in list(pending_ids):
            snap = self.snapshot(jid)
            if snap.get("event") in ("enqueued", "claimed"):
                active.append(snap)
                seen.add(jid)
        now = datetime.now(timezone.utc)
        for jid in reversed(self.job_ids()):
            if jid in seen:
                continue
            snap = self.snapshot(jid)
            ev = snap.get("event")
            if ev not in ("enqueued", "claimed"):
                continue
            if self._age_s(str(snap.get("ts") or ""), now) > 1800:
                continue
            active.append(snap)
            if len(active) >= 4:
                break
        if active:
            caps = []
            for snap in active:
                cap = str(snap.get("cap") or "job")
                if cap not in caps:
                    caps.append(cap)
            return f"Still on {', '.join(caps)}, sir."
        if re.search(
            r"\b(?:animation|pdf|image|picture|video|drawing|document)\b",
            asked_l,
        ):
            return (
                "Nothing queued for that, sir. "
                "Talking at the desk does not start Imagine or a PDF."
            )
        return "Nothing on the workbench, sir."

    def active(self, caps: list[str] | None = None) -> list[dict]:
        want = set(caps) if caps is not None else None
        found: list[dict] = []
        for job_id in self.job_ids():
            snap = self.snapshot(job_id)
            if not snap:
                continue
            if want is not None and snap.get("cap") not in want:
                continue
            if snap.get("event") not in TERMINAL and snap.get("event") not in (
                None,
                "missing",
            ):
                found.append(snap)
        return found

    def claim(self, job_id: str, worker_id: str) -> bool:
        st = self.latest_status(job_id)
        if st not in ("enqueued", "claimed"):
            return False
        self.append(job_id, {"event": "claimed", "worker": worker_id})
        return True

    def finish(
        self,
        job_id: str,
        *,
        speak: str = "",
        result: str = "",
        extra: dict | None = None,
    ) -> None:
        event = {"event": "done", "speak": speak, "result": result}
        if extra:
            event.update(extra)
        self.append(job_id, event)

    def fail(self, job_id: str, error: str) -> None:
        self.append(job_id, {"event": "error", "error": str(error)[:800], "speak": ""})

    def wait(
        self,
        job_id: str,
        timeout: float = 60,
        interval: float = 0.2,
        abort=None,
    ) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if abort is not None and abort():
                return None
            st = self.latest_status(job_id)
            if st in TERMINAL:
                return self.snapshot(job_id)
            time.sleep(interval)
        return None
