"""Jarvis receptionist latency spike.

Hold Home to talk, or type if --stt none.
Times every stage. Swap --brain / --model / --stt / --tts.

Examples:
  .venv\\Scripts\\python talk.py --bench
  .venv\\Scripts\\python talk.py --brain agent --model grok-4.6 --stt none --tts sapi
  .venv\\Scripts\\python talk.py --brain agent --model grok-4.6 --stt tiny --tts sapi
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
from memory.ears import (  # noqa: E402
    format_inputs,
    list_inputs,
    load_mic_pref,
    pick_input,
    transcribe_pcm,
    vocabulary,
)
from memory.home import JarvisHome  # noqa: E402
from memory.intent import maybe_enqueue  # noqa: E402
from memory.jobs import JobBoard  # noqa: E402
from memory.prompt import SPEECH_RULES, build_system_prompt, load_boot_notes  # noqa: E402
from memory.session import SessionLog  # noqa: E402
from memory.reminders import take_due  # noqa: E402
from memory.worker import HOST_CAPS, drain_runnable, spawn_host_workshop  # noqa: E402
from memory.workshops import WorkshopRegistry  # noqa: E402
WIN = sys.platform == "win32"
EDGE_VOICE = "en-GB-RyanNeural"
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
NO_TOOLS = (
    "Agent,run_terminal_cmd,read_file,search_replace,web_search,web_fetch,"
    "grep,list_dir,glob"
)


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


def log(msg: str) -> None:
    print(msg, flush=True)


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
    if WIN:
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
            "low",
            "--cwd",
            str(HERE),
            "--always-approve",
            "--no-subagents",
            "--disable-web-search",
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

    def __init__(self, model: str, system_prompt: str = SPEECH_RULES):
        self.model = model
        self.system_prompt = system_prompt
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._updates: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self.session_id = ""
        self.warm = False

    def start(self) -> None:
        slim = [
            "--disable-web-search",
            "--no-subagents",
            "--disallowed-tools",
            NO_TOOLS,
        ]
        base = [
            "agent",
            "-m",
            self.model,
            "--effort",
            "low",
            "--always-approve",
            "--no-leader",
            "stdio",
        ]
        err = (HERE / "agent.stderr.log").open("ab")
        init = {
            "protocolVersion": 1,
            "clientInfo": {"name": "jarvis-receptionist", "version": "0"},
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": True,
            },
        }
        self.proc = subprocess.Popen(
            [str(GROK), *slim, *base],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err,
            cwd=str(HERE),
            bufsize=0,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        time.sleep(0.25)
        try:
            if self.proc.poll() is not None:
                raise RuntimeError("slim grok agent exited")
            self._rpc("initialize", init)
        except Exception:
            log("[brain] slim flags rejected, retrying full agent")
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = subprocess.Popen(
                [str(GROK), *base],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=err,
                cwd=str(HERE),
                bufsize=0,
            )
            threading.Thread(target=self._reader, daemon=True).start()
            self._rpc("initialize", init)
        result = self._rpc(
            "session/new",
            {
                "cwd": str(HERE),
                "mcpServers": [],
                "_meta": {
                    "yoloMode": True,
                    "systemPromptOverride": self.system_prompt,
                },
            },
        )
        self.session_id = result.get("sessionId") or result.get("session_id") or ""
        if not self.session_id:
            raise RuntimeError(f"session/new failed: {result!r}")
        self.warm = True

    def warmup(self) -> None:
        log("[brain] warming prompt cache...")
        t0 = time.perf_counter()
        for _ in self.ask("Warmup ping. Reply with the single word ready."):
            pass
        log(f"[brain] cache hot in {int((time.perf_counter()-t0)*1000)}ms")

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

    def ask(self, text: str):
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
        while True:
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

    if FFMPEG is None:
        raise RuntimeError("ffmpeg.exe not found")
    suffix = ".mp4"
    low = (content_type or "").lower()
    if "webm" in low:
        suffix = ".webm"
    elif "wav" in low:
        suffix = ".wav"
    elif "mpeg" in low or "mp3" in low:
        suffix = ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        path = f.name
    try:
        proc = subprocess.run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError("could not decode phone audio")
    return pcm.astype(np.float32) / 32768.0


def handle_phone_job(job, mouth: Mouth, utter) -> None:
    try:
        hud_state("listening")
        pcm = decode_upload(job.data, job.content_type)
        if getattr(pcm, "size", 0) < 1600:
            job.finish(error="too short")
            hud_state("idle")
            return
        t0 = time.perf_counter()
        text, note = transcribe(pcm)
        stt_ms = round((time.perf_counter() - t0) * 1000)
        log(f"[phone] {text!r}  (stt {stt_ms}ms {note})")
        if not text:
            job.finish(error="empty transcript" if "quiet" not in note else note)
            hud_state("idle")
            return
        mouth._capture = []
        utter(text, stt_ms=stt_ms)
        mp3 = b"".join(mouth._capture or [])
        mouth._capture = None
        job.finish(text=text, mp3=mp3)
        hud_state("idle")
    except Exception as exc:
        log(f"[phone] {exc}")
        mouth._capture = None
        job.finish(error=str(exc))
        hud_state("idle")


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


class Mouth:
    def __init__(self, kind: str, voice: str = EDGE_VOICE):
        self.kind = kind
        self.voice = voice
        self._sapi = None
        self._voice_name = ""
        self._out = None
        self._last_out = 0.0
        self._capture: list[bytes] | None = None
        self.last_start: float | None = None
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

    def say(self, text: str) -> None:
        self.last_start = None
        if self.kind == "none" or not text.strip():
            return
        if self.kind == "sapi":
            log(f"[mouth] speaking: {text}")
            self.last_start = time.perf_counter()
            self._speak_offline(text)
            return
        if self.kind == "edge":
            log(f"[mouth] speaking ({self.voice}): {text}")
            try:
                asyncio.run(self._edge_play(text))
            except Exception as exc:
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

    def _write_pcm(self, samples) -> None:
        import numpy as np

        x = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
        step = 2048
        for i in range(0, len(x), step):
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

        if FFMPEG is None:
            raise RuntimeError("ffmpeg.exe not found")
        proc = subprocess.run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                str(PLAY_RATE),
                "pipe:1",
            ],
            input=mp3,
            capture_output=True,
            check=True,
        )
        return np.frombuffer(proc.stdout, dtype=np.float32)

    def _feed_edge(self, text: str, proc: subprocess.Popen) -> None:
        async def _run() -> None:
            import edge_tts

            comm = edge_tts.Communicate(text, self.voice, rate="+4%")
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

    async def _edge_play(self, text: str) -> None:
        import numpy as np

        if FFMPEG is None:
            raise RuntimeError("ffmpeg.exe not found")
        proc = subprocess.Popen(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                str(PLAY_RATE),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        threading.Thread(target=self._feed_edge, args=(text, proc), daemon=True).start()
        loop = asyncio.get_running_loop()
        self._ensure_out()
        if time.perf_counter() - self._last_out > 0.12:
            self._write_pcm(np.zeros(int(PLAY_RATE * PREROLL_S), dtype=np.float32))
        leftover = b""
        while True:
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
            self._write_pcm(samples)
        await loop.run_in_executor(None, proc.wait)


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
) -> dict:
    hud_state("thinking", text)
    t0 = time.perf_counter()
    ttfb = None
    first_sent = None
    first_audio = None
    spoken = []
    buf = ""
    for chunk in brain.ask(text):
        now = time.perf_counter()
        if ttfb is None:
            ttfb = now
            log(f"  [{brain.model}] first token {int((now-t0)*1000)}ms {chunk!r}")
        buf += chunk
        while True:
            m = SENTENCE_END.search(buf)
            if not m:
                break
            sent, buf = buf[: m.end()].strip(), buf[m.end() :]
            if not sent:
                continue
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
    tail = buf.strip()
    if tail:
        if first_sent is None:
            first_sent = time.perf_counter()
            log(f"  [{brain.model}] first sentence {int((first_sent-t0)*1000)}ms: {tail}")
            hud_state("speaking", tail)
            mouth.say(tail)
            first_audio = mouth.last_start or time.perf_counter()
        else:
            log(f"  [{brain.model}] {tail}")
            hud_state("speaking", tail)
            mouth.say(tail)
        spoken.append(tail)
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
        "reply": " ".join(spoken),
    }
    extra = f" stt={stt_ms}ms" if stt_ms is not None else ""
    log(
        f"  timing{extra} ttfb={row['ttfb_ms']}ms  "
        f"sentence={row['first_sentence_ms']}ms  "
        f"audio={row['first_audio_ms']}ms  total={row['total_ms']}ms"
    )
    if session is not None:
        session.record(
            text,
            row["reply"],
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

    def __init__(self, brain, mouth: Mouth, board: JobBoard, registry: WorkshopRegistry, session: SessionLog | None):
        self.brain = brain
        self.mouth = mouth
        self.board = board
        self.registry = registry
        self.session = session
        self.pending: set[str] = set()
        self.announced: set[str] = set()

    def utter(self, text: str, stt_ms: int | None = None) -> dict:
        extra = {}
        if self.session is not None:
            extra["session"] = self.session.session_id
        hit = maybe_enqueue(text, self.board, self.registry, extra=extra or None)
        if hit is None:
            return one_turn(self.brain, self.mouth, text, stt_ms=stt_ms, session=self.session)
        intent, job_id = hit
        self.pending.add(job_id)
        log(f"[jobs] {job_id} cap={intent.cap} {text!r}")
        hud_state("speaking", intent.ack)
        self.mouth.say(intent.ack)
        spoken = [intent.ack]
        if self.session is not None:
            self.session.record(
                text,
                intent.ack,
                stt_ms=stt_ms,
                brain="jobs",
                model=intent.cap,
            )
        if intent.wait_s > 0:
            snap = self.board.wait(job_id, timeout=intent.wait_s)
            if snap and snap.get("event") in ("done", "error"):
                self.announced.add(job_id)
                self.pending.discard(job_id)
                line = self._speak_line(snap)
                if line:
                    hud_state("speaking", line)
                    self.mouth.say(line)
                    spoken.append(line)
                    if self.session is not None:
                        self.session.record(
                            f"[job {intent.cap}]",
                            line,
                            brain="jobs",
                            model=intent.cap,
                        )
            else:
                log(f"[jobs] {job_id} still running after {intent.wait_s:.0f}s")
        hud_state("idle")
        return {
            "brain": "jobs",
            "model": intent.cap,
            "stt_ms": stt_ms,
            "reply": " ".join(spoken),
        }

    def drain(self) -> None:
        for job_id in list(self.pending):
            snap = self.board.snapshot(job_id)
            ev = snap.get("event")
            if ev not in ("done", "error"):
                continue
            self.pending.discard(job_id)
            if job_id in self.announced:
                continue
            self.announced.add(job_id)
            line = self._speak_line(snap)
            if not line:
                log(f"[jobs] {job_id} {ev}")
                continue
            log(f"[jobs] {job_id} {ev}: {line}")
            hud_state("speaking", line)
            self.mouth.say(line)
            hud_state("idle")
            if self.session is not None:
                self.session.record(
                    f"[job {snap.get('cap')}]",
                    line,
                    brain="jobs",
                    model=str(snap.get("cap") or ""),
                )
        self._speak_due_reminders()

    def _speak_due_reminders(self) -> None:
        for line in take_due(self.board.home):
            log(f"[remind] {line}")
            hud_state("speaking", line)
            self.mouth.say(line)
            hud_state("idle")
            if self.session is not None:
                self.session.record("[reminder]", line, brain="jobs", model="remind")

    @staticmethod
    def _speak_line(snap: dict) -> str:
        if snap.get("event") == "error":
            return "The workshop could not finish that, sir."
        return str(snap.get("speak") or "").strip()


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
            state["down"] = True
        if key == keyboard.Key.esc:
            state["quit"] = True

    def on_release(key):
        if key == keyboard.Key.home:
            state["down"] = False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    state["listener"] = listener


def run_talk(desk: Desk, stt: str) -> None:
    log("Talk: hold Home, speak, release. Esc or Ctrl-C quits. Type if --stt none.")
    hud_state("idle")
    if stt == "none":
        while True:
            desk.drain()
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line or line.lower() in ("q", "quit", "exit"):
                break
            desk.utter(line)
            hud_state("idle")
        return
    state = {"down": False, "quit": False}
    start_ptt_listener(state)
    log("waiting for Home (or iPhone on the PC hotspot)...")
    while not state["quit"]:
        desk.drain()
        try:
            job = incoming_jobs.get_nowait()
        except queue.Empty:
            job = None
        if job:
            handle_phone_job(job, desk.mouth, desk.utter)
            continue
        if not state["down"]:
            time.sleep(0.02)
            continue
        hud_state("listening")
        log("[ptt] recording...")
        t0 = time.perf_counter()
        pcm = record_held(lambda: state["down"])
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
                desk.mouth.say("I didn't catch that, sir.")
            hud_state("idle")
            continue
        desk.utter(text, stt_ms=stt_ms)
        hud_state("idle")
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
        "--mic",
        default=None,
        help="input device index or name substring (Focusrite, Scarlett, …)",
    )
    p.add_argument("--list-mics", action="store_true", help="print capture devices and exit")
    p.add_argument("--tts", choices=("none", "sapi", "edge"), default="none")
    p.add_argument(
        "--voice",
        default=EDGE_VOICE,
        help="edge-tts voice id (default en-GB-RyanNeural, a British male)",
    )
    p.add_argument("--bench", action="store_true", help="time typed hellos, no mic")
    p.add_argument("--no-hud", action="store_true", help="do not open the Iron Man HUD")
    p.add_argument(
        "--no-workshop",
        action="store_true",
        help="do not spawn the host workshop (desk only)",
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
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
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
    take_lock()
    home = None
    session = None
    board = None
    desk = None
    worker_proc = None
    try:
        home, prompt, board, registry = open_memory(args.data_dir)
        warn = home.take_lease(os.getpid())
        if warn:
            log(f"[memory] {warn}")
        _setup_ears(home, args)
        if not args.no_workshop and not args.bench:
            try:
                worker_proc = spawn_host_workshop(
                    home, grok=GROK, model=args.model, parent_pid=os.getpid()
                )
            except OSError as exc:
                log(f"[workshop] failed to start: {exc}")
                worker_proc = None
            if worker_proc is not None:
                time.sleep(0.35)
                if worker_proc.poll() is not None:
                    log("[workshop] exited immediately — desk only")
                    worker_proc = None
                elif _wait_for_worker(registry):
                    log(f"[workshop] pid={worker_proc.pid} caps={','.join(HOST_CAPS)}")
                    prompt = build_system_prompt(
                        load_boot_notes(home), workers=registry.prompt_line()
                    )
                else:
                    log("[workshop] no heartbeat yet — jobs will still dispatch")
        if not args.no_hud and not args.bench:
            start_hud(open_browser=True)
            hud_state("idle")
        brain = (
            AgentBrain(args.model, system_prompt=prompt)
            if args.brain == "agent"
            else CliBrain(args.model, system_prompt=prompt)
        )
        mouth = Mouth(args.tts, voice=args.voice)
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
            desk = Desk(brain, mouth, board, registry, session)
            run_talk(desk, args.stt)
    finally:
        if session is not None and board is not None:
            session.close()
            dest = distill_session(session, board=board)
            if dest:
                log(f"[memory] daily note {dest}")
            worker_alive = worker_proc is not None and worker_proc.poll() is None
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
        _stop_worker(worker_proc)
        if home is not None:
            home.drop_lease(os.getpid())
        try:
            brain.close()
            mouth.close()
        except NameError:
            pass
        stop_hud()
        drop_lock()


if __name__ == "__main__":
    main()
