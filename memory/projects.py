"""Engineering work the mouth can recall. One markdown file per project."""
from __future__ import annotations

import re
from pathlib import Path

from memory.home import JarvisHome

_SLUG = re.compile(r"[^a-z0-9]+")
_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "on",
        "in",
        "to",
        "for",
        "of",
        "my",
        "our",
        "this",
        "that",
        "with",
        "about",
        "jarvis",
        "please",
        "project",
        "bench",
    }
)
# Filename stem → extra words that should load that page.
_ALIASES: dict[str, tuple[str, ...]] = {
    "pergola": ("pergola", "rafter", "rafters", "alley", "pallet", "timber"),
    "room-node": (
        "room-node",
        "room node",
        "house mic",
        "house mics",
        "esp32",
        "esp-32",
        "esp",
        "mems",
        "electronics",
        "circuit",
        "kit",
        "devkit",
    ),
}


def projects_dir(home: JarvisHome) -> Path:
    dest = home.vault / "projects"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def project_id(name: str) -> str:
    slug = _SLUG.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:80] or "misc"


def project_path(home: JarvisHome, name: str) -> Path:
    return projects_dir(home) / f"{project_id(name)}.md"


def list_projects(home: JarvisHome) -> list[Path]:
    root = home.vault / "projects"
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.glob("*.md")
        if p.is_file() and p.name.lower() != "readme.md"
    )


def _title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path.stem.replace("-", " ")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or path.stem.replace("-", " ")
    return path.stem.replace("-", " ")


def projects_index(home: JarvisHome, *, limit: int = 320) -> str:
    rows = []
    for path in list_projects(home):
        rows.append(_title(path))
    if not rows:
        return ""
    text = "On file: " + "; ".join(rows) + "."
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _hay(path: Path) -> str:
    extra = " ".join(_ALIASES.get(path.stem.lower(), ()))
    return f"{path.stem} {_title(path)} {extra}".lower()


def match_projects(home: JarvisHome, asked: str, *, limit: int = 2) -> list[Path]:
    raw = " ".join((asked or "").split()).lower()
    if not raw:
        return []
    words = [w for w in re.findall(r"[a-z0-9]+", raw) if w not in _STOP and len(w) > 2]
    scored: list[tuple[int, Path]] = []
    for path in list_projects(home):
        blob = _hay(path)
        score = 0
        if path.stem.lower() in raw or path.stem.replace("-", " ") in raw:
            score += 5
        for w in words:
            if w in blob:
                score += 2
        if score:
            scored.append((score, path))
    scored.sort(key=lambda row: (-row[0], row[1].name))
    return [p for _s, p in scored[:limit]]


def _read(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def project_notes(
    home: JarvisHome, asked: str, *, limit: int = 900
) -> list[tuple[str, str]]:
    notes: list[tuple[str, str]] = []
    for path in match_projects(home, asked):
        body = _read(path, limit)
        if body:
            notes.append((path.stem, body))
    return notes


def ensure_project_file(home: JarvisHome, name: str, title: str = "") -> Path:
    dest = project_path(home, name)
    if dest.is_file():
        return dest
    label = (title or name.replace("-", " ")).strip()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f"# {label}\n\n", encoding="utf-8")
    return dest
