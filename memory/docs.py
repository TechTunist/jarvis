"""Written artefacts: specs, parts lists, build notes, PDFs.

Lives in ~/Documents/jarvis — not the git repo, not the vault.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path


def documents_root() -> Path:
    custom = os.environ.get("JARVIS_DOCUMENTS")
    if custom:
        return Path(custom).expanduser().resolve()
    xdg = os.environ.get("XDG_DOCUMENTS_DIR")
    if xdg:
        return (Path(xdg).expanduser() / "jarvis").resolve()
    home = Path.home()
    for name in ("Documents", "documents"):
        cand = home / name
        if cand.is_dir():
            return (cand / "jarvis").resolve()
    return (home / "Documents" / "jarvis").resolve()


def day_dir(today: date | None = None) -> Path:
    today = today or date.today()
    return documents_root() / today.isoformat()


def slug_title(text: str, fallback: str = "guide") -> str:
    t = " ".join((text or "").split()).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:48].strip("-")
    return t or fallback


_STUB = re.compile(
    r"searching the workspace|need the hardware details|i don't have (?:the )?(?:context|details)|"
    r"cannot (?:find|locate) (?:the )?brief|no (?:project )?context",
    re.I,
)


def looks_like_guide(text: str) -> bool:
    body = (text or "").strip()
    if len(body) < 400:
        return False
    if _STUB.search(body):
        return False
    if not re.search(r"(?m)^(#{1,3}\s|- |\d+\.\s)", body):
        return False
    return True


def speak_ready(path: Path) -> str:
    name = path.name
    return f"Ready, sir. {name}, in today's Documents folder."


def _wrap(text: str, width: int = 92) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        raw = raw.expandtabs(4).rstrip()
        if not raw:
            lines.append("")
            continue
        while len(raw) > width:
            cut = raw.rfind(" ", 0, width)
            if cut < 20:
                cut = width
            lines.append(raw[:cut])
            raw = raw[cut:].lstrip()
        lines.append(raw)
    return lines or [""]


def write_pdf(body: str, dest: Path, *, title: str = "Jarvis") -> Path:
    """Minimal Latin-1 PDF. No extra packages."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = _wrap(body)
    per_page = 48
    pages = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[""]]

    def esc(s: str) -> str:
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content_ids: list[int] = []
    page_ids: list[int] = []
    objs: dict[int, bytes] = {}
    next_id = 3  # 1=catalog, 2=pages

    font_id = next_id
    next_id += 1
    objs[font_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
    )

    for page_no, chunk in enumerate(pages, start=1):
        cmds = ["BT", "/F1 11 Tf", "14 TL", "50 800 Td"]
        for i, line in enumerate(chunk):
            if i:
                cmds.append("T*")
            cmds.append(f"({esc(line)}) Tj")
        cmds.append("ET")
        stream = "\n".join(cmds).encode("latin-1", "replace")
        cid = next_id
        next_id += 1
        content_ids.append(cid)
        objs[cid] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream\n"
        )
        pid = next_id
        next_id += 1
        page_ids.append(pid)
        objs[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Contents {cid} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>\n"
        ).encode("ascii")

    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objs[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>\n"
    ).encode("ascii")
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>\n"

    order = [1, 2, font_id, *content_ids, *page_ids]
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {0: 0}
    for oid in order:
        offsets[oid] = len(buf)
        buf.extend(f"{oid} 0 obj\n".encode("ascii"))
        buf.extend(objs[oid])
        if not objs[oid].endswith(b"\n"):
            buf.extend(b"\n")
        buf.extend(b"endobj\n")
    xref = len(buf)
    nobj = max(order) + 1
    buf.extend(f"xref\n0 {nobj}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for i in range(1, nobj):
        off = offsets.get(i, 0)
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        (
            f"trailer\n<< /Size {nobj} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    dest.write_bytes(bytes(buf))
    return dest


def save_guide(markdown: str, *, slug: str, when: datetime | None = None) -> tuple[Path, Path]:
    when = when or datetime.now()
    folder = day_dir(when.date())
    folder.mkdir(parents=True, exist_ok=True)
    stamp = when.strftime("%H%M%S")
    md = folder / f"{stamp}-{slug}.md"
    pdf = folder / f"{stamp}-{slug}.pdf"
    body = (markdown or "").strip() + "\n"
    md.write_text(body, encoding="utf-8")
    write_pdf(body, pdf, title=slug)
    return md, pdf
