"""Mics and local Whisper. Grok never hears audio.

Laptop lid mics are not the product. Prefer USB/Focusrite or the phone HUD.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from memory.home import JarvisHome

PREFERRED = (
    "focusrite",
    "scarlett",
    "yeti",
    "blue ",
    "rode",
    "samson",
    "fifine",
    "at2020",
    "audio-technica",
    "hyperx",
    "jabra",
    "usb microphone",
    "usb audio",
    "condenser",
)
AVOID = (
    "monitor of",
    "loopback",
    "dummy",
    "hdmi",
    "lavrate",
    "speex",
    "upmix",
    "vdownmix",
    "samplerate",
)
BUILTIN = ("alc", "analog", "internal", "laptop", "pch", "realtek", "sof-")
TOO_QUIET_PEAK = 0.008
TOO_QUIET_RMS = 0.0015
WAKE_LEAD = ("hey", "ok", "okay", "hi", "yo")
# Open-mic energy gate (30 ms frames at 16 kHz). Not a wake word.
# Low vs PTT: Focusrite speech often sits under 0.015 rms.
OPEN_START_RMS = 0.004
OPEN_HOLD_RMS = 0.0018
OPEN_START_PEAK = 0.02
OPEN_START_N = 3  # ~90 ms loud
OPEN_END_N = 38  # ~1.14 s quiet — breath / think, not a comma
OPEN_MIN_N = 8  # ~240 ms of speech
OPEN_MAX_N = 400  # ~12 s
OPEN_PREROLL = 8
CORE_WORDS = (
    "Jarvis",
    "Matt",
    "Jak",
    "Jack",
    "Canterbury",
    "lamp",
    "garage",
    "kitchen",
    "entrance",
)


def mic_config_path(home: JarvisHome) -> Path:
    return home.root / "mic.json"


def load_mic_pref(home: JarvisHome) -> str | None:
    path = mic_config_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    want = str(doc.get("device") or "").strip()
    return want or None


def save_mic_pref(home: JarvisHome, device: str) -> None:
    home.root.mkdir(parents=True, exist_ok=True)
    mic_config_path(home).write_text(
        json.dumps({"device": device}, indent=2) + "\n", encoding="utf-8"
    )


def _kind(name: str) -> str:
    low = name.lower()
    if any(p in low for p in PREFERRED):
        return "usb"
    if any(b in low for b in BUILTIN):
        return "builtin"
    return "other"


def list_inputs(devices: list[dict] | None = None) -> list[dict]:
    if devices is None:
        import sounddevice as sd

        devices = list(sd.query_devices())
    rows = []
    for i, dev in enumerate(devices):
        n_in = int(dev.get("max_input_channels") or 0)
        if n_in <= 0:
            continue
        name = str(dev.get("name") or f"device-{i}")
        low = name.lower()
        if any(a in low for a in AVOID):
            continue
        rows.append({"index": i, "name": name, "channels": n_in, "kind": _kind(name)})
    return rows


def pick_input(
    devices: list[dict] | None = None,
    want: str | None = None,
) -> dict | None:
    rows = list_inputs(devices)
    if not rows:
        return None
    if want:
        want_l = want.strip().lower()
        if want_l.isdigit():
            idx = int(want_l)
            for row in rows:
                if row["index"] == idx:
                    return row
        for row in rows:
            if want_l in row["name"].lower():
                return row
    usb = [r for r in rows if r["kind"] == "usb"]
    if usb:
        return usb[0]
    named = [r for r in rows if r["name"].lower() in ("default", "pulse")]
    if named:
        return named[0]
    return rows[0]


def format_inputs(rows: list[dict], chosen: dict | None = None) -> str:
    lines = []
    for row in rows:
        mark = "*" if chosen and row["index"] == chosen["index"] else " "
        lines.append(
            f"{mark} {row['index']:3}  {row['kind']:8}  {row['name']}"
        )
    return "\n".join(lines)


class EnergyGate:
    """Frame energy VAD for always-on listen. No hardware, no Whisper."""

    def __init__(
        self,
        start_rms: float = OPEN_START_RMS,
        hold_rms: float = OPEN_HOLD_RMS,
        start_n: int = OPEN_START_N,
        end_n: int = OPEN_END_N,
        min_n: int = OPEN_MIN_N,
        max_n: int = OPEN_MAX_N,
        preroll: int = OPEN_PREROLL,
        start_peak: float = OPEN_START_PEAK,
    ) -> None:
        self.start_rms = start_rms
        self.hold_rms = hold_rms
        self.start_peak = start_peak
        self.start_n = start_n
        self.end_n = end_n
        self.min_n = min_n
        self.max_n = max_n
        self.preroll_n = preroll
        self.reset()

    def reset(self) -> None:
        self.speech = False
        self.loud = 0
        self.quiet = 0
        self.voiced = 0
        self.total = 0
        self.noise = 0.0
        self.preroll: list[float] = []

    def feed(self, rms: float, peak: float = 0.0) -> str:
        """Return idle, start, speech, or end."""
        level = float(rms)
        pk = float(peak)
        if not self.speech:
            self.preroll.append(level)
            if len(self.preroll) > self.preroll_n:
                self.preroll.pop(0)
            if self.noise <= 0.0:
                self.noise = max(level, 1e-6)
            else:
                self.noise = 0.97 * self.noise + 0.03 * min(level, self.noise * 4)
            thresh = max(self.start_rms, self.noise * 4.0)
            hold = max(self.hold_rms, self.noise * 1.6)
            self._hold = hold
            hot = level >= thresh or pk >= max(self.start_peak, self.noise * 10)
            if hot:
                self.loud += 1
            else:
                self.loud = 0
            if self.loud >= self.start_n:
                self.speech = True
                self.quiet = 0
                self.voiced = self.loud
                self.total = self.loud
                return "start"
            return "idle"
        self.total += 1
        hold = getattr(self, "_hold", self.hold_rms)
        if level >= hold or pk >= self.start_peak * 0.5:
            self.quiet = 0
            self.voiced += 1
        else:
            self.quiet += 1
        ended = False
        if self.quiet >= self.end_n and self.voiced >= self.min_n:
            ended = True
        if self.total >= self.max_n:
            ended = True
        if ended:
            self.speech = False
            return "end"
        return "speech"


def after_wake(text: str, word: str = "jarvis") -> str | None:
    """If the line starts with the wake name, return the rest. None = ignore.

    'Jarvis, lights off' → 'lights off'. Bare 'hey Jarvis' → '' (a ping).
    Not a keyword spotter — Whisper already heard the clip.
    """
    raw = " ".join((text or "").split())
    if not raw:
        return None
    name = (word or "jarvis").strip().lower()
    if not name:
        return None
    low = raw.lower()
    # Strip leading punctuation / vocatives.
    body = re.sub(r"^[\s,.:;!?]+", "", low)
    tokens = re.split(r"[\s,]+", body)
    tokens = [re.sub(r"[^a-z0-9]+", "", t) for t in tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    i = 0
    if tokens[0] in WAKE_LEAD and len(tokens) > 1:
        i = 1
    hit = None
    for j in range(i, min(len(tokens), i + 3)):
        if _wake_token(tokens[j], name):
            hit = j
            break
    if hit is None:
        return None
    return " ".join(tokens[hit + 1 :])


def _wake_token(tok: str, name: str) -> bool:
    if tok == name:
        return True
    # Whisper often hears Jarvis as Jarvus / Jarvish.
    if len(name) >= 5 and tok.startswith(name[:4]) and abs(len(tok) - len(name)) <= 2:
        return True
    return False


def rms_peak(samples) -> tuple[float, float]:
    n = len(samples)
    if n == 0:
        return 0.0, 0.0
    total = 0.0
    peak = 0.0
    for x in samples:
        v = float(x)
        av = abs(v)
        if av > peak:
            peak = av
        total += v * v
    return math.sqrt(total / n), peak


def prepare_audio(pcm):
    """Boost quiet speech a bit. None means too quiet to bother Whisper."""
    import numpy as np

    audio = np.asarray(pcm, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return None, "empty"
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if peak < TOO_QUIET_PEAK and rms < TOO_QUIET_RMS:
        return None, f"too quiet (peak={peak:.4f} rms={rms:.4f})"
    if 0 < peak < 0.12:
        audio = audio * min(0.35 / peak, 10.0)
    return audio, f"peak={peak:.3f} rms={rms:.3f}"


def _bold_names(text: str) -> list[str]:
    found = []
    for m in re.finditer(r"\*\*([^*]{2,40})\*\*", text or ""):
        name = m.group(1).strip()
        if name and name not in found:
            found.append(name)
    return found


def vocabulary(home: JarvisHome) -> tuple[str, str]:
    words: list[str] = list(CORE_WORDS)
    people = home.vault / "people"
    if people.is_dir():
        for path in sorted(people.glob("*.md")):
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name in _bold_names(body):
                if name not in words:
                    words.append(name)
    names_file = home.cache / "ha-names.txt"
    if names_file.is_file():
        try:
            extra = names_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            extra = []
        for line in extra:
            name = line.strip()
            if name and name not in words:
                words.append(name)
            if len(words) >= 24:
                break
    prompt = "Jarvis. " + ". ".join(words[:18]) + "."
    hot = " ".join(words[:16])
    return prompt[:400], hot[:220]


def transcribe_pcm(
    pcm,
    model,
    *,
    prompt: str = "",
    hotwords: str = "",
) -> tuple[str, str]:
    """Returns (text, level_note). Empty text if silence or too quiet."""
    import numpy as np

    audio, note = prepare_audio(pcm)
    if audio is None:
        return "", note
    kwargs: dict[str, Any] = {
        "language": "en",
        "temperature": 0.0,
        "beam_size": 5,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.6,
    }
    if prompt:
        kwargs["initial_prompt"] = prompt
    if hotwords:
        kwargs["hotwords"] = hotwords
    segments, _info = model.transcribe(audio, **kwargs)
    text = "".join(s.text for s in list(segments)).strip()
    return text, note


def cache_ha_names(home: JarvisHome, labels: list[str]) -> None:
    home.cache.mkdir(parents=True, exist_ok=True)
    lines = [x.strip() for x in labels if x and x.strip()]
    (home.cache / "ha-names.txt").write_text(
        "\n".join(lines[:80]) + ("\n" if lines else ""),
        encoding="utf-8",
    )
