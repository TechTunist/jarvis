"""Time Grok TTFB for receptionist-sized prompts. No extra packages."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROK = Path.home() / ".grok" / "bin" / "grok.exe"
PROMPT = "Hello Jarvis, just saying hi."
OVERRIDE = (
    "You are Jarvis, a British butler receptionist. "
    "Reply in one short witty spoken sentence. No markdown, no tools, no lists."
)
MODELS = ("grok-4.5", "grok-4.6")


def grok_cmd(model: str, extra: list[str]) -> list[str]:
    return [
        str(GROK),
        "-p",
        PROMPT,
        "-m",
        model,
        "--effort",
        "low",
        "--cwd",
        str(HERE),
        "--always-approve",
        "--no-subagents",
        "--disable-web-search",
        "--max-turns",
        "1",
        "--system-prompt-override",
        OVERRIDE,
        "--output-format",
        "streaming-json",
        *extra,
    ]


def run_once(label: str, cmd: list[str]) -> dict:
    t0 = time.perf_counter()
    t_text = None
    t_end = None
    first_text = ""
    err_tail = []
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(HERE),
    )
    assert proc.stdout and proc.stderr
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        if kind == "text" and t_text is None:
            t_text = time.perf_counter()
            first_text = str(ev.get("data") or "")[:120]
        if kind == "end" and t_end is None:
            t_end = time.perf_counter()
    proc.wait(timeout=180)
    if proc.returncode != 0:
        err_tail = (proc.stderr.read() or "")[-800:].splitlines()[-12:]
    now = time.perf_counter()
    return {
        "label": label,
        "ok": proc.returncode == 0 and t_text is not None,
        "ttfb_ms": round(((t_text or now) - t0) * 1000),
        "total_ms": round(((t_end or now) - t0) * 1000),
        "first": first_text,
        "rc": proc.returncode,
        "err": err_tail,
    }


def main() -> None:
    if not GROK.is_file():
        sys.exit(f"grok not found at {GROK}")
    print(f"cwd={HERE}")
    print(f"prompt={PROMPT!r}")
    rows = []
    for model in MODELS:
        # cold (new process, new session)
        rows.append(run_once(f"{model} cold", grok_cmd(model, [])))
        print(json.dumps(rows[-1], ensure_ascii=False))
        # continue: should reuse last session in this cwd
        rows.append(run_once(f"{model} continue", grok_cmd(model, ["-c"])))
        print(json.dumps(rows[-1], ensure_ascii=False))
    print("\n--- summary ---")
    for r in rows:
        print(
            f"{r['label']:22} ttfb={r['ttfb_ms']:5}ms  total={r['total_ms']:5}ms  "
            f"ok={r['ok']}  {r['first']!r}"
        )
        if r["err"]:
            print("  err:", " | ".join(r["err"]))


if __name__ == "__main__":
    main()
