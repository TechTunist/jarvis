"""Imagine workshop helpers.

Stills:  ~/Pictures/jarvis/YYYY-MM-DD/HHMMSS-slug.jpg
Videos:  ~/Videos/jarvis/YYYY-MM-DD/HHMMSS-slug.mp4
Albums:  .../jarvis/albums/<name>/
Catalog: INDEX.md in that library root. Talk does not load it.

Never the git checkout, never ~/.grok/sessions.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
VIDEO_EXT = frozenset({".mp4", ".webm", ".mov", ".mkv"})
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT
RESERVED_ALBUMS = frozenset(
    {
        "albums",
        "images",
        "videos",
        "index",
        "vault",
        "secrets",
        "jobs",
        "logs",
        "cache",
        "tmp",
        "temp",
        "workshops",
    }
)
INDEX_HEADER = (
    "# Imagine catalog\n\n"
    "Generated media. Not the vault; Talk does not load this file.\n\n"
)
_ANIM = re.compile(
    r"\b(?:rotat(?:e|ing)|spinn(?:ing)?|animat(?:e|ion|ions|ed)|"
    r"videos?|clips?|turntable|orbit|(?:360|three[\s-]*sixty))\b",
    re.I,
)

_IMAGINE_PREFIX = re.compile(
    r"^(?:please\s+)?(?:"
    r"(?:generate|create|make|draw|paint|render|imagine)\s+"
    r"(?:me\s+)?(?:an?\s+)?(?:(?:rotat(?:e|ing)|spinn(?:ing)?|animat(?:e|ed))\s+)?"
    r"(?:image|picture|photo|illustration|painting|portrait|drawing|video|animation|clip)"
    r"(?:\s+of)?\s*"
    r"|(?:draw|paint|sketch)\s+me\s+(?:an?\s+)?"
    r"|(?:rotat(?:e|ing)|spinn(?:ing)?|animat(?:e|ed))\s+(?:an?\s+)?"
    r"|imagine\s+(?:me\s+)?"
    r")",
    re.I,
)
# Trailing dest only, and only with save/put/file or folder/album/project.
_DEST = re.compile(
    r"""
    [,.]?\s+
    (?:
        (?:please\s+)?(?:save|file|put|drop)\s+(?:it|this|that)?\s*
        (?:in|into|to|under)\s+(?:the\s+)?
        (?P<a>[\w][\w '-]{0,40}?)
        (?:\s+(?:folder|album|directory|dir|project))?
        |
        (?:in|into|under)\s+(?:the\s+)?
        (?P<b>[\w][\w '-]{0,40}?)
        \s+(?:folder|album|directory|dir)
        |
        for\s+(?:the\s+)?
        (?P<c>[\w][\w '-]{0,40}?)
        \s+(?:project|folder|album)
        |
        (?:album|folder)\s+
        (?P<d>[\w][\w '-]{0,40}?)
    )
    \s*[.!]?\s*$
    """,
    re.I | re.X,
)


def wants_animation(text: str) -> bool:
    return bool(_ANIM.search(text or ""))


def wants_assembly(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:go together|assembl(?:e|y|ed|ing)|exploded|"
            r"how the (?:parts|components)|parts list|"
            r"build instructions|how to (?:make|build) them)\b",
            text or "",
            re.I,
        )
    )


def slug_title(text: str, fallback: str = "picture") -> str:
    t = " ".join((text or "").split()).lower()
    t = re.sub(r"^(?:an?|the)\s+", "", t)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40].strip("-")
    return t or fallback


def album_slug(name: str) -> str | None:
    slug = slug_title(name, fallback="")
    if not slug or slug in RESERVED_ALBUMS:
        return None
    if slug.replace("-", "").isdigit():
        return None
    return slug[:32]


def parse_imagine_request(text: str) -> tuple[str, str | None]:
    """Subject for the filename, plus an album slug if the utterance named one."""
    raw = " ".join((text or "").split())
    album = None
    match = _DEST.search(raw)
    if match:
        name = next((g for g in match.groups() if g), "")
        album = album_slug(name)
        raw = raw[: match.start()].strip(" .,")
    subject = _IMAGINE_PREFIX.sub("", raw).strip(" .")
    return (subject or "picture"), album


def imagine_subject(text: str) -> str:
    subject, _ = parse_imagine_request(text)
    return subject


def _user_media(env_key: str, xdg_name: str, fallback: str) -> Path:
    custom = os.environ.get(env_key)
    if custom:
        return Path(custom).expanduser().resolve()
    xdg = os.environ.get(f"XDG_{xdg_name}_DIR")
    if xdg:
        return (Path(xdg).expanduser() / "jarvis").resolve()
    home = Path.home()
    for name in (fallback, fallback.lower()):
        cand = home / name
        if cand.is_dir():
            return (cand / "jarvis").resolve()
    return (home / fallback / "jarvis").resolve()


def library_root(kind: str = "still") -> Path:
    if kind == "video":
        return _user_media("JARVIS_VIDEOS", "VIDEOS", "Videos")
    return _user_media("JARVIS_PICTURES", "PICTURES", "Pictures")


def library_label(kind: str = "still") -> str:
    return "Videos" if kind == "video" else "Pictures"


def album_dir(root: Path, album: str | None, today: date | None = None) -> Path:
    today = today or date.today()
    root = root.resolve()
    if album:
        dest = (root / "albums" / album).resolve()
    else:
        dest = (root / today.isoformat()).resolve()
    dest.relative_to(root)
    return dest


def grok_session_folder(cwd: Path, session_id: str) -> Path | None:
    if not session_id or not cwd:
        return None
    key = quote(str(Path(cwd).expanduser().resolve()), safe="")
    return Path.home() / ".grok" / "sessions" / key / session_id


def _walk_strings(obj: object):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for val in obj.values():
            yield from _walk_strings(val)
    elif isinstance(obj, list):
        for val in obj:
            yield from _walk_strings(val)


def _looks_like_media_path(s: str) -> bool:
    text = (s or "").strip()
    if not text or len(text) > 400 or "\n" in text:
        return False
    if Path(text).suffix.lower() not in MEDIA_EXT:
        return False
    return "/" in text or "\\" in text or text.lower().startswith(("images", "videos"))


def files_from_stream(stdout: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        for s in _walk_strings(ev):
            if _looks_like_media_path(s) and s not in seen:
                seen.add(s)
                found.append(s)
    return found


def resolve_image_path(raw: str, dest_dir: Path) -> Path | None:
    text = (raw or "").strip().strip("\"'")
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = dest_dir / path
    try:
        path = path.resolve()
    except OSError:
        return None
    if path.suffix.lower() not in MEDIA_EXT:
        return None
    if path.is_file():
        return path
    return None


def collect_new_images(root: Path, since: float, *, limit: int = 16) -> list[Path]:
    found: list[Path] = []
    if not root or not Path(root).is_dir():
        return found
    folders = [Path(root), Path(root) / "images", Path(root) / "videos"]
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXT:
                continue
            try:
                if path.stat().st_mtime >= since - 2:
                    found.append(path)
            except OSError:
                continue
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[:limit]


def pick_candidate(paths: list[Path], kind: str = "still") -> Path | None:
    if not paths:
        return None
    if kind == "video":
        videos = [p for p in paths if p.suffix.lower() in VIDEO_EXT]
        if videos:
            return videos[0]
    stills = [p for p in paths if p.suffix.lower() in IMAGE_EXT]
    if stills:
        return stills[0]
    return paths[0]


def stray_repo_blob(path: Path, repo: Path = REPO_ROOT) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
    except ValueError:
        return False
    return path.suffix.lower() in MEDIA_EXT


def is_scratch(path: Path, repo: Path = REPO_ROOT) -> bool:
    resolved = path.resolve()
    roots = [repo, Path.home() / ".grok" / "sessions"]
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    if resolved.parent.name.lower() in {"images", "videos"}:
        return True
    return False


def settle_image(
    src: Path,
    dest_dir: Path,
    slug: str,
    *,
    repo: Path = REPO_ROOT,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() if src.suffix.lower() in MEDIA_EXT else ".jpg"
    stamp = datetime.now().strftime("%H%M%S")
    dest = dest_dir / f"{stamp}-{slug}{ext}"
    n = 1
    while dest.exists() and dest.resolve() != src.resolve():
        dest = dest_dir / f"{stamp}-{slug}-{n}{ext}"
        n += 1
    src_res = src.resolve()
    dest_res = dest.resolve()
    if src_res != dest_res:
        try:
            src.replace(dest)
        except OSError:
            shutil.copy2(src, dest)
            if is_scratch(src, repo=repo):
                try:
                    src.unlink()
                except OSError:
                    pass
    if src.exists() and src_res != dest_res and is_scratch(src, repo=repo):
        try:
            src.unlink()
        except OSError:
            pass
    return dest.resolve()


def append_index(root: Path, rel: str, label: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "INDEX.md"
    if not path.is_file():
        path.write_text(INDEX_HEADER, encoding="utf-8")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = " ".join((label or "").split())[:80] or "picture"
    rel = str(rel).replace("\\", "/").lstrip("/")
    line = f"- {stamp}  `{rel}`  — {label}\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def folder_phrase(
    path: Path,
    root: Path,
    today: date | None = None,
    *,
    library: str = "Pictures",
) -> str:
    today = today or date.today()
    try:
        parent = path.resolve().parent.relative_to(root.resolve())
    except ValueError:
        return f"your {library} folder"
    key = parent.as_posix()
    if key in (".", ""):
        return f"your {library} folder"
    if key == today.isoformat():
        return f"today's {library} folder"
    if key.startswith("albums/"):
        name = key.split("/", 1)[-1].replace("-", " ")
        return f"the {name} folder"
    return f"the {key.replace('-', ' ')} folder"


def rescue_session_media(
    cwd: Path,
    session_id: str,
    *,
    since: float = 0.0,
    slug: str = "picture",
) -> list[Path]:
    """Move grok session stills/videos into Pictures/Videos. Returns new paths."""
    sess = grok_session_folder(cwd, session_id)
    if sess is None:
        return []
    moved: list[Path] = []
    for src in collect_new_images(sess, since or 0.0, limit=16):
        kind = "video" if src.suffix.lower() in VIDEO_EXT else "still"
        root = library_root(kind)
        dest_dir = album_dir(root, None)
        try:
            final = settle_image(src, dest_dir, slug_title(slug or src.stem))
            rel = final.resolve().relative_to(root.resolve())
            append_index(root, rel.as_posix(), slug or src.stem)
            moved.append(final)
        except Exception:
            continue
    return moved


def speak_ready(
    path: Path,
    title: str = "",
    *,
    root: Path | None = None,
    today: date | None = None,
    library: str = "Pictures",
) -> str:
    title = " ".join((title or "").split())
    where = f"your {library} folder"
    if root is not None:
        where = folder_phrase(path, root, today=today, library=library)
    if title:
        return f"Ready, sir. {title}, in {where}."
    return f"Ready, sir. In {where}."
