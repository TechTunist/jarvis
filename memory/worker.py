"""Host workshop: heartbeat + pull jobs. Search, vault-write, distill.

Talk stays tool-free. This process is the hands: grok -p with web search for
lookup, Python-only writes into allowed vault files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

from memory.grokrun import extract_json, find_grok, run_prompt
from memory.home import JarvisHome
from memory.intent import file_line, remember_dest
from memory.jobs import JobBoard
from memory.workshops import WorkshopRegistry

HOST_CAPS = ("search", "vault-write", "distill", "home")
SEARCH_SYSTEM = (
    "You are Jarvis's workshop, not the front desk. Search the web if needed. "
    "Reply with at most two short spoken sentences for Matt. British butler. "
    "First sentence at most six words. No markdown, no lists, no URLs unless "
    "essential. No preamble."
)
REMEMBER_SYSTEM = (
    'Return JSON only: {"bullet": "one short durable fact"}. '
    "No markdown, no leading dash, no 'remember'."
)
DISTILL_SYSTEM = (
    "Extract durable household facts from this transcript. "
    "Ignore chit-chat, jokes, hellos, and one-off questions. "
    'Return JSON only: {"facts": [{"dest": "household"|"never"|"daily"|"reminders", '
    '"bullet": "one short fact"}]}. '
    "household = lasting preferences and people. never = hard constraints. "
    "daily = only if it matters today and not later. "
    'reminders = timed items as "HH:MM daily - fact" or "YYYY-MM-DD HH:MM - fact". '
    'If nothing durable, {"facts": []}.'
)

CompleteFn = Callable[..., str]


def log(msg: str) -> None:
    print(msg, flush=True)


def dest_path(home: JarvisHome, dest: str, today: date | None = None) -> Path | None:
    today = today or date.today()
    if dest == "household":
        return home.vault / "people" / "_household.md"
    if dest == "never":
        return home.vault / "never.md"
    if dest == "daily":
        return home.vault / "daily" / f"{today.isoformat()}.md"
    if dest == "inbox":
        return home.vault / "inbox.md"
    if dest == "reminders":
        return home.vault / "reminders.md"
    return None


def append_bullet(path: Path, bullet: str) -> bool:
    bullet = " ".join((bullet or "").split()).lstrip("- ").strip()
    if not bullet:
        return False
    line = f"- {bullet}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if bullet in text:
            return False
        with path.open("a", encoding="utf-8") as fh:
            if text and not text.endswith("\n"):
                fh.write("\n")
            fh.write(line)
    else:
        path.write_text(line, encoding="utf-8")
    return True


def _session_turns(path: Path, limit: int = 40) -> str:
    if not path.is_file():
        return ""
    rows: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") != "turn":
            continue
        user = " ".join(str(ev.get("user") or "").split())[:240]
        reply = " ".join(str(ev.get("reply") or "").split())[:240]
        if user:
            rows.append(f"You: {user}")
        if reply:
            rows.append(f"Jarvis: {reply}")
    return "\n".join(rows[-(limit * 2) :])


def _parent_gone(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return True
    return False


class HostWorker:
    def __init__(
        self,
        home: JarvisHome,
        *,
        grok: Path | None = None,
        model: str = "grok-4.5",
        worker_id: str | None = None,
        complete: CompleteFn | None = None,
        parent_pid: int = 0,
        heartbeat_s: float = 10.0,
        caps: tuple[str, ...] = HOST_CAPS,
    ):
        self.home = home
        self.grok = grok or find_grok()
        self.model = model
        self.worker_id = worker_id or f"host-{socket.gethostname()}"
        self.complete = complete
        self.parent_pid = parent_pid
        self.heartbeat_s = heartbeat_s
        self.caps = caps
        self.board = JobBoard(home)
        self.registry = WorkshopRegistry(home)
        self._last_beat = 0.0

    def advertise(self) -> None:
        self.registry.advertise(
            self.worker_id,
            list(self.caps),
            host=socket.gethostname(),
            pid=os.getpid(),
            model=self.model,
        )
        self._last_beat = time.monotonic()

    def beat(self) -> None:
        if time.monotonic() - self._last_beat >= self.heartbeat_s:
            self.advertise()

    def _ask(
        self,
        prompt: str,
        *,
        system: str,
        web: bool,
        max_turns: int = 6,
        timeout: float = 90,
    ) -> str:
        if self.complete is not None:
            return self.complete(
                prompt, system=system, web=web, max_turns=max_turns
            )
        return run_prompt(
            prompt,
            grok=self.grok,
            model=self.model,
            system=system,
            web=web,
            max_turns=max_turns,
            timeout=timeout,
        )

    def handle(self, snap: dict) -> tuple[str, str]:
        cap = str(snap.get("cap") or "")
        if cap == "search":
            return self._search(snap)
        if cap == "vault-write":
            return self._remember(snap)
        if cap == "distill":
            return self._distill(snap)
        if cap == "home":
            return self._home(snap)
        raise RuntimeError(f"unsupported cap {cap!r}")

    def _home(self, snap: dict) -> tuple[str, str]:
        from memory.ha import run_home

        return run_home(self.home, snap)

    def _search(self, snap: dict) -> tuple[str, str]:
        prompt = str(snap.get("prompt") or "").strip()
        speak = self._ask(prompt, system=SEARCH_SYSTEM, web=True, max_turns=6, timeout=80)
        speak = " ".join(speak.split())
        if re.search(r"weather|forecast", prompt, re.I):
            cache = self.home.cache / "weather.md"
            cache.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            cache.write_text(f"{speak}\n\n_cached {stamp}_\n", encoding="utf-8")
        return speak, speak

    def _remember(self, snap: dict) -> tuple[str, str]:
        prompt = str(snap.get("prompt") or "").strip()
        dest = str(snap.get("dest") or remember_dest(prompt))
        bullet = ""
        try:
            raw = self._ask(
                f"Utterance: {prompt}",
                system=REMEMBER_SYSTEM,
                web=False,
                max_turns=1,
                timeout=30,
            )
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                bullet = str(parsed.get("bullet") or "").strip()
        except Exception as exc:
            log(f"[workshop] remember polish skipped ({exc})")
        if not bullet:
            bullet = file_line(prompt)
        if dest == "reminders":
            from memory.reminders import format_from_utterance

            bullet = format_from_utterance(prompt, fallback=bullet)
        path = dest_path(self.home, dest)
        if path is None:
            raise RuntimeError(f"refusing vault dest {dest!r}")
        wrote = append_bullet(path, bullet)
        result = f"{dest}: {bullet}" if wrote else f"{dest}: duplicate"
        return "", result

    def _distill(self, snap: dict) -> tuple[str, str]:
        path = Path(str(snap.get("path") or ""))
        transcript = _session_turns(path)
        if not transcript.strip():
            return "", "no turns"
        raw = self._ask(
            "Transcript:\n" + transcript,
            system=DISTILL_SYSTEM,
            web=False,
            max_turns=1,
            timeout=60,
        )
        parsed = extract_json(raw)
        facts = []
        if isinstance(parsed, dict):
            facts = parsed.get("facts") or []
        written = 0
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            dest = str(fact.get("dest") or "")
            bullet = str(fact.get("bullet") or "")
            dest_file = dest_path(self.home, dest)
            if dest_file is None:
                log(f"[workshop] distill skipped dest {dest!r}")
                continue
            if append_bullet(dest_file, bullet):
                written += 1
        result = f"filed {written} fact(s)"
        return "", result

    def tick(self) -> bool:
        """Claim and run at most one runnable job. True if work ran."""
        self.beat()
        jobs = self.board.runnable(list(self.caps))
        if not jobs:
            return False
        snap = jobs[0]
        job_id = str(snap.get("id") or "")
        if not job_id or not self.board.claim(job_id, self.worker_id):
            return False
        log(f"[workshop] {job_id} {snap.get('cap')}")
        try:
            speak, result = self.handle(self.board.snapshot(job_id))
            self.board.finish(job_id, speak=speak, result=result)
            log(f"[workshop] {job_id} done {result!r}")
        except Exception as exc:
            log(f"[workshop] {job_id} error {exc}")
            self.board.fail(job_id, str(exc))
        return True

    def run(self, *, once: bool = False, idle_s: float = 0.25) -> None:
        self.home.ensure()
        self.advertise()
        log(f"[workshop] {self.worker_id} caps={','.join(self.caps)} home={self.home.root}")
        while True:
            if self.parent_pid and _parent_gone(self.parent_pid):
                log("[workshop] parent gone, exit")
                return
            ran = self.tick()
            if once:
                return
            if not ran:
                time.sleep(idle_s)


def spawn_host_workshop(
    home: JarvisHome,
    *,
    grok: Path,
    model: str,
    parent_pid: int,
) -> subprocess.Popen:
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "memory.worker",
        "--data-dir",
        str(home.root),
        "--grok",
        str(grok),
        "--model",
        model,
        "--parent-pid",
        str(parent_pid),
    ]
    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    return subprocess.Popen(cmd, cwd=str(root), env=env, **extra)


def drain_runnable(
    home: JarvisHome,
    *,
    grok: Path | None = None,
    model: str = "grok-4.5",
    complete: CompleteFn | None = None,
    limit: int = 8,
) -> int:
    """Run leftover jobs in-process (session close / dead worker)."""
    worker = HostWorker(
        home,
        grok=grok,
        model=model,
        worker_id="host-close",
        complete=complete,
    )
    n = 0
    for _ in range(limit):
        if not worker.tick():
            break
        n += 1
    return n


def _ignore_sigint() -> None:
    if sys.platform == "win32":
        return
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jarvis host workshop")
    p.add_argument("--data-dir", default=None)
    p.add_argument("--grok", default=None)
    p.add_argument("--model", default="grok-4.5")
    p.add_argument("--worker-id", default=None)
    p.add_argument("--parent-pid", type=int, default=0)
    p.add_argument("--once", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    _ignore_sigint()
    args = parse_args(argv)
    home = JarvisHome.discover(args.data_dir)
    grok = Path(args.grok).expanduser() if args.grok else find_grok()
    worker = HostWorker(
        home,
        grok=grok,
        model=args.model,
        worker_id=args.worker_id,
        parent_pid=args.parent_pid,
    )
    worker.run(once=args.once)


if __name__ == "__main__":
    main()
