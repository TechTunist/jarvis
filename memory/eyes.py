"""Opt-in stills. Jarvis looks only when asked — no always-on camera."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from shutil import which

from memory.home import JarvisHome
from memory.prompt import HANDS_RULES

SEE_SYSTEM = (
    HANDS_RULES
    + "You are looking through a still photograph just taken. "
    "Say what you see in one or two short spoken sentences. "
    "Answer the question if they asked one. No markdown, no lists, no preamble. "
    "Do not invent people who are not in the picture. "
    "Do not store or repeat secrets, passwords, or card numbers if they appear."
)


def eyes_dir(home: JarvisHome, when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc)
    dest = home.cache / "eyes" / when.strftime("%Y-%m-%d")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def save_still(
    home: JarvisHome,
    data: bytes,
    *,
    suffix: str = ".jpg",
    when: datetime | None = None,
) -> Path:
    when = when or datetime.now(timezone.utc)
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    if ext.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    dest = eyes_dir(home, when) / f"{when.strftime('%H%M%S')}-{when.microsecond:06d}{ext}"
    dest.write_bytes(data)
    return dest


def wants_screen(text: str) -> bool:
    t = (text or "").lower()
    return "screen" in t or "display" in t or "monitor" in t


def grab_webcam(dest: Path) -> Path | None:
    ffmpeg = which("ffmpeg")
    video = Path("/dev/video0")
    if not ffmpeg or not video.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "v4l2",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=960:-1",
            "-q:v",
            "5",
            str(dest),
        ],
        capture_output=True,
        timeout=8,
    )
    if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 200:
        return dest
    return None


def grab_screen(dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmds: list[list[str]] = []
    if which("grim"):
        cmds.append(["grim", str(dest)])
    if which("gnome-screenshot"):
        cmds.append(["gnome-screenshot", "-f", str(dest)])
    if which("import"):
        cmds.append(["import", "-window", "root", str(dest)])
    for cmd in cmds:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 200:
            return dest
    return None


def grab_still(home: JarvisHome, prompt: str = "") -> Path | None:
    when = datetime.now(timezone.utc)
    dest = eyes_dir(home, when) / f"{when.strftime('%H%M%S')}-grab.jpg"
    if wants_screen(prompt):
        return grab_screen(dest) or grab_webcam(dest)
    return grab_webcam(dest) or grab_screen(dest)
