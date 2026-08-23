"""Workers advertise capabilities with a heartbeat file."""
from __future__ import annotations

import json
import time
from pathlib import Path

from memory.home import JarvisHome

STALE_S = 45


class WorkshopRegistry:
    def __init__(self, home: JarvisHome, stale_s: float = STALE_S):
        self.home = home
        self.root = home.workshops
        self.stale_s = stale_s

    def _path(self, worker_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in worker_id)
        return self.root / f"{safe}.json"

    def advertise(self, worker_id: str, caps: list[str], **extra) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        doc = {
            "id": worker_id,
            "seen": time.time(),
            "caps": list(caps),
            **extra,
        }
        dest = self._path(worker_id)
        dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return dest

    def online(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        now = time.time()
        found: list[dict] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            seen = float(doc.get("seen") or 0)
            doc["online"] = (now - seen) <= self.stale_s
            doc["age_s"] = int(max(0, now - seen))
            found.append(doc)
        return found

    def live(self) -> list[dict]:
        return [w for w in self.online() if w.get("online")]

    def has_cap(self, cap: str) -> bool:
        for worker in self.live():
            if cap in (worker.get("caps") or []):
                return True
        return False

    def prompt_line(self) -> str:
        live = self.live()
        if not live:
            return "Workers: none. Workbench is not connected."
        parts = []
        for w in live:
            caps = ", ".join(w.get("caps") or []) or "none"
            parts.append(f"{w.get('id')} ({caps})")
        return "Workers online: " + "; ".join(parts) + "."
