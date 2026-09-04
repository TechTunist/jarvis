"""One-shot grok -p for the hands thread. Not used by the mouth."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from shutil import which
from typing import NamedTuple


def _child_env() -> dict[str, str]:
    """Hands Grok inherits this process env.

    On Linux, also the desktop session (snap PATH, DISPLAY, DBus) so browser
    tools work. Windows has no getuid / X11 / snap — leave PATH alone.
    """
    env = dict(os.environ)
    if sys.platform == "win32":
        return env
    path = env.get("PATH") or ""
    extra = "/snap/bin:/usr/bin:/usr/local/bin"
    if extra not in path:
        env["PATH"] = f"{path}:{extra}" if path else extra
    if not env.get("DISPLAY") and Path("/tmp/.X11-unix/X0").exists():
        env["DISPLAY"] = ":0"
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return env
    runtime = Path(f"/run/user/{getuid()}")
    if runtime.is_dir():
        env.setdefault("XDG_RUNTIME_DIR", str(runtime))
        bus = runtime / "bus"
        if bus.exists():
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus}")
    return env

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


def _communicate(
    proc: subprocess.Popen,
    *,
    timeout: float,
    abort: Callable[[], bool] | None,
) -> tuple[str, str]:
    if abort is None:
        out = proc.communicate(timeout=timeout)
        return out[0] or "", out[1] or ""
    deadline = time.monotonic() + timeout
    while True:
        if abort():
            proc.kill()
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise InterruptedError("cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.kill()
            proc.communicate()
            raise subprocess.TimeoutExpired(proc.args, timeout)
        try:
            out = proc.communicate(timeout=min(0.25, remaining))
            return out[0] or "", out[1] or ""
        except subprocess.TimeoutExpired:
            continue


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
    effort: str = "low",
    disallowed: str | None = None,
    subagents: bool = False,
    image: Path | str | None = None,
) -> list[str]:
    cmd = [str(grok)]
    # Never put a still on the Grok CLI. Cloud vision is off.
    cmd.extend(["-p", prompt])
    cmd.extend([
        "-m",
        model,
        "--effort",
        effort,
        "--always-approve",
        "--no-leader",
        "--max-turns",
        str(max_turns),
        "--system-prompt-override",
        system,
        "--output-format",
        "streaming-json",
    ])
    if not subagents:
        cmd.append("--no-subagents")
    if cwd is not None:
        cmd.extend(["--cwd", str(cwd)])
    if tools:
        cmd.extend(["--tools", tools])
    elif disallowed is not None:
        cmd.extend(["--disallowed-tools", disallowed])
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
    effort: str = "low",
    disallowed: str | None = None,
    subagents: bool = False,
    abort: Callable[[], bool] | None = None,
    image: Path | str | None = None,
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
        effort=effort,
        disallowed=disallowed,
        subagents=subagents,
        image=image,
    )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd is not None else None,
        env=_child_env(),
    )
    try:
        stdout, stderr = _communicate(proc, timeout=timeout, abort=abort)
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
    effort: str = "low",
    disallowed: str | None = None,
    subagents: bool = False,
    abort: Callable[[], bool] | None = None,
    image: Path | str | None = None,
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
        effort=effort,
        disallowed=disallowed,
        subagents=subagents,
        abort=abort,
        image=image,
    )
    if not got.text:
        raise RuntimeError((got.stderr or "grok produced no text").strip()[:400])
    return got.text
