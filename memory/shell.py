"""Laptop shell workshop: this git checkout only.

The desk stays tool-free. Merge and push stay a human gate. Talk is never
restarted from under itself.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from memory.grokrun import extract_json
from memory.home import JarvisHome

SHELL_CAPS = ("shell",)
SHELL_TOOLS = "run_terminal_cmd,read_file,search_replace,grep,list_dir,glob"
SHELL_SYSTEM = (
    "You are Jarvis's laptop workshop, not the front desk. "
    "This directory is the Jarvis git checkout. Use tools here only. "
    "Run tests with: python3 -m unittest discover -s tests. "
    "For edits, create branch jarvis/workshop-<short-slug> first. "
    "Never git push. Never merge. Never commit to main or master. "
    "Never restart Talk, never kill talk.py, never touch ~/.jarvis/secrets. "
    "No Imagine, no web search, no other repos. "
    "When finished, JSON only: "
    '{"speak":"<one or two spoken sentences>","ok":true,"branch":"<name or empty>"}. '
    "British butler. First sentence at most six words. No markdown, no preamble."
)

_TESTS = re.compile(
    r"(?:^|\b)(?:please\s+)?(?:run|running)\s+(?:the\s+)?tests?\b"
    r"|\b(?:pytest|unittest)\b",
    re.I,
)
_ALSO_PATCH = re.compile(r"\b(?:fix|patch|edit|change|commit|merge)\b", re.I)
_PUSH = re.compile(r"\b(?:git\s+)?push\b|\bforce[\s-]*push\b", re.I)
_MERGE = re.compile(
    r"\b(?:git\s+)?merge\b|\bmerge\s+(?:it|that|this|the\s+branch)\b"
    r"|\bcommit\s+to\s+(?:main|master)\b",
    re.I,
)
_RESTART = re.compile(
    r"\b(?:restart|kill|stop)\s+(?:talk|the\s+(?:desk|receptionist))\b"
    r"|\brestart\s+jarvis\b",
    re.I,
)
_RAN = re.compile(r"Ran (\d+) tests?")
_FAILED = re.compile(r"FAILED \(([^)]*)\)")


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for path in (here, *here.parents):
        if (path / ".git").exists() and (path / "memory" / "worker.py").is_file():
            return path
    return Path(__file__).resolve().parent.parent


def looks_like_tests(text: str) -> bool:
    raw = " ".join((text or "").split())
    if not raw or not _TESTS.search(raw):
        return False
    return not _ALSO_PATCH.search(raw)


def refuse_reason(text: str) -> str:
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    if _PUSH.search(raw):
        return "I won't push that, sir. Merge stays with you."
    if _MERGE.search(raw):
        return "I won't merge that, sir. The branch is ready when you are."
    if _RESTART.search(raw):
        return "I won't restart Talk from here, sir."
    return ""


def speak_tests(returncode: int, stdout: str, stderr: str) -> tuple[str, str]:
    blob = f"{stdout or ''}\n{stderr or ''}"
    ran = _RAN.search(blob)
    n = int(ran.group(1)) if ran else 0
    if returncode == 0:
        if n:
            return f"All {n} tests passed, sir.", f"ok:{n}"
        return "Tests passed, sir.", "ok"
    failed = 0
    hit = _FAILED.search(blob)
    if hit:
        for part in hit.group(1).split(","):
            if "=" not in part:
                continue
            try:
                failed += int(part.split("=", 1)[1])
            except ValueError:
                continue
    if failed:
        return f"{failed} tests failed, sir.", f"fail:{failed}"
    return "Tests failed, sir.", "fail"


def run_unittests(
    repo: Path,
    *,
    python: str | None = None,
    timeout: float = 180,
) -> tuple[str, str]:
    cmd = [
        python or sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-q",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "Tests timed out, sir.", "timeout"
    return speak_tests(proc.returncode, proc.stdout or "", proc.stderr or "")


def speak_from_grok(raw: str) -> tuple[str, str]:
    data = extract_json(raw)
    if isinstance(data, dict):
        speak = " ".join(str(data.get("speak") or "").split())
        branch = str(data.get("branch") or "").strip()
        if speak:
            return speak, branch or ("ok" if data.get("ok") else "done")
    text = " ".join((raw or "").split())
    if text:
        return text[:280], "done"
    return "The workshop finished that, sir.", "done"


def shell_brief(home: JarvisHome, asked: str) -> str:
    from memory.working import pack_recent

    recent = pack_recent(home, limit=8, clip=400, span="day")
    chunks: list[str] = []
    if recent:
        chunks.append("Recent conversation:\n" + recent)
    chunks.append("Matt asked: " + " ".join((asked or "").split()))
    chunks.append(
        "Stay in this git checkout. Do not merge, push, or restart Talk."
    )
    return "\n\n".join(chunks)
