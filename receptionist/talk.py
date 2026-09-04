"""Jarvis receptionist latency spike.

Hold Home to talk, or --listen for always-on energy VAD, or type if --stt none.
Times every stage. Swap --brain / --model / --stt / --tts.

Examples:
  .venv\\Scripts\\python talk.py --bench
  .venv\\Scripts\\python talk.py --brain agent --model grok-4.6 --stt none --tts sapi
  .venv\\Scripts\\python talk.py --brain agent --model grok-4.6 --stt tiny --tts sapi
  .venv\\Scripts\\python talk.py --brain agent --model grok-4.6 --stt base --tts edge --listen
  .venv\\Scripts\\python talk.py --brain cli --model grok-4.6 --stt none --tts none
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from shutil import which

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (HERE, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from hud_server import (  # noqa: E402
    incoming_jobs,
    set_state as hud_state,
    start_hud,
    stop_hud,
)
from memory.distill import distill_session  # noqa: E402
from memory.grokrun import NO_TOOLS  # noqa: E402
from memory.ears import (  # noqa: E402
    EnergyGate,
    after_wake,
    format_inputs,
    list_inputs,
    load_mic_pref,
    pick_input,
    rms_peak,
    transcribe_pcm,
    vocabulary,
)
from memory.home import JarvisHome  # noqa: E402
from memory.imagine import library_label, rescue_session_media, speak_ready  # noqa: E402
from memory.batch import is_ping, latest_wins  # noqa: E402
from memory.ha import is_no, is_yes, pending_confirm  # noqa: E402
from memory.intent import HOME, HUSH, classify, maybe_enqueue, resolve_intents  # noqa: E402
from memory.replace import (  # noqa: E402
    ask as ask_replace,
    contended,
    keep_line,
    pending as pending_replace,
    clear as clear_replace,
)
from memory.route import intent_for_cap  # noqa: E402
from memory.route import ROUTE_SYSTEM, ROUTE_TIMEOUT_S, roster_card  # noqa: E402
from memory.jobs import JobBoard  # noqa: E402
from memory.prompt import SPEECH_RULES, build_system_prompt, load_boot_notes  # noqa: E402
from memory.session import SessionLog  # noqa: E402
from memory.reminders import take_due  # noqa: E402
from memory.worker import (  # noqa: E402
    HOST_CAPS,
    drain_runnable,
    process_image,
    spawn_host_workshop,
    spawn_shell_workshop,
)
from memory.workshops import WorkshopRegistry  # noqa: E402
WIN = sys.platform == "win32"
# Closest Edge neural we can legally use: British, composed, not a celebrity clone.
EDGE_VOICE = "en-GB-ThomasNeural"
EDGE_RATE = "-2%"
EDGE_PITCH = "+4Hz"
LOCK = HERE / "talk.pid"


def find_grok() -> Path:
    """Windows ships grok.exe; Linux/macOS use grok. PATH is a fallback."""
    bin_dir = Path.home() / ".grok" / "bin"
    names = ("grok.exe", "grok") if WIN else ("grok", "grok.exe")
    for name in names:
        p = bin_dir / name
        if p.is_file():
            return p
    w = which("grok") or which("grok.exe")
    if w:
        return Path(w)
    return bin_dir / names[0]


GROK = find_grok()


def find_ffplay() -> Path | None:
    hits: list[Path] = []
    w = which("ffplay") or which("ffplay.exe")
    if w:
        hits.append(Path(w))
    if WIN:
        hits.append(
            Path(
                r"C:\Users\oppat\AppData\Local\Microsoft\WinGet\Packages"
                r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
                r"\ffmpeg-9.0-full_build\bin\ffplay.exe"
            )
        )
        winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
        if winget.is_dir():
            hits.extend(winget.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffplay.exe"))
    for p in hits:
        if p and p.is_file():
            return p
    return None


FFPLAY = find_ffplay()
PLAY_RATE = 24000
PREROLL_S = 0.22
SENTENCE_END = re.compile(r"(?<=[.!?])(?:\s+|(?=[A-Z]))")
OVERRIDE = SPEECH_RULES
PROGRESS_AFTER_S = 12
PROGRESS_LINE = "Still working on that, sir."
BUSY_ACK = "I'm listening, sir."


def find_ffmpeg() -> Path | None:
    fp = find_ffplay()
    if fp:
        for name in ("ffmpeg.exe", "ffmpeg"):
            cand = fp.with_name(name)
            if cand.is_file():
                return cand
    w = which("ffmpeg") or which("ffmpeg.exe")
    return Path(w) if w else None


FFMPEG = find_ffmpeg()
HELLO = "Hello Jarvis, just saying hi."


def ffmpeg_argv(*args: str) -> list[str]:
    if FFMPEG is None:
        raise RuntimeError("ffmpeg not found (install ffmpeg)")
    # -nostdin: Talk also reads the TTY; ffmpeg must not steal stdin.
    return [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-nostdin", *args]


def upload_suffix(content_type: str) -> str:
    """iPhone MediaRecorder is usually audio/mp4 (AAC). Android often webm."""
    low = (content_type or "").lower()
    if "webm" in low:
        return ".webm"
    if "wav" in low:
        return ".wav"
    if "mpeg" in low or "mp3" in low:
        return ".mp3"
    if "aac" in low and "mp4" not in low:
        return ".aac"
    return ".mp4"


def log(msg: str) -> None:
    print(msg, flush=True)


_NOT_TALK = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "conhost.exe",
        "openconsole.exe",
        "windowsterminal.exe",
        "windows terminal.exe",
    }
)


def _ignore_console_ctrl(ignore: bool) -> None:
    """Windows: taskkill / dying console apps can broadcast CTRL_C_EVENT to
    this window. Swallow it during lock-steal and worker spawn."""
    if not WIN:
        return
    import ctypes

    ctypes.windll.kernel32.SetConsoleCtrlHandler(None, bool(ignore))


def take_lock() -> None:
    """Only one Talk window. An old David session plus a new British one
    both bind Home and both speak."""
    if LOCK.is_file():
        try:
            old = int(LOCK.read_text().strip().split()[0])
        except ValueError:
            old = 0
        if old and old != os.getpid():
            log(f"[talk] stopping previous receptionist pid={old}")
            _kill_pid(old)
            time.sleep(0.4)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def _kill_pid(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        if pid == os.getppid():
            log(f"[talk] skip stopping pid={pid} (this window's parent)")
            return
    except OSError:
        pass
    if WIN:
        image = process_image(pid)
        name = Path(image).name.lower() if image else ""
        if not name:
            log(f"[talk] skip stopping pid={pid} (already gone)")
            return
        if name in _NOT_TALK or "python" not in name:
            log(f"[talk] skip stopping pid={pid} ({name})")
            return
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def drop_lock() -> None:
    try:
        if LOCK.is_file() and LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


# ---- brain: cold grok -p (new process every turn) -------------------------

class CliBrain:
    name = "cli"

    def __init__(self, model: str, system_prompt: str = SPEECH_RULES):
        self.model = model
        self.system_prompt = system_prompt
        self.warm = False

    def start(self) -> None:
        self.warm = True

    def warmup(self) -> None:
        pass

    def close(self) -> None:
        pass

    def ask(self, text: str):
        cmd = [
            str(GROK),
            "-p",
            text,
            "-m",
            self.model,
            "--effort",
            "medium",
            "--cwd",
            str(HERE),
            "--always-approve",
            "--no-subagents",
            "--disable-web-search",
            "--disallowed-tools",
            NO_TOOLS,
            "--max-turns",
            "1",
            "--system-prompt-override",
            self.system_prompt,
            "--output-format",
            "streaming-json",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(HERE),
        )
        assert proc.stdout
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "text":
                    chunk = str(ev.get("data") or "")
                    if chunk:
                        yield chunk
                elif ev.get("type") in ("end", "error"):
                    break
        finally:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()


# ---- brain: warm grok agent (one process, many turns) ---------------------

class AgentBrain:
    name = "agent"

    def __init__(
        self,
        model: str,
        system_prompt: str = SPEECH_RULES,
        *,
        log_path: Path | None = None,
        client: str = "jarvis-receptionist",
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.log_path = log_path or (HERE / "agent.stderr.log")
        self.client = client
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._updates: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self.session_id = ""
        self.warm = False

    def start(self) -> None:
        # grok agent stdio ignores --disallowed-tools (headless-only).
        # dontAsk + deny rules actually block Imagine/shell. Never yolo.
        deny = [
            "--permission-mode",
            "dontAsk",
            "--no-subagents",
            "--disable-web-search",
            "--deny",
            "Bash",
            "--deny",
            "Read",
            "--deny",
            "Write",
            "--deny",
            "Edit",
            "--deny",
            "Grep",
            "--deny",
            "WebFetch",
        ]
        base = [
            "agent",
            "-m",
            self.model,
            "--effort",
            "medium",
            "--no-leader",
            "stdio",
        ]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        err = self.log_path.open("ab")
        init = {
            "protocolVersion": 1,
            "clientInfo": {"name": self.client, "version": "0"},
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False,
            },
        }
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = subprocess.Popen(
            [str(GROK), *deny, *base],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            cwd=str(HERE),
            bufsize=0,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        time.sleep(0.25)
        if self.proc.poll() is not None:
            raise RuntimeError("tool-free grok agent exited")
        self._rpc("initialize", init)
        result = self._rpc(
            "session/new",
            {
                "cwd": str(HERE),
                "mcpServers": [],
                "_meta": {
                    "systemPromptOverride": self.system_prompt,
                },
            },
        )
        self.session_id = result.get("sessionId") or result.get("session_id") or ""
        if not self.session_id:
            raise RuntimeError(f"session/new failed: {result!r}")
        self.warm = True

    def warmup(self, text: str | None = None) -> None:
        ping = text or "Warmup ping. Reply with the single word ready."
        log(f"[{self.client}] warming prompt cache...")
        t0 = time.perf_counter()
        self.complete(ping, timeout=30)
        log(f"[{self.client}] cache hot in {int((time.perf_counter()-t0)*1000)}ms")

    def complete(self, text: str, timeout: float = 8) -> str:
        return "".join(self.ask(text, timeout=timeout))

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass

    def _next_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    def _send(self, obj: dict) -> None:
        assert self.proc and self.proc.stdin
        line = json.dumps(obj) + "\n"
        with self._lock:
            self.proc.stdin.write(line.encode("utf-8"))
            self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict, timeout: float = 60) -> dict:
        rid = self._next_id()
        box: queue.Queue = queue.Queue()
        self._pending[rid] = box
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            msg = box.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"ACP {method} timed out")
        finally:
            self._pending.pop(rid, None)
        if "error" in msg:
            raise RuntimeError(f"ACP {method}: {msg['error']}")
        return msg.get("result") or {}

    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        buf = b""
        while True:
            chunk = self.proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if not raw.strip():
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                mid = msg.get("id")
                if mid in self._pending:
                    self._pending[mid].put(msg)
                method = msg.get("method")
                if method in ("session/update", "_x.ai/session/prompt_complete"):
                    self._updates.put(msg)
                elif method and "id" in msg:
                    self._send(
                        {
                            "jsonrpc": "2.0",
                            "id": msg["id"],
                            "error": {"code": -32601, "message": "not supported"},
                        }
                    )

    def _chunk(self, msg: dict) -> str:
        params = msg.get("params") or {}
        update = params.get("update") or params
        kind = update.get("sessionUpdate") or update.get("session_update")
        if kind != "agent_message_chunk":
            return ""
        content = update.get("content") or {}
        if isinstance(content, dict):
            return content.get("text") or ""
        return str(content) if content else ""

    def ask(self, text: str, timeout: float | None = None):
        while True:
            try:
                self._updates.get_nowait()
            except queue.Empty:
                break
        rid = self._next_id()
        done: queue.Queue = queue.Queue()
        self._pending[rid] = done
        self._send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "session/prompt",
                "params": {
                    "sessionId": self.session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            }
        )
        finished = False
        idle_after = 0.0
        started = time.perf_counter()
        while True:
            if timeout is not None and time.perf_counter() - started > timeout:
                log(f"[{self.client}] ask timed out after {timeout:.0f}s")
                break
            try:
                msg = self._updates.get(timeout=0.05)
            except queue.Empty:
                if not done.empty() or finished:
                    if not finished:
                        finished = True
                        idle_after = time.perf_counter()
                    if time.perf_counter() - idle_after > 0.2:
                        break
                if self.proc and self.proc.poll() is not None:
                    raise RuntimeError("grok agent exited")
                continue
            if msg.get("method") == "_x.ai/session/prompt_complete":
                finished = True
                idle_after = time.perf_counter()
                continue
            chunk = self._chunk(msg)
            if chunk:
                yield chunk
        self._pending.pop(rid, None)


# ---- ears / mouth ---------------------------------------------------------

_whisper = None
_stt_prompt = ""
_stt_hotwords = ""
_mic: dict | None = None


def _prepend_cuda_dlls() -> None:
    """Windows: ctranslate2 finds the GPU but not pip-installed CUDA bins."""
    import site

    roots = [Path(p) / "nvidia" for p in site.getsitepackages()]
    extra = []
    for root in roots:
        if not root.is_dir():
            continue
        for bin_dir in root.glob("*/bin"):
            extra.append(str(bin_dir))
    if not extra:
        return
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])
    add = getattr(os, "add_dll_directory", None)
    if add:
        for d in extra:
            try:
                add(d)
            except OSError:
                pass


def stt_device() -> str:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _load_whisper(name: str, device: str, compute: str):
    import numpy as np
    from faster_whisper import WhisperModel

    log(f"[ears] loading {name}.en on {device}/{compute} ...")
    t0 = time.perf_counter()
    model = WhisperModel(f"{name}.en", device=device, compute_type=compute)
    # Force a real encode now so missing CUDA DLLs fail here, not on first talk.
    list(model.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])
    log(f"[ears] ready in {int((time.perf_counter()-t0)*1000)}ms")
    return model


def warm_stt(model: str) -> str:
    global _whisper
    if model == "none":
        return "none"
    _prepend_cuda_dlls()
    device = stt_device()
    try:
        compute = "float16" if device == "cuda" else "int8"
        _whisper = _load_whisper(model, device, compute)
        return f"{device}/{compute}"
    except Exception as exc:
        if device != "cuda":
            raise
        log(f"[ears] CUDA failed ({exc}). Falling back to CPU.")
        _whisper = _load_whisper(model, "cpu", "int8")
        return "cpu/int8"


def transcribe(pcm) -> tuple[str, str]:
    import numpy as np

    audio = np.asarray(pcm, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio[:, 0]
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.5:
        audio = audio / 32768.0
    text, note = transcribe_pcm(
        audio, _whisper, prompt=_stt_prompt, hotwords=_stt_hotwords
    )
    return text, note


def decode_upload(data: bytes, content_type: str):
    """iPhone MediaRecorder blob -> float32 mono 16 kHz for Whisper."""
    import numpy as np
    import tempfile

    suffix = upload_suffix(content_type)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        path = f.name
    try:
        proc = subprocess.run(
            ffmpeg_argv(
                "-i",
                path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ),
            capture_output=True,
            check=False,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if proc.returncode not in (0, None) or not (proc.stdout or b""):
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(err or "could not decode phone audio")
    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError("could not decode phone audio")
    return pcm.astype(np.float32) / 32768.0


def _phone_say(mouth: Mouth, line: str) -> bytes:
    prev = mouth.hear
    mouth.hear = False
    mouth._capture = []
    try:
        mouth.say(line)
        return b"".join(mouth._capture or [])
    finally:
        mouth.hear = prev
        mouth._capture = None


def handle_phone_job(job, desk: Desk) -> None:
    mouth = desk.mouth
    from memory.people import resolve_who, with_vocative

    who = resolve_who(getattr(job, "who", "") or "", desk.roster)
    if who is not None:
        desk.set_speaker(who)
    prev = mouth.hear
    mouth.hear = False
    miss = with_vocative("I didn't catch that, sir.", desk.speaker)
    fail = with_vocative("The phone link failed, sir.", desk.speaker)
    try:
        hud_state("listening")
        pcm = decode_upload(job.data, job.content_type)
        if getattr(pcm, "size", 0) < 1600:
            mp3 = _phone_say(mouth, miss)
            job.finish(text="", mp3=mp3)
            hud_state("idle")
            return
        t0 = time.perf_counter()
        text, note = transcribe(pcm)
        stt_ms = round((time.perf_counter() - t0) * 1000)
        log(f"[phone] {text!r}  (stt {stt_ms}ms {note})")
        if not text:
            mp3 = _phone_say(mouth, miss)
            job.finish(text="", mp3=mp3)
            hud_state("idle")
            return
        mouth._capture = []
        desk.utter(text, stt_ms=stt_ms)
        mp3 = b"".join(mouth._capture or [])
        mouth._capture = None
        job.finish(text=text, mp3=mp3)
        hud_state("idle")
    except Exception as exc:
        log(f"[phone] {exc}")
        mouth._capture = None
        try:
            mp3 = _phone_say(mouth, fail)
            if mp3:
                job.finish(text="", mp3=mp3)
            else:
                job.finish(error=str(exc)[:400])
        except Exception:
            job.finish(error=str(exc)[:400])
        hud_state("idle")
    finally:
        mouth.hear = prev


def handle_glance_job(job, desk: Desk) -> None:
    mouth = desk.mouth
    from memory.people import resolve_who, with_vocative

    who = resolve_who(getattr(job, "who", "") or "", desk.roster)
    if who is not None:
        desk.set_speaker(who)
    prev = mouth.hear
    mouth.hear = False
    line = with_vocative(
        "I don't send pictures off this machine, sir. "
        "I haven't got eyes that stay in the house yet.",
        desk.speaker,
    )
    try:
        hud_state("speaking", line)
        mp3 = _phone_say(mouth, line)
        job.finish(text=line, mp3=mp3)
        hud_state("idle")
    except Exception as exc:
        log(f"[eyes] {exc}")
        job.finish(error=str(exc)[:400])
        hud_state("idle")
    finally:
        mouth.hear = prev


def record_held(is_held, samplerate=16000):
    import numpy as np
    import sounddevice as sd

    chunks = []
    kwargs = {"samplerate": samplerate, "channels": 1, "dtype": "float32"}
    if _mic is not None:
        kwargs["device"] = _mic["index"]
    with sd.InputStream(**kwargs) as stream:
        while is_held():
            block, _ = stream.read(int(samplerate * 0.03))
            chunks.append(block.copy())
    if not chunks:
        return None
    return np.concatenate(chunks, axis=0)


def record_utterance(should_stop, samplerate=16000):
    """Open mic: wait for speech energy, then until silence. None if aborted."""
    import numpy as np
    import sounddevice as sd

    gate = EnergyGate()
    chunks = []
    preroll = []
    started = False
    kwargs = {"samplerate": samplerate, "channels": 1, "dtype": "float32"}
    if _mic is not None:
        kwargs["device"] = _mic["index"]
    frame = int(samplerate * 0.03)
    last_log = time.monotonic()
    max_rms = 0.0
    max_peak = 0.0
    with sd.InputStream(**kwargs) as stream:
        while not should_stop():
            block, _ = stream.read(frame)
            copy = block.copy()
            rms, peak = rms_peak(copy.reshape(-1))
            if rms > max_rms:
                max_rms = rms
            if peak > max_peak:
                max_peak = peak
            ev = gate.feed(rms, peak)
            if not started:
                preroll.append(copy)
                if len(preroll) > gate.preroll_n:
                    preroll.pop(0)
                now = time.monotonic()
                if now - last_log >= 5.0:
                    log(
                        f"[ears] waiting for speech  rms={max_rms:.4f} peak={max_peak:.4f} "
                        f"noise={gate.noise:.4f}"
                    )
                    last_log = now
                    max_rms = 0.0
                    max_peak = 0.0
                if ev == "start":
                    started = True
                    chunks.extend(preroll)
                    hud_state("listening")
                    log("[ears] open mic — speech")
                continue
            chunks.append(copy)
            if ev == "end":
                break
    if not started or not chunks:
        return None
    return np.concatenate(chunks, axis=0)


class Mouth:
    def __init__(
        self,
        kind: str,
        voice: str = EDGE_VOICE,
        rate: str = EDGE_RATE,
        pitch: str = EDGE_PITCH,
    ):
        self.kind = kind
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self._sapi = None
        self._voice_name = ""
        self._out = None
        self._last_out = 0.0
        self._capture: list[bytes] | None = None
        self.last_start: float | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._token = 0
        self._ffmpeg: subprocess.Popen | None = None
        self.hear = True
        self._speaking = False
        if kind == "sapi":
            self._init_offline()

    def _init_offline(self) -> None:
        if WIN:
            self._init_sapi()
        else:
            self._init_espeak()

    def _init_espeak(self) -> None:
        import pyttsx3

        self._sapi = pyttsx3.init()
        self._voice_name = "espeak"
        log("[mouth] offline TTS: espeak (pyttsx3)")

    def _speak_offline(self, text: str) -> None:
        if WIN:
            if self._sapi is None:
                self._init_sapi()
            self._sapi.Speak(text, 0)
            return
        if self._sapi is None:
            self._init_espeak()
        self._sapi.say(text)
        self._sapi.runAndWait()

    def _init_sapi(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        self._sapi.Rate = 1
        self._sapi.Volume = 100
        # Prefer British Hazel over David if OneCore George cannot be bound.
        george = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_enGB_GeorgeM"
        try:
            tok = win32com.client.Dispatch("SAPI.SpObjectToken")
            tok.SetId(george)
            self._sapi.Voice = tok
            self._voice_name = tok.GetDescription()
            log(f"[mouth] Windows SAPI voice: {self._voice_name}")
            return
        except Exception:
            pass
        pick = None
        for v in self._sapi.GetVoices():
            name = v.GetDescription()
            low = name.lower()
            if "hazel" in low:
                pick, self._voice_name = v, name
                break
            if pick is None:
                pick, self._voice_name = v, name
        if pick is not None:
            self._sapi.Voice = pick
        else:
            self._voice_name = self._sapi.Voice.GetDescription()
        log(f"[mouth] Windows SAPI voice: {self._voice_name}")

    def warm(self) -> None:
        if self.kind == "none":
            return
        log("[mouth] you should hear: Jarvis online.")
        self.say("Jarvis online.")

    @property
    def busy(self) -> bool:
        return bool(self._speaking)

    def interrupt(self) -> None:
        """Cut current playback so a newer command can take the mouth."""
        self._token += 1
        self._cancel.set()
        self._speaking = False
        proc = self._ffmpeg
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def say(self, text: str) -> None:
        token = self._token
        self._cancel.clear()
        with self._lock:
            if self._token != token or self._cancel.is_set():
                return
            self._say_locked(text, token)

    def _cut(self, token: int) -> bool:
        return self._cancel.is_set() or self._token != token

    def _edge_mp3_only(self, text: str) -> None:
        """Synthesize MP3 for the phone. Do not open the laptop speakers."""
        chunks: list[bytes] = []

        async def _run() -> None:
            import edge_tts

            comm = edge_tts.Communicate(
                text, self.voice, rate=self.rate, pitch=self.pitch
            )
            async for ev in comm.stream():
                if ev["type"] == "audio":
                    chunks.append(ev["data"])

        asyncio.run(_run())
        if self._capture is not None:
            self._capture.extend(chunks)
        self.last_start = time.perf_counter()

    def _say_locked(self, text: str, token: int = 0) -> None:
        self.last_start = None
        if self.kind == "none" or not text.strip():
            return
        if self._cut(token):
            return
        self._speaking = True
        try:
            self._say_locked_body(text, token)
        finally:
            self._speaking = False

    def _say_locked_body(self, text: str, token: int) -> None:
        if not self.hear:
            log(f"[mouth] phone-only: {text}")
            try:
                self._edge_mp3_only(text)
            except Exception as exc:
                log(f"[mouth] phone capture failed ({exc})")
            return
        if self.kind == "sapi":
            log(f"[mouth] speaking: {text}")
            self.last_start = time.perf_counter()
            self._speak_offline(text)
            return
        if self.kind == "edge":
            log(f"[mouth] speaking ({self.voice}): {text}")
            try:
                asyncio.run(self._edge_play(text, token))
            except Exception as exc:
                if self._cut(token):
                    return
                if self.last_start is not None:
                    log(f"[mouth] edge playback already started ({exc})")
                    return
                log(f"[mouth] edge failed ({exc}); falling back to offline TTS")
                self.last_start = time.perf_counter()
                self._speak_offline(text)

    def close(self) -> None:
        if self._out is not None:
            try:
                self._out.stop()
                self._out.close()
            except Exception:
                pass
            self._out = None

    def _ensure_out(self) -> None:
        import numpy as np
        import sounddevice as sd

        if self._out is not None:
            return
        self._out = sd.OutputStream(
            samplerate=PLAY_RATE,
            channels=1,
            dtype="float32",
            blocksize=1024,
        )
        self._out.start()
        # Wake the device on silence so the first real word is not clipped.
        self._write_pcm(np.zeros(int(PLAY_RATE * PREROLL_S), dtype=np.float32))
        self._last_out = time.perf_counter()

    def _write_pcm(self, samples, token: int | None = None) -> None:
        import numpy as np

        x = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
        step = 2048
        for i in range(0, len(x), step):
            if token is not None and self._cut(token):
                return
            self._out.write(x[i : i + step])
        self._last_out = time.perf_counter()

    def _play_pcm(self, samples) -> None:
        import numpy as np

        self._ensure_out()
        if time.perf_counter() - self._last_out > 0.12:
            self._write_pcm(np.zeros(int(PLAY_RATE * PREROLL_S), dtype=np.float32))
        if self.last_start is None:
            self.last_start = time.perf_counter()
        self._write_pcm(samples)

    def _mp3_to_float(self, mp3: bytes):
        import numpy as np

        proc = subprocess.run(
            ffmpeg_argv(
                "-i",
                "pipe:0",
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                str(PLAY_RATE),
                "pipe:1",
            ),
            input=mp3,
            capture_output=True,
            check=True,
        )
        return np.frombuffer(proc.stdout, dtype=np.float32)

    def _feed_edge(self, text: str, proc: subprocess.Popen) -> None:
        async def _run() -> None:
            import edge_tts

            comm = edge_tts.Communicate(
                text, self.voice, rate=self.rate, pitch=self.pitch
            )
            try:
                async for ev in comm.stream():
                    if ev["type"] == "audio" and proc.stdin:
                        proc.stdin.write(ev["data"])
                        proc.stdin.flush()
                        if self._capture is not None:
                            self._capture.append(ev["data"])
            finally:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except OSError:
                    pass

        asyncio.run(_run())

    async def _edge_play(self, text: str, token: int = 0) -> None:
        import numpy as np

        proc = subprocess.Popen(
            ffmpeg_argv(
                "-i",
                "pipe:0",
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                str(PLAY_RATE),
                "pipe:1",
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._ffmpeg = proc
        threading.Thread(target=self._feed_edge, args=(text, proc), daemon=True).start()
        loop = asyncio.get_running_loop()
        self._ensure_out()
        if time.perf_counter() - self._last_out > 0.12:
            self._write_pcm(
                np.zeros(int(PLAY_RATE * PREROLL_S), dtype=np.float32), token
            )
        leftover = b""
        try:
            while True:
                if self._cut(token):
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    break
                chunk = await loop.run_in_executor(None, proc.stdout.read, 8192)
                if not chunk:
                    break
                leftover += chunk
                n = (len(leftover) // 4) * 4
                if not n:
                    continue
                samples = np.frombuffer(leftover[:n], dtype=np.float32).copy()
                leftover = leftover[n:]
                if self.last_start is None:
                    self.last_start = time.perf_counter()
                self._write_pcm(samples, token)
            if not self._cut(token):
                await loop.run_in_executor(None, proc.wait)
        finally:
            if self._ffmpeg is proc:
                self._ffmpeg = None
            if self._cut(token):
                try:
                    proc.kill()
                except OSError:
                    pass


def sentences(stream):
    buf = ""
    for chunk in stream:
        buf += chunk
        while True:
            m = SENTENCE_END.search(buf)
            if not m:
                break
            sent, buf = buf[: m.end()].strip(), buf[m.end() :]
            if sent:
                yield sent
    tail = buf.strip()
    if tail:
        yield tail


# ---- turn -----------------------------------------------------------------

def one_turn(
    brain,
    mouth: Mouth,
    text: str,
    stt_ms: int | None = None,
    session: SessionLog | None = None,
    log_text: str | None = None,
    stop=None,
) -> dict:
    hud_state("thinking", text)
    started = time.time()
    t0 = time.perf_counter()
    ttfb = None
    first_sent = None
    first_audio = None
    spoken = []
    buf = ""
    raw_all = ""
    muted = False
    cut = False
    from memory.dispatch import split_public

    def _say(sent: str) -> None:
        nonlocal first_sent, first_audio
        sent = " ".join((sent or "").split())
        if not sent:
            return
        if first_sent is None:
            first_sent = time.perf_counter()
            log(f"  [{brain.model}] first sentence {int((first_sent-t0)*1000)}ms: {sent}")
            hud_state("speaking", sent)
            mouth.say(sent)
            first_audio = mouth.last_start or time.perf_counter()
        else:
            log(f"  [{brain.model}] {sent}")
            hud_state("speaking", sent)
            mouth.say(sent)
        spoken.append(sent)

    for chunk in brain.ask(text):
        if stop is not None and stop():
            log("[desk] chat superseded")
            cut = True
            break
        now = time.perf_counter()
        if ttfb is None:
            ttfb = now
            log(f"  [{brain.model}] first token {int((now-t0)*1000)}ms {chunk!r}")
        raw_all += chunk
        if muted:
            continue
        buf += chunk
        public, priv = split_public(buf)
        if priv:
            buf = public
            muted = True
            log(f"  [{brain.model}] hands (muted)")
        while True:
            m = SENTENCE_END.search(buf)
            if not m:
                break
            sent, buf = buf[: m.end()].strip(), buf[m.end() :]
            if sent:
                _say(sent)
            if stop is not None and stop():
                log("[desk] chat superseded")
                cut = True
                buf = ""
                break
        if cut:
            break
    tail = buf.strip()
    if tail and not cut and not (stop is not None and stop()):
        _say(tail)
    hud_state("idle")
    sid = getattr(brain, "session_id", "") or ""
    if sid:
        from memory.imagine import VIDEO_EXT, library_root

        moved = rescue_session_media(HERE, sid, since=started, slug=text)
        if moved:
            dest = moved[-1]
            kind = "video" if dest.suffix.lower() in VIDEO_EXT else "still"
            line = speak_ready(
                dest,
                root=library_root(kind),
                library=library_label(kind),
            )
            log(f"[imagine] rescued {dest}")
            hud_state("speaking", line)
            mouth.say(line)
            spoken.append(line)
            hud_state("idle")
    total = time.perf_counter() - t0
    row = {
        "brain": brain.name,
        "model": brain.model,
        "stt_ms": stt_ms,
        "ttfb_ms": round(((ttfb or time.perf_counter()) - t0) * 1000) if ttfb else None,
        "first_sentence_ms": round((first_sent - t0) * 1000) if first_sent else None,
        "first_audio_ms": round((first_audio - t0) * 1000) if first_audio else None,
        "total_ms": round(total * 1000),
        "reply": raw_all or " ".join(s for s in spoken if s),
        "spoken": " ".join(s for s in spoken if s),
    }
    extra = f" stt={stt_ms}ms" if stt_ms is not None else ""
    log(
        f"  timing{extra} ttfb={row['ttfb_ms']}ms  "
        f"sentence={row['first_sentence_ms']}ms  "
        f"audio={row['first_audio_ms']}ms  total={row['total_ms']}ms"
    )
    if session is not None:
        from memory.dispatch import strip_hands as _strip_hands

        session.record(
            log_text if log_text is not None else text,
            row.get("spoken") or _strip_hands(row["reply"]),
            stt_ms=row["stt_ms"],
            ttfb_ms=row["ttfb_ms"],
            first_sentence_ms=row["first_sentence_ms"],
            first_audio_ms=row["first_audio_ms"],
            total_ms=row["total_ms"],
            model=row["model"],
            brain=row["brain"],
        )
    return row


class Desk:
    """Front desk: local intent gate, then Grok or the job board."""

    def __init__(
        self,
        brain,
        mouth: Mouth,
        board: JobBoard,
        registry: WorkshopRegistry,
        session: SessionLog | None,
        router: AgentBrain | None = None,
    ):
        self.brain = brain
        self.mouth = mouth
        self.board = board
        self.registry = registry
        self.session = session
        self.router = router
        self.pending: set[str] = set()
        self.announced: set[str] = set()
        self.progressed: set[str] = set()
        self.last_speak: str = ""
        self.gen = 0
        self._preempt = threading.Event()
        self._state = threading.Lock()
        from memory.people import load_roster, primary

        self.roster = load_roster(board.home)
        self.speaker = primary(self.roster)

    def set_speaker(self, person) -> None:
        if person is None:
            return
        self.speaker = person
        log(f"[who] {person.name} address={person.address}")

    def _vocative_line(self, line: str) -> str:
        from memory.people import with_vocative

        return with_vocative(line, self.speaker)

    def _greet_speaker(self, person, text: str, stt_ms: int | None = None) -> dict:
        self.set_speaker(person)
        from memory.people import vocative

        v = vocative(person)
        if v.lower() == "sir":
            line = "Yes, sir."
        else:
            line = f"Hello {v}."
        hud_state("speaking", line)
        self.mouth.say(line)
        hud_state("idle")
        if self.session is not None:
            self.session.record(
                text, line, stt_ms=stt_ms, brain="who", model=person.slug
            )
        return {"reply": line, "brain": "who", "model": person.slug, "stt_ms": stt_ms}

    def _claim_speak(self, job_id: str) -> bool:
        """First caller may speak this job. Wait vs drain must not both talk."""
        with self._state:
            if job_id in self.announced:
                return False
            self.announced.add(job_id)
            self.pending.discard(job_id)
            return True

    def preempt(self) -> None:
        """A newer line arrived. Cut speech; in-flight work must not keep talking."""
        self._preempt.set()
        self.mouth.interrupt()
        log("[desk] preempt")

    def _preempted(self) -> bool:
        return self._preempt.is_set()

    def _stale(self, snap: dict) -> bool:
        g = snap.get("gen")
        if g is None:
            return True
        try:
            return int(g) != self.gen
        except (TypeError, ValueError):
            return True

    def hush(self, text: str, stt_ms: int | None = None) -> dict:
        self.gen += 1
        self.mouth.interrupt()
        self._preempt.set()
        with self._state:
            for job_id in list(self.pending):
                self.announced.add(job_id)
        log("[desk] hush — older jobs stay silent")
        clear_replace(self.board.home)
        if self.session is not None:
            self.session.record(
                text, "", stt_ms=stt_ms, brain="jobs", model="hush"
            )
        hud_state("idle")
        return {"reply": "", "brain": "hush"}

    def _route_run(self, asked: str) -> str:
        t0 = time.perf_counter()
        out = ""
        try:
            if self.router is not None and self.router.warm:
                out = self.router.complete(asked, timeout=ROUTE_TIMEOUT_S)
            else:
                from memory.grokrun import run_prompt

                out = run_prompt(
                    asked,
                    grok=GROK,
                    model=getattr(self.brain, "model", None) or "grok-4.6",
                    system=ROUTE_SYSTEM,
                    web=False,
                    max_turns=1,
                    timeout=ROUTE_TIMEOUT_S,
                )
        except Exception as exc:
            log(f"[route] failed ({exc})")
            out = ""
        log(f"[route] {int((time.perf_counter() - t0) * 1000)}ms {out[:120]!r}")
        return out or '{"caps":["chat"]}'

    def utter(self, text: str, stt_ms: int | None = None) -> dict:
        return self.handle_batch([(text, stt_ms)])

    def handle_batch(self, items: list[tuple[str, int | None]]) -> dict:
        """Answer only the latest user line. Older queued lines are dropped."""
        items = latest_wins(items)
        texts = [" ".join((t or "").split()) for t, _ in items]
        texts = [t for t in texts if t and t not in ("__quit__", "__quiet__")]
        if not texts:
            return {"reply": ""}
        stt_ms = next((s for _, s in items if s is not None), None)
        text = texts[-1]
        self._preempt.clear()
        model = getattr(self.brain, "model", None) or "grok-4.6"
        t_route = time.perf_counter()
        resolved = resolve_intents(
            text,
            caps=self.registry.caps(),
            roster=roster_card(self.board.home),
            home=self.board.home,
        )
        log(
            f"[route] {int((time.perf_counter() - t_route) * 1000)}ms "
            f"{text[:40]!r} -> {[getattr(i, 'cap', None) or getattr(i, 'kind', None) for i in resolved]!r}"
        )
        if any(getattr(i, "kind", "") == HUSH.kind for i in resolved):
            return self.hush(text, stt_ms=stt_ms)
        from memory.people import match_intro

        intro = match_intro(text, self.roster)
        if intro is not None:
            return self._greet_speaker(intro, text, stt_ms=stt_ms)
        if self.registry.has_cap("home"):
            from memory.ha import is_house_followup, pending_clarify

            if pending_confirm(self.board.home):
                resolved = [
                    HOME if (is_yes(text) or is_no(text)) else i for i in resolved
                ]
            if pending_clarify(self.board.home):
                resolved = [
                    HOME if is_house_followup(text) else i for i in resolved
                ]
        if self._preempted():
            log("[desk] superseded before acting")
            return {"reply": ""}
        waiting = pending_replace(self.board.home)
        if (
            waiting
            and not pending_confirm(self.board.home)
            and (is_yes(text) or is_no(text))
        ):
            return self._replace_answer(text, waiting, stt_ms=stt_ms)
        kinds = [getattr(i, "kind", "") for i in resolved]
        if kinds and all(k == "status" for k in kinds):
            return self.report_work(text, stt_ms=stt_ms)
        if self.pending and is_ping(text) and not any(getattr(i, "cap", None) for i in resolved):
            return self.report_work(text, stt_ms=stt_ms)
        jobs_now = [i for i in resolved if getattr(i, "cap", None)]
        if jobs_now:
            busy = contended(self.board, self.registry, jobs_now[0].cap)
            if busy:
                return self._ask_replace(text, jobs_now[0], busy, stt_ms=stt_ms)
        self.gen += 1
        my_gen = self.gen
        spoken: list[str] = []
        extra: dict = {"gen": my_gen}
        if self.session is not None:
            extra["session"] = self.session.session_id
        if self.speaker is not None:
            extra["who"] = self.speaker.name
            extra["address"] = self.speaker.address
        jobs = [(text, i) for i in resolved if getattr(i, "cap", None)]
        chat = [
            i
            for i in resolved
            if not getattr(i, "cap", None) and getattr(i, "kind", "") not in ("status", "hush")
        ]
        for _, intent in jobs:
            if self._preempted():
                log("[desk] superseded during jobs")
                return {"reply": " ".join(s for s in spoken if s), "brain": "batch"}
            spoken.extend(self._start_job(text, stt_ms, extra, intent=intent))
        if chat and not jobs:
            if self._preempted():
                return {"reply": ""}
            from memory.working import desk_prefix

            prompt = text
            pre = desk_prefix(self.board.home, person=self.speaker)
            if pre:
                who = getattr(self.speaker, "name", None) or "They"
                prompt = pre + f"\n\n{who}: " + prompt
            row = one_turn(
                self.brain,
                self.mouth,
                prompt,
                stt_ms=stt_ms,
                session=self.session,
                log_text=text,
                stop=self._preempted,
            )
            raw_reply = str(row.get("reply") or "")
            from memory.dispatch import intents_from_mouth, strip_hands

            heard = str(row.get("spoken") or "").strip() or strip_hands(raw_reply)
            spoken.append(heard)
            for task, intent in intents_from_mouth(raw_reply, text):
                log(f"[desk] mouth asked hands cap={intent.cap} {task[:80]!r}")
                spoken.extend(
                    self._start_job(
                        task,
                        stt_ms,
                        extra,
                        intent=intent,
                        speak_ack=False,
                    )
                )
        hud_state("idle")
        return {"reply": " ".join(s for s in spoken if s), "brain": "batch"}

    def _ask_replace(self, text: str, intent, busy: list[dict], stt_ms: int | None):
        for snap in busy:
            jid = str(snap.get("id") or "")
            if jid:
                self.announced.add(jid)
        line = ask_replace(
            self.board.home,
            current=busy,
            next_prompt=text,
            next_cap=str(intent.cap or ""),
        )
        log(f"[jobs] confirm replace {line!r}")
        hud_state("speaking", line)
        self.mouth.say(line)
        hud_state("idle")
        if self.session is not None:
            self.session.record(
                text, line, stt_ms=stt_ms, brain="jobs", model="replace"
            )
        return {"reply": line, "brain": "jobs", "model": "replace", "stt_ms": stt_ms}

    def _replace_answer(self, text: str, waiting: dict, stt_ms: int | None):
        current = str(waiting.get("current_label") or "that")
        if is_no(text):
            for jid in waiting.get("cancel_ids") or []:
                self.announced.discard(str(jid))
            clear_replace(self.board.home)
            line = keep_line(current)
            hud_state("speaking", line)
            self.mouth.say(line)
            hud_state("idle")
            if self.session is not None:
                self.session.record(
                    text, line, stt_ms=stt_ms, brain="jobs", model="replace"
                )
            spoken = self.drain()
            if spoken:
                line = line + " " + spoken[-1]
            return {"reply": line, "brain": "jobs", "model": "replace", "stt_ms": stt_ms}
        self.gen += 1
        extra: dict = {"gen": self.gen}
        if self.session is not None:
            extra["session"] = self.session.session_id
        if self.speaker is not None:
            extra["who"] = self.speaker.name
            extra["address"] = self.speaker.address
        for jid in waiting.get("cancel_ids") or []:
            jid = str(jid)
            self.board.cancel(jid, reason="replaced")
            self.announced.add(jid)
            self.pending.discard(jid)
        clear_replace(self.board.home)
        nxt = str(waiting.get("next_prompt") or text)
        cap = str(waiting.get("next_cap") or "")
        intent = intent_for_cap(cap, nxt)
        spoken = self._start_job(nxt, stt_ms, extra, intent=intent)
        return {
            "reply": " ".join(s for s in spoken if s),
            "brain": "jobs",
            "model": "replace",
            "stt_ms": stt_ms,
        }

    def _start_job(
        self,
        text: str,
        stt_ms: int | None,
        extra: dict,
        intent=None,
        speak_ack: bool = True,
    ) -> list[str]:
        hit = maybe_enqueue(
            text,
            self.board,
            self.registry,
            extra=extra or None,
            intent=intent,
            grok=GROK,
            model=getattr(self.brain, "model", None) or "grok-4.6",
        )
        if hit is None:
            missed = intent if intent is not None else classify(text)
            line = self._vocative_line("I haven't got hands for that yet, sir.")
            log(f"[jobs] {getattr(missed, 'cap', None)} missed — workshop offline or cap down")
            hud_state("speaking", line)
            self.mouth.say(line)
            if self.session is not None:
                self.session.record(
                    text,
                    line,
                    stt_ms=stt_ms,
                    brain="jobs",
                    model=str(getattr(missed, "cap", None) or ""),
                )
            return [line]
        intent, job_id = hit
        self.pending.add(job_id)
        log(f"[jobs] {job_id} cap={intent.cap} gen={extra.get('gen')} {text!r}")
        if self._preempted():
            return []
        ack = self._vocative_line(intent.ack) if speak_ack else ""
        if ack:
            hud_state("speaking", ack)
            self.mouth.say(ack)
            if self.session is not None:
                self.session.record(
                    text, ack, stt_ms=stt_ms, brain="jobs", model=intent.cap
                )
        if self._preempted():
            return [ack] if ack else []
        if intent.wait_s > 0:
            snap = self.board.wait(
                job_id, timeout=intent.wait_s, abort=self._preempted
            )
            if self._preempted():
                return [ack]
            if snap and snap.get("event") in ("done", "error"):
                if not self._claim_speak(job_id):
                    return [ack]
                if self._stale(snap):
                    return [ack]
                line = self._speak_line(snap)
                if line:
                    self.last_speak = line
                    hud_state("speaking", line)
                    self.mouth.say(line)
                    if self.session is not None:
                        self.session.record(
                            f"[job {intent.cap}]",
                            line,
                            brain="jobs",
                            model=intent.cap,
                        )
                    return [ack, line]
            log(f"[jobs] {job_id} still running after {intent.wait_s:.0f}s")
        return [ack]

    def report_work(self, text: str, stt_ms: int | None = None) -> dict:
        """Finished jobs speak immediately. Otherwise the mouth answers from the brief."""
        spoken = self.drain()
        if spoken:
            line = spoken[-1]
            if self.session is not None:
                self.session.record(
                    text, line, stt_ms=stt_ms, brain="jobs", model="status"
                )
            return {
                "brain": "jobs",
                "model": "status",
                "stt_ms": stt_ms,
                "reply": line,
            }
        from memory.working import desk_prefix

        prompt = text
        pre = desk_prefix(self.board.home, person=self.speaker)
        if pre:
            who = getattr(self.speaker, "name", None) or "They"
            prompt = pre + f"\n\n{who}: " + prompt
        row = one_turn(
            self.brain,
            self.mouth,
            prompt,
            stt_ms=stt_ms,
            session=self.session,
            log_text=text,
            stop=self._preempted,
        )
        return row

    def drain(self) -> list[str]:
        to_say: list[tuple[str, str, dict]] = []
        spoken: list[str] = []
        with self._state:
            for job_id in list(self.pending):
                snap = self.board.snapshot(job_id)
                ev = snap.get("event")
                if ev not in ("done", "error"):
                    continue
                if job_id in self.announced:
                    self.pending.discard(job_id)
                    continue
                to_say.append(("done", job_id, snap))
        for kind, job_id, snap in to_say:
            if kind == "done" and not self._claim_speak(job_id):
                continue
            if self._preempted() or self._stale(snap):
                log(f"[jobs] {job_id} skip speak stale/preempt gen={snap.get('gen')}")
                continue
            line = self._speak_line(snap)
            if not line:
                log(f"[jobs] {job_id} {snap.get('event')}")
                continue
            self.last_speak = line
            log(f"[jobs] {job_id} {snap.get('event')}: {line}")
            hud_state("speaking", line)
            self.mouth.say(line)
            hud_state("idle")
            spoken.append(line)
            if self.session is not None:
                self.session.record(
                    f"[job {snap.get('cap')}]",
                    line,
                    brain="jobs",
                    model=str(snap.get("cap") or ""),
                )
        if not self._preempted():
            self._speak_due_reminders()
        return spoken

    def _speak_due_reminders(self) -> None:
        from memory.reminders import reminder_norm

        seen: set[str] = set()
        last = reminder_norm(self.last_speak)
        if last:
            seen.add(last)
        for line in take_due(self.board.home):
            key = reminder_norm(line)
            if key in seen:
                log(f"[remind] skip duplicate {line!r}")
                continue
            seen.add(key)
            log(f"[remind] {line}")
            hud_state("speaking", line)
            self.mouth.say(line)
            self.last_speak = line
            hud_state("idle")
            if self.session is not None:
                self.session.record("[reminder]", line, brain="jobs", model="remind")

    @staticmethod
    def _speak_line(snap: dict) -> str:
        if snap.get("event") == "error":
            return "I couldn't finish that, sir."
        from memory.dispatch import audible

        return audible(str(snap.get("speak") or ""))

    @staticmethod
    def _job_age_s(snap: dict) -> float:
        ts = str(snap.get("ts") or "")
        try:
            then = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            return max(0.0, (datetime.now(timezone.utc) - then).total_seconds())
        except ValueError:
            return 0.0


def wait_home(held_flag: dict) -> None:
    from pynput import keyboard

    def on_press(key):
        if key == keyboard.Key.home:
            held_flag["down"] = True
            return False
        if key == keyboard.Key.esc:
            held_flag["quit"] = True
            return False

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


def home_held() -> bool:
    from pynput import keyboard

    # pynput has no simple poll; we track via a shared listener started once
    return bool(getattr(home_held, "down", False))


def start_ptt_listener(state: dict) -> None:
    from pynput import keyboard

    def on_press(key):
        if key == keyboard.Key.home:
            state["home_at"] = time.monotonic()
            state["down"] = True
        if key == keyboard.Key.esc:
            state["quit"] = True

    def on_release(key):
        if key != keyboard.Key.home:
            return

        def _up() -> None:
            # X11 key-repeat can emit press/release pairs while still holding.
            time.sleep(0.08)
            if time.monotonic() - float(state.get("home_at") or 0) >= 0.07:
                state["down"] = False

        threading.Thread(target=_up, daemon=True).start()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    state["listener"] = listener


def _silence_tty():
    """Stop Home/arrows echoing into the Talk terminal. Keep Ctrl-C."""
    if sys.platform == "win32" or not sys.stdin.isatty():
        return None
    try:
        import termios
    except ImportError:
        return None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = list(old)
    new[3] = new[3] & ~(termios.ECHO | termios.ECHONL | termios.ICANON)
    termios.tcsetattr(fd, termios.TCSANOW, new)
    return old


def _restore_tty(old) -> None:
    if old is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, old)
    except Exception:
        pass


def _swallow_keys(stop: threading.Event) -> None:
    """Discard Home escape sequences so they never print or queue."""
    if sys.platform == "win32":
        try:
            import msvcrt
        except ImportError:
            return
        while not stop.is_set():
            if msvcrt.kbhit():
                msvcrt.getch()
            else:
                time.sleep(0.05)
        return
    if not sys.stdin.isatty():
        return
    import select

    fd = sys.stdin.fileno()
    while not stop.is_set():
        try:
            ready, _, _ = select.select([fd], [], [], 0.1)
        except (OSError, ValueError):
            return
        if not ready:
            continue
        try:
            os.read(fd, 4096)
        except OSError:
            return


def _drain_loop(desk: Desk, stop: threading.Event) -> None:
    while not stop.wait(0.4):
        try:
            desk.drain()
        except Exception as exc:
            log(f"[jobs] drain {exc}")


def run_talk(
    desk: Desk, stt: str, listen: bool = False, wake: str | None = None
) -> None:
    if stt == "none":
        log("Talk: type a line. Esc or Ctrl-C quits.")
    elif wake:
        log(
            f"Talk: say '{wake}' then the request. Home still PTT (no wake needed). "
            "Esc or Ctrl-C quits."
        )
    elif listen:
        log(
            "Talk: always-on mic (speak, then pause). Home still works as PTT. "
            "Esc or Ctrl-C quits."
        )
    else:
        log("Talk: hold Home, speak, release. Esc or Ctrl-C quits. Type if --stt none.")
    hud_state("idle")
    stop = threading.Event()
    threading.Thread(target=_drain_loop, args=(desk, stop), daemon=True).start()
    tty = None
    if stt != "none":
        tty = _silence_tty()
        threading.Thread(target=_swallow_keys, args=(stop,), daemon=True).start()
    try:
        _run_talk_loop(desk, stt, listen=listen, wake=wake)
    finally:
        stop.set()
        _restore_tty(tty)


def _take_batch(inbox: queue.Queue, timeout: float) -> list[tuple[str, int | None]]:
    try:
        first = inbox.get(timeout=timeout)
    except queue.Empty:
        return []
    out = [first]
    while True:
        try:
            out.append(inbox.get_nowait())
        except queue.Empty:
            break
    return out


def _typed_reader(
    inbox: queue.Queue, quit_ev: threading.Event, on_line=None
) -> None:
    while not quit_ev.is_set():
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            inbox.put(("__quit__", None))
            return
        if not line:
            continue
        if line.lower() in ("q", "quit", "exit"):
            inbox.put(("__quit__", None))
            return
        inbox.put((line, None))
        if on_line is not None:
            on_line()


def _ptt_reader(
    state: dict, inbox: queue.Queue, quit_ev: threading.Event, on_line=None
) -> None:
    while not quit_ev.is_set() and not state.get("quit"):
        if not state.get("down"):
            time.sleep(0.02)
            continue
        hud_state("listening")
        log("[ptt] recording...")
        t0 = time.perf_counter()
        pcm = record_held(lambda: bool(state.get("down")) and not quit_ev.is_set())
        if pcm is None or getattr(pcm, "size", 0) < 1600:
            log("[ptt] too short")
            hud_state("idle")
            continue
        text, note = transcribe(pcm)
        stt_ms = round((time.perf_counter() - t0) * 1000)
        log(f"[you] {text!r}  (stt {stt_ms}ms {note})")
        if not text:
            if "quiet" in note:
                log("[ears] too quiet — lid closed or wrong mic? USB or phone HUD is better.")
                inbox.put(("__quiet__", None))
            hud_state("idle")
            continue
        inbox.put((text, stt_ms))
        if on_line is not None:
            on_line()


def _open_mic_reader(
    state: dict,
    inbox: queue.Queue,
    quit_ev: threading.Event,
    desk: Desk,
    on_line=None,
    wake: str | None = None,
) -> None:
    cool = False
    while not quit_ev.is_set() and not state.get("quit"):
        if desk.mouth.busy and not state.get("down"):
            cool = True
            time.sleep(0.05)
            continue
        if cool and not state.get("down"):
            time.sleep(0.35)
            cool = False
            continue
        hud_state("idle")
        t0 = time.perf_counter()
        used_ptt = False
        if state.get("down"):
            used_ptt = True
            log("[ptt] recording...")
            pcm = record_held(lambda: bool(state.get("down")) and not quit_ev.is_set())
        else:
            pcm = record_utterance(
                lambda: quit_ev.is_set()
                or state.get("quit")
                or (desk.mouth.busy and not state.get("down"))
                or bool(state.get("down"))
            )
            if state.get("down"):
                continue
        if pcm is None or getattr(pcm, "size", 0) < 1600:
            hud_state("idle")
            continue
        text, note = transcribe(pcm)
        stt_ms = round((time.perf_counter() - t0) * 1000)
        log(f"[you] {text!r}  (stt {stt_ms}ms {note})")
        if not text:
            if "quiet" in note:
                log("[ears] too quiet — lid closed or wrong mic? USB or phone HUD is better.")
                inbox.put(("__quiet__", None))
            hud_state("idle")
            continue
        if wake and not used_ptt:
            rest = after_wake(text, wake)
            if rest is None:
                log(f"[ears] no wake '{wake}' — ignored")
                hud_state("idle")
                continue
            if not rest:
                text = "hello"
            else:
                text = rest
            log(f"[ears] wake → {text!r}")
        inbox.put((text, stt_ms))
        if on_line is not None:
            on_line()


def _run_talk_loop(
    desk: Desk, stt: str, listen: bool = False, wake: str | None = None
) -> None:
    inbox: queue.Queue = queue.Queue()
    quit_ev = threading.Event()
    if stt == "none":
        threading.Thread(
            target=_typed_reader, args=(inbox, quit_ev, desk.preempt), daemon=True
        ).start()
        while not quit_ev.is_set():
            batch = latest_wins(_take_batch(inbox, 0.2))
            if not batch:
                continue
            if any(t == "__quit__" for t, _ in batch):
                rest = [(t, s) for t, s in batch if t not in ("__quit__", "__quiet__")]
                if rest:
                    desk.handle_batch(rest)
                break
            quiet = any(t == "__quiet__" for t, _ in batch)
            rest = [(t, s) for t, s in batch if t not in ("__quit__", "__quiet__")]
            if quiet and not rest:
                desk.mouth.say(desk._vocative_line("I didn't catch that, sir."))
                hud_state("idle")
                continue
            if rest:
                desk.handle_batch(rest)
                hud_state("idle")
        quit_ev.set()
        return
    state = {"down": False, "quit": False}
    start_ptt_listener(state)
    open_mic = listen or bool(wake)
    if open_mic:
        threading.Thread(
            target=_open_mic_reader,
            kwargs={
                "state": state,
                "inbox": inbox,
                "quit_ev": quit_ev,
                "desk": desk,
                "on_line": desk.preempt,
                "wake": wake,
            },
            daemon=True,
        ).start()
        if wake:
            log(
                f"listening for '{wake}'. Home still works. "
                "iPhone HUD is still hold-to-talk."
            )
        else:
            log("listening (open mic). Home still works. iPhone HUD is still hold-to-talk.")
    else:
        threading.Thread(
            target=_ptt_reader, args=(state, inbox, quit_ev, desk.preempt), daemon=True
        ).start()
        log("waiting for Home (or iPhone on the PC hotspot)...")
    while not state["quit"] and not quit_ev.is_set():
        try:
            job = incoming_jobs.get_nowait()
        except queue.Empty:
            job = None
        if job:
            desk.preempt()
            if getattr(job, "kind", "") == "glance":
                handle_glance_job(job, desk)
            else:
                handle_phone_job(job, desk)
            continue
        batch = latest_wins(_take_batch(inbox, 0.05))
        if not batch:
            continue
        rest = [(t, s) for t, s in batch if t != "__quiet__"]
        if any(t == "__quiet__" for t, _ in batch) and not rest:
            desk.mouth.say(desk._vocative_line("I didn't catch that, sir."))
            hud_state("idle")
            continue
        if rest:
            desk.handle_batch(rest)
            hud_state("idle")
    quit_ev.set()
    log("bye")


def run_bench(brain, mouth: Mouth, rounds: int) -> None:
    log(f"warmup on {brain.name}/{brain.model} ...")
    one_turn(brain, mouth, "Warmup ping. Reply with the single word ready.")
    log(f"--- {rounds} timed hellos ---")
    rows = []
    for i in range(rounds):
        log(f"hello {i+1}/{rounds}")
        rows.append(one_turn(brain, mouth, HELLO))
        time.sleep(0.3)
    ttfbs = [r["ttfb_ms"] for r in rows if r["ttfb_ms"] is not None]
    auds = [r["first_audio_ms"] for r in rows if r["first_audio_ms"] is not None]
    log("\n=== bench ===")
    log(f"brain={brain.name} model={brain.model} tts={mouth.kind} rounds={rounds}")
    if ttfbs:
        log(f"ttfb ms: {ttfbs}  avg={sum(ttfbs)//len(ttfbs)}")
    if auds:
        log(f"first_audio ms: {auds}  avg={sum(auds)//len(auds)}")
    else:
        log("first_audio: n/a (--tts none)")


def parse_args():
    p = argparse.ArgumentParser(description="Jarvis receptionist latency spike")
    p.add_argument("--brain", choices=("agent", "cli"), default="agent")
    p.add_argument("--model", choices=("grok-4.6", "grok-4.5"), default="grok-4.6")
    p.add_argument("--stt", choices=("none", "tiny", "base", "small"), default="none")
    p.add_argument(
        "--listen",
        action="store_true",
        help="always-on mic: speak, pause. Home still works as PTT. Needs --stt.",
    )
    p.add_argument(
        "--wake",
        nargs="?",
        const="jarvis",
        default=None,
        metavar="WORD",
        help="open mic, but only act if the clip starts with WORD (default jarvis). Implies --listen.",
    )
    p.add_argument(
        "--mic",
        default=None,
        help="input device index or name substring (Focusrite, Scarlett, …)",
    )
    p.add_argument("--list-mics", action="store_true", help="print capture devices and exit")
    p.add_argument("--tts", choices=("none", "sapi", "edge"), default="none")
    p.add_argument(
        "--voice",
        default=EDGE_VOICE,
        help="edge-tts voice id (default en-GB-ThomasNeural)",
    )
    p.add_argument("--rate", default=EDGE_RATE, help="edge-tts rate, e.g. -2%%")
    p.add_argument("--pitch", default=EDGE_PITCH, help="edge-tts pitch, e.g. +4Hz")
    p.add_argument("--bench", action="store_true", help="time typed hellos, no mic")
    p.add_argument("--no-hud", action="store_true", help="do not open the Iron Man HUD")
    p.add_argument(
        "--no-workshop",
        action="store_true",
        help="do not spawn host or shell workshops (desk only)",
    )
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument(
        "--data-dir",
        default=None,
        help="JARVIS_HOME (default: $JARVIS_HOME or ~/.jarvis)",
    )
    return p.parse_args()


def open_memory(data_dir: str | None) -> tuple[JarvisHome, str, JobBoard, WorkshopRegistry]:
    home = JarvisHome.discover(data_dir)
    home.ensure()
    board = JobBoard(home)
    registry = WorkshopRegistry(home)
    notes = load_boot_notes(home)
    prompt = build_system_prompt(notes, workers=registry.prompt_line())
    log(f"[memory] home={home.root} boot={len(prompt)} chars")
    return home, prompt, board, registry


def _wait_for_worker(registry: WorkshopRegistry, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if registry.live():
            return True
        time.sleep(0.05)
    return False


def _stop_worker(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if WIN:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            pass
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    except KeyboardInterrupt:
        proc.kill()


def _setup_ears(home: JarvisHome, args) -> None:
    global _mic, _stt_prompt, _stt_hotwords
    _stt_prompt, _stt_hotwords = vocabulary(home)
    if args.stt == "none":
        return
    want = args.mic or load_mic_pref(home)
    try:
        rows = list_inputs()
    except Exception as exc:
        log(f"[ears] could not list mics ({exc})")
        rows = []
    chosen = pick_input(want=want) if rows else None
    _mic = chosen
    if rows:
        log("[ears] capture devices (* in use):")
        log(format_inputs(rows, chosen))
    if chosen:
        log(f"[ears] mic={chosen['index']} {chosen['name']} ({chosen['kind']})")
        if chosen["kind"] == "builtin":
            log(
                "[ears] built-in mic — lid-closed laptops mangle names. "
                "Plug in the Focusrite/USB mic, or use the phone HUD. "
                "Pin one with ~/.jarvis/mic.json {\"device\": \"Focusrite\"}"
            )
    else:
        log("[ears] no capture device listed; sounddevice default")
    log(f"[ears] whisper vocab: {_stt_prompt[:120]}")


def main() -> None:
    args = parse_args()
    if args.list_mics:
        rows = list_inputs()
        chosen = pick_input()
        print(format_inputs(rows, chosen) or "no input devices")
        return
    if not GROK.is_file():
        sys.exit(f"grok CLI missing: {GROK}  (install Grok Build and run grok login)")
    home = None
    session = None
    board = None
    desk = None
    workshop_procs: list[subprocess.Popen] = []
    router = None
    _ignore_console_ctrl(True)
    try:
        take_lock()
        home, prompt, board, registry = open_memory(args.data_dir)
        warn = home.take_lease(os.getpid())
        if warn:
            log(f"[memory] {warn}")
        _setup_ears(home, args)
        if not args.no_workshop and not args.bench:
            try:
                workshop_procs.append(
                    spawn_host_workshop(
                        home, grok=GROK, model=args.model, parent_pid=os.getpid()
                    )
                )
            except OSError as exc:
                log(f"[workshop] failed to start: {exc}")
            try:
                workshop_procs.append(
                    spawn_shell_workshop(
                        home, grok=GROK, model=args.model, parent_pid=os.getpid()
                    )
                )
            except OSError as exc:
                log(f"[workshop] shell failed to start: {exc}")
            alive = [p for p in workshop_procs if p.poll() is None]
            dead = len(workshop_procs) - len(alive)
            workshop_procs = alive
            if dead:
                log("[workshop] a worker exited immediately")
            if workshop_procs:
                time.sleep(0.35)
                workshop_procs = [p for p in workshop_procs if p.poll() is None]
            if workshop_procs and _wait_for_worker(registry):
                log(f"[workshop] live caps={','.join(registry.caps())}")
                prompt = build_system_prompt(
                    load_boot_notes(home), workers=registry.prompt_line()
                )
            elif workshop_procs:
                log("[workshop] no heartbeat yet — jobs will still dispatch")
            log("[talk] starting HUD and brain — leave this window open")
        _ignore_console_ctrl(False)
        if not args.no_hud and not args.bench:
            start_hud(open_browser=True)
            hud_state("idle")
        brain = (
            AgentBrain(args.model, system_prompt=prompt)
            if args.brain == "agent"
            else CliBrain(args.model, system_prompt=prompt)
        )
        router = None
        mouth = Mouth(args.tts, voice=args.voice, rate=args.rate, pitch=args.pitch)
        log(
            f"starting brain={args.brain} model={args.model} stt={args.stt} "
            f"tts={args.tts}"
            + (f" voice={args.voice}" if args.tts == "edge" else "")
            + "  (one mouth only — old Talk windows are closed)"
        )
        t0 = time.perf_counter()
        brain.start()
        log(f"[brain] up in {int((time.perf_counter()-t0)*1000)}ms")
        ping = threading.Thread(target=brain.warmup, daemon=True)
        ping.start()
        if args.stt != "none":
            warm_stt(args.stt)
        if args.tts != "none":
            t1 = time.perf_counter()
            mouth.warm()
            log(f"[mouth] warm in {int((time.perf_counter()-t1)*1000)}ms")
        ping.join(timeout=90)
        if ping.is_alive():
            log("[brain] warmup still running — first hello may be slower")
        if args.bench:
            run_bench(brain, mouth, args.rounds)
        else:
            session = SessionLog.start(home)
            desk = Desk(brain, mouth, board, registry, session, router=router)
            wake = (args.wake or "").strip() or None
            if args.stt == "none":
                wake = None
            listen = bool((args.listen or wake) and args.stt != "none")
            run_talk(desk, args.stt, listen=listen, wake=wake)
    except KeyboardInterrupt:
        log("[talk] stopped")
    finally:
        _ignore_console_ctrl(False)
        if session is not None and board is not None:
            session.close()
            dest = distill_session(session, board=board)
            if dest:
                log(f"[memory] daily note {dest}")
            worker_alive = any(p.poll() is None for p in workshop_procs)
            if worker_alive and board.active():
                log("[jobs] waiting on workshop to finish")
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline and board.active():
                    time.sleep(0.4)
            leftover = board.runnable(list(HOST_CAPS))
            if leftover and home is not None:
                log(f"[jobs] finishing {len(leftover)} leftover job(s) in-process")
                try:
                    n = drain_runnable(home, grok=GROK, model=args.model)
                    log(f"[jobs] in-process finished {n}")
                except Exception as exc:
                    log(f"[jobs] in-process finish failed: {exc}")
            if desk is not None:
                for job_id in list(desk.pending):
                    st = board.latest_status(job_id)
                    log(f"[jobs] {job_id} {st}")
        for proc in workshop_procs:
            _stop_worker(proc)
        if home is not None:
            home.drop_lease(os.getpid())
        try:
            brain.close()
        except NameError:
            pass
        try:
            if router is not None:
                router.close()
        except NameError:
            pass
        try:
            mouth.close()
        except NameError:
            pass
        stop_hud()
        drop_lock()


if __name__ == "__main__":
    main()
