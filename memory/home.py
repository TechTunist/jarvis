"""JARVIS_HOME layout. Default ~/.jarvis — not this git repo.

The vault can be its own private git remote. This tree is the one writer
Talk should treat as the filing cabinet.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import which

TEMPLATES = Path(__file__).resolve().parent / "templates"
LEASE_STALE_S = 8 * 3600


@dataclass(frozen=True)
class JarvisHome:
    root: Path

    @classmethod
    def discover(cls, override: str | Path | None = None) -> JarvisHome:
        if override:
            return cls(Path(override).expanduser().resolve())
        env = os.environ.get("JARVIS_HOME")
        if env:
            return cls(Path(env).expanduser().resolve())
        return cls((Path.home() / ".jarvis").resolve())

    @property
    def vault(self) -> Path:
        return self.root / "vault"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    @property
    def workshops(self) -> Path:
        return self.root / "workshops"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def sessions(self) -> Path:
        return self.logs / "sessions"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def imagine(self) -> Path:
        return self.root / "imagine"

    @property
    def secrets(self) -> Path:
        return self.root / "secrets"

    @property
    def lease_path(self) -> Path:
        return self.root / "writer.lease"

    def ensure(self) -> None:
        for p in (
            self.root,
            self.vault,
            self.vault / "people",
            self.vault / "daily",
            self.vault / "projects",
            self.jobs,
            self.workshops,
            self.sessions,
            self.cache,
            self.imagine,
            self.secrets,
        ):
            p.mkdir(parents=True, exist_ok=True)
        mapping = {
            "BOOT.md": self.vault / "BOOT.md",
            "never.md": self.vault / "never.md",
            "README.md": self.vault / "README.md",
            ".gitignore": self.vault / ".gitignore",
            "people/_household.md": self.vault / "people" / "_household.md",
            "reminders.md": self.vault / "reminders.md",
            "calendar.md": self.vault / "calendar.md",
            "secrets-README.md": self.secrets / "README.md",
        }
        for rel, dest in mapping.items():
            src = TEMPLATES / rel
            if src.is_file() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        proj_src = TEMPLATES / "projects"
        proj_dest = self.vault / "projects"
        if proj_src.is_dir():
            for src in proj_src.iterdir():
                if not src.is_file():
                    continue
                dest = proj_dest / src.name
                if not dest.exists():
                    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        _maybe_git_init(self.vault)

    def take_lease(self, pid: int) -> str | None:
        """Claim the one-writer lease. Returns a warning if another host had it."""
        now = time.time()
        warning = None
        if self.lease_path.is_file():
            try:
                old = json.loads(self.lease_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                old = {}
            age = now - float(old.get("ts") or 0)
            other = old.get("host") or "?"
            other_pid = int(old.get("pid") or 0)
            same = other == socket.gethostname() and other_pid == pid
            if not same and age < LEASE_STALE_S:
                warning = (
                    f"vault writer lease was held by {other} pid={other_pid} "
                    f"({int(age)}s ago). One Talk only — stop the other desk."
                )
        payload = {
            "host": socket.gethostname(),
            "pid": pid,
            "ts": now,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return warning

    def drop_lease(self, pid: int) -> None:
        try:
            if not self.lease_path.is_file():
                return
            old = json.loads(self.lease_path.read_text(encoding="utf-8"))
            if int(old.get("pid") or 0) == pid and old.get("host") == socket.gethostname():
                self.lease_path.unlink()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return


def _maybe_git_init(vault: Path) -> None:
    if (vault / ".git").exists():
        return
    git = which("git")
    if not git:
        return
    subprocess.run(
        [git, "init", "-q"],
        cwd=str(vault),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
