"""Who is speaking. Phone picks a name; laptop defaults to the primary.

Voice biometrics are later. Until then the device says who, or they do.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from memory.home import JarvisHome

_HEAD = re.compile(
    r"^[-*]\s+\*\*([^*]+)\*\*(?:\s*[—–:-]\s*(.*))?$",
)
_ALIAS = re.compile(r"\(([^)]+)\)")
_ADDRESS = re.compile(
    r"address as\s+("
    r"(?:Master|Miss|Mrs|Ms|Mr)\s+[A-Za-z][A-Za-z'-]+"
    r"|sir|ma'am|madam"
    r"|[A-Za-z][A-Za-z'-]+"
    r")",
    re.I,
)
_INTRO = re.compile(
    r"^(?:(?:hi|hello|hey)[, ]+)?"
    r"(?:this is|i am|i'm|my name is|i'm called)\s+"
    r"([A-Za-z][A-Za-z'-]+)",
    re.I,
)
_SIR = re.compile(r"\bsir\b", re.I)


@dataclass(frozen=True)
class Person:
    slug: str
    name: str
    aliases: tuple[str, ...]
    address: str
    primary: bool = False
    guest: bool = False


def _slug(name: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return t or "guest"


def _spoken_and_aliases(field: str) -> tuple[str, tuple[str, ...]]:
    raw = " ".join((field or "").split())
    parens = [a.strip() for a in _ALIAS.findall(raw) if a.strip()]
    core = _ALIAS.sub(" ", raw)
    core = " ".join(core.split())
    aliases: list[str] = []
    for item in [core, *parens]:
        if item and item.lower() not in {a.lower() for a in aliases}:
            aliases.append(item)
        for part in item.replace("/", " ").split():
            if len(part) > 1 and part.lower() not in {a.lower() for a in aliases}:
                aliases.append(part)
    spoken = parens[-1] if parens else (core.split()[0] if core else "there")
    return spoken, tuple(aliases)


def parse_household(text: str) -> list[Person]:
    people: list[Person] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        hit = _HEAD.match(line.strip())
        if not hit:
            continue
        spoken, aliases = _spoken_and_aliases(hit.group(1))
        rest = hit.group(2) or ""
        primary = bool(re.search(r"\bprimary\b", rest, re.I))
        addr_hit = _ADDRESS.search(rest)
        if addr_hit:
            address = " ".join(addr_hit.group(1).split())
        elif re.search(r"\bsir\b", rest, re.I) or primary:
            address = "sir"
        else:
            address = spoken
        slug = _slug(spoken)
        if slug in seen or slug in {"household", "add", "keep"}:
            continue
        seen.add(slug)
        people.append(
            Person(
                slug=slug,
                name=spoken,
                aliases=aliases,
                address=address,
                primary=primary,
            )
        )
    if people and not any(p.primary for p in people):
        first = people[0]
        people[0] = Person(
            slug=first.slug,
            name=first.name,
            aliases=first.aliases,
            address=first.address,
            primary=True,
        )
    return people


def load_roster(home: JarvisHome) -> list[Person]:
    path = home.vault / "people" / "_household.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse_household(text)


def primary(roster: list[Person]) -> Person | None:
    for person in roster:
        if person.primary:
            return person
    return roster[0] if roster else None


def match_person(token: str, roster: list[Person]) -> Person | None:
    raw = " ".join((token or "").split())
    if not raw:
        return None
    key = raw.lower().strip()
    slug = _slug(key)
    for person in roster:
        if person.slug == slug:
            return person
        for alias in person.aliases:
            if alias.lower() == key:
                return person
    return None


def guest(name: str) -> Person:
    spoken = " ".join((name or "").split()) or "there"
    spoken = spoken.split()[0]
    spoken = spoken[:1].upper() + spoken[1:]
    return Person(
        slug=_slug(spoken),
        name=spoken,
        aliases=(spoken,),
        address=spoken,
        primary=False,
        guest=True,
    )


def resolve_who(token: str, roster: list[Person]) -> Person | None:
    raw = " ".join((token or "").split())
    if not raw:
        return None
    hit = match_person(raw, roster)
    if hit:
        return hit
    if re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,24}", raw):
        return guest(raw)
    return None


def match_intro(text: str, roster: list[Person]) -> Person | None:
    """Only household names. 'This is embarrassing' is not an introduction."""
    hit = _INTRO.search(" ".join((text or "").split()))
    if not hit:
        return None
    return match_person(hit.group(1), roster)


def vocative(person: Person | None) -> str:
    if person is None:
        return "sir"
    v = (person.address or person.name or "").strip()
    return v or "sir"


def with_vocative(line: str, person: Person | None) -> str:
    raw = " ".join((line or "").split())
    if not raw:
        return ""
    v = vocative(person)
    if _SIR.search(raw):
        return _SIR.sub(v, raw, count=1)
    if not v:
        return raw
    if raw.endswith("."):
        return raw[:-1] + f", {v}."
    return raw + f", {v}."


def speaker_note(person: Person | None) -> str:
    if person is None:
        return ""
    v = vocative(person)
    bits = [
        f"You are speaking with {person.name}.",
        f"Address them as {v}.",
    ]
    if v.lower() != "sir":
        bits.append("Never call them sir.")
    if not person.primary:
        bits.append(
            "They are not Matt. Do not use Matt's accounts, work, or preferences as theirs."
        )
    if person.guest:
        bits.append("Guest for this turn only.")
    return "[speaker]\n" + " ".join(bits)


def public_roster(home: JarvisHome) -> list[dict]:
    out = []
    for person in load_roster(home):
        out.append(
            {
                "slug": person.slug,
                "name": person.name,
                "address": vocative(person),
                "primary": person.primary,
            }
        )
    return out


def write_public_roster(home: JarvisHome, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(public_roster(home), indent=2) + "\n", encoding="utf-8"
    )
    return dest
