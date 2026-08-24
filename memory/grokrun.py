"""One-shot grok -p for workshop jobs. Not used by the front desk."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from shutil import which
from typing import NamedTuple

NO_MEDIA = "image_gen,image_edit,image_to_video,reference_to_video"
NO_TOOLS = (
    "Agent,run_terminal_cmd,read_file,search_replace,web_search,web_fetch,"
    "grep,list_dir,glob," + NO_MEDIA
)
# Search keeps web tools; this list is subtracted only when we also pass
# --disallowed-tools for the rest.
NO_SHELL = (
    "Agent,run_terminal_cmd,read_file,search_replace,grep,list_dir,glob," + NO_MEDIA
)


def find_grok() -> Path:
    bin_dir = Path.home() / ".grok" / "bin"
    names = ("grok", "grok.exe")
    for name in names:
        p = bin_dir / name
        if p.is_file():
            return p
    w = which("grok") or which("grok.exe")
    if w:
        return Path(w)
    return bin_dir / names[0]


def text_from_stream(stdout: str) -> str:
    chunks: list[str] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            if not chunks and line.startswith("{"):
                continue
            if not line.startswith("{"):
                chunks.append(line)
            continue
        if ev.get("type") == "text":
            chunk = str(ev.get("data") or "")
            if chunk:
                chunks.append(chunk)
        elif isinstance(ev.get("result"), str):
            chunks.append(ev["result"])
        elif isinstance(ev.get("text"), str) and ev.get("type") not in (
            "thinking",
            "tool",
        ):
            chunks.append(ev["text"])
    if chunks:
        return "".join(chunks).strip()
    return (stdout or "").strip()


def session_id_from_stream(stdout: str) -> str:
    sid = ""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "end":
            sid = str(ev.get("sessionId") or ev.get("session_id") or sid)
        elif ev.get("sessionId") or ev.get("session_id"):
            sid = str(ev.get("sessionId") or ev.get("session_id") or sid)
    return sid


class PromptResult(NamedTuple):
    text: str
    stdout: str = ""
    stderr: str = ""
    session_id: str = ""


def extract_json(text: str) -> dict | list | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        val = json.loads(raw)
        if isinstance(val, (dict, list)):
            return val
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            val = json.loads(raw[start : end + 1])
            if isinstance(val, (dict, list)):
                return val
        except json.JSONDecodeError:
            return None
    return None


def prompt_argv(
    prompt: str,
    *,
    grok: Path,
    model: str,
    system: str,
    web: bool,
    max_turns: int = 6,
    tools: str | None = None,
    cwd: Path | str | None = None,
) -> list[str]:
    cmd = [
        str(grok),
        "-p",
        prompt,
        "-m",
        model,
        "--effort",
        "low",
        "--always-approve",
        "--no-subagents",
        "--no-leader",
        "--max-turns",
        str(max_turns),
        "--system-prompt-override",
        system,
        "--output-format",
        "streaming-json",
    ]
    if cwd is not None:
        cmd.extend(["--cwd", str(cwd)])
    if tools:
        cmd.extend(["--tools", tools])
        cmd.append("--disable-web-search")
    else:
        cmd.extend(["--disallowed-tools", NO_SHELL if web else NO_TOOLS])
        if not web:
            cmd.append("--disable-web-search")
    return cmd


def run_prompt_result(
    prompt: str,
    *,
    grok: Path,
    model: str,
    system: str,
    web: bool,
    max_turns: int = 6,
    timeout: float = 90,
    tools: str | None = None,
    cwd: Path | str | None = None,
) -> PromptResult:
    if not grok.is_file():
        raise FileNotFoundError(f"grok CLI missing: {grok}")
    cmd = prompt_argv(
        prompt,
        grok=grok,
        model=model,
        system=system,
        web=web,
        max_turns=max_turns,
        tools=tools,
        cwd=cwd,
    )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd is not None else None,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise TimeoutError("grok prompt timed out")
    if proc.returncode not in (0, None) and not (stdout or "").strip():
        err = (stderr or "").strip()[:400]
        raise RuntimeError(err or f"grok exited {proc.returncode}")
    text = text_from_stream(stdout)
    return PromptResult(
        text=text,
        stdout=stdout or "",
        stderr=stderr or "",
        session_id=session_id_from_stream(stdout),
    )


def run_prompt(
    prompt: str,
    *,
    grok: Path,
    model: str,
    system: str,
    web: bool,
    max_turns: int = 6,
    timeout: float = 90,
    tools: str | None = None,
    cwd: Path | str | None = None,
) -> str:
    got = run_prompt_result(
        prompt,
        grok=grok,
        model=model,
        system=system,
        web=web,
        max_turns=max_turns,
        timeout=timeout,
        tools=tools,
        cwd=cwd,
    )
    if not got.text:
        raise RuntimeError((got.stderr or "grok produced no text").strip()[:400])
    return got.text
