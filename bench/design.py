"""Inventory, site, and constrained timber layout for the millimetre bench.

Grok does not pick millimetres. Speech becomes stock + site + hints; this
module consumes the pile and places boards that must fit the alley and clear
the midpoint headroom.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

_CSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_QTY = r"(?P<qty>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_DIM = r"(?P<l>\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*(?P<w>\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?\s*[x×]\s*(?P<t>\d+(?:\.\d+)?)\s*(?:mm|millimet(?:er|re)s?)?"
_STOCK = re.compile(
    r"(?:^|[\s,:;])"
    + _QTY
    + r"\s*(?:lengths?\s+of|pieces?\s+of|x|×)?\s*"
    + _DIM,
    re.I,
)
_DESIGN = re.compile(
    r"(?:"
    r"\bpergola\b"
    r"|\brafters?\b"
    r"|\bheadroom\b"
    r"|\balley\b"
    r"|\b(?:design|create|build|make)\b.{0,50}\b(?:structure|pergola|frame)"
    r"|\bentire structure\b"
    r"|\b\d+\s+upright"
    r"|\bupright boards?\s+at\b"
    r")",
    re.I,
)
_INVENTORY = re.compile(
    r"(?:"
    r"\blengths of\b"
    r"|\b(?:available|recovered)\b.{0,40}\b(?:pine|timber|wood|pallet)"
    r"|\bI have\b.{0,40}\b(?:pine|timber|wood|boards?|lengths?)"
    r")",
    re.I,
)
_UPRIGHTS = re.compile(
    r"(\d+|two|three|four)\s+upright(?:s| boards?)?(?:\s+at\s+(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:centres?|centers?))?",
    re.I,
)
_CENTRES = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:centres?|centers?)",
    re.I,
)
_AWAY = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|m)\s+"
    r"(?:away|across|wide)\b",
    re.I,
)
_LONG = re.compile(
    r"(?:about\s+)?(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|m|metres?|meters?)\s+long\b",
    re.I,
)
_HEADROOM = re.compile(
    r"(?:(?:min(?:imum)?\s+)?(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|m|metres?|meters?)\s+(?:min(?:imum)\s+)?headroom"
    r"|headroom.{0,40}?(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|m|metres?|meters?))",
    re.I,
)
_WALL_H = re.compile(
    r"(?:wall.{0,48}?(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|m|metres?|meters?)\s+high"
    r"|(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|m|metres?|meters?)\s+high.{0,32}wall)",
    re.I,
)
_STOREY = re.compile(r"\b(\d+)\s*stor(?:e)y\b", re.I)
_OFFCUT_MIN = 50.0


@dataclass
class StockItem:
    length_mm: float
    width_mm: float
    thickness_mm: float
    qty: int

    def key(self) -> tuple[float, float, float]:
        return (
            round(self.length_mm, 2),
            round(self.width_mm, 2),
            round(self.thickness_mm, 2),
        )

    def section(self) -> tuple[float, float]:
        return (round(self.width_mm, 2), round(self.thickness_mm, 2))


@dataclass
class Site:
    width_mm: float = 0.0
    length_mm: float = 0.0
    min_headroom_mm: float = 0.0
    wall_height_mm: float = 0.0
    house_height_mm: float = 0.0

    def any(self) -> bool:
        return any(
            (self.width_mm, self.length_mm, self.min_headroom_mm, self.wall_height_mm)
        )


@dataclass
class Hints:
    uprights: int = 0
    centres_mm: float = 0.0

    def any(self) -> bool:
        return bool(self.uprights or self.centres_mm)


@dataclass
class Brief:
    stock: list[StockItem] = field(default_factory=list)
    site: Site = field(default_factory=Site)
    hints: Hints = field(default_factory=Hints)
    wants_inventory: bool = False
    wants_design: bool = False


@dataclass
class Check:
    span_mm: float = 0.0
    length_mm: float = 0.0
    mid_underside_mm: float = 0.0
    span_ok: bool = False
    length_ok: bool = False
    headroom_ok: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "span_mm": round(self.span_mm, 2),
            "length_mm": round(self.length_mm, 2),
            "mid_underside_mm": round(self.mid_underside_mm, 2),
            "span_ok": self.span_ok,
            "length_ok": self.length_ok,
            "headroom_ok": self.headroom_ok,
            "notes": list(self.notes),
        }


def scrub(text: str) -> str:
    return _CSI.sub("", text or "")


def clean(text: str) -> str:
    return " ".join(scrub(text).split())


def _qty(raw: str) -> int:
    key = (raw or "").strip().lower()
    if key in _WORDS:
        return _WORDS[key]
    return int(float(key))


def mm(value: float, unit: str | None) -> float:
    u = (unit or "mm").strip().lower()
    n = float(value)
    if u in {"m", "metre", "metres", "meter", "meters"}:
        return n * 1000.0
    if u.startswith("cm"):
        return n * 10.0
    return n


def parse_stock(text: str) -> list[StockItem]:
    raw = clean(text)
    found: list[StockItem] = []
    for hit in _STOCK.finditer(" " + raw):
        item = StockItem(
            length_mm=float(hit.group("l")),
            width_mm=float(hit.group("w")),
            thickness_mm=float(hit.group("t")),
            qty=_qty(hit.group("qty")),
        )
        if item.qty <= 0 or item.length_mm <= 0:
            continue
        merge_stock(found, item)
    return found


def parse_site(text: str) -> Site:
    raw = clean(text)
    site = Site()
    away = _AWAY.search(raw)
    if away:
        site.width_mm = mm(float(away.group(1)), away.group(2))
    along = _LONG.search(raw)
    if along:
        site.length_mm = mm(float(along.group(1)), along.group(2))
    head = _HEADROOM.search(raw)
    if head:
        if head.group(1):
            site.min_headroom_mm = mm(float(head.group(1)), head.group(2))
        else:
            site.min_headroom_mm = mm(float(head.group(3)), head.group(4))
    wall = _WALL_H.search(raw)
    if wall:
        if wall.group(1):
            site.wall_height_mm = mm(float(wall.group(1)), wall.group(2))
        else:
            site.wall_height_mm = mm(float(wall.group(3)), wall.group(4))
    storey = _STOREY.search(raw)
    if storey:
        site.house_height_mm = float(storey.group(1)) * 2800.0
    return site


def parse_hints(text: str) -> Hints:
    raw = clean(text)
    hints = Hints()
    up = _UPRIGHTS.search(raw)
    if up:
        hints.uprights = _qty(up.group(1))
        if up.group(2):
            hints.centres_mm = float(up.group(2))
    if not hints.centres_mm:
        c = _CENTRES.search(raw)
        if c and hints.uprights:
            hints.centres_mm = float(c.group(1))
    return hints


def is_design_request(text: str) -> bool:
    return bool(_DESIGN.search(clean(text)))


def is_inventory_request(text: str) -> bool:
    raw = clean(text)
    return bool(_INVENTORY.search(raw) or parse_stock(raw))


def merge_site(base: Site, over: Site) -> Site:
    out = replace(base)
    for name in ("width_mm", "length_mm", "min_headroom_mm", "wall_height_mm", "house_height_mm"):
        val = getattr(over, name)
        if val:
            setattr(out, name, val)
    return out


def merge_hints(base: Hints, over: Hints) -> Hints:
    out = replace(base)
    if over.uprights:
        out.uprights = over.uprights
    if over.centres_mm:
        out.centres_mm = over.centres_mm
    return out


def merge_stock(stock: list[StockItem], item: StockItem) -> None:
    for row in stock:
        if row.key() == item.key():
            row.qty += item.qty
            return
    stock.append(
        StockItem(item.length_mm, item.width_mm, item.thickness_mm, item.qty)
    )


def stock_from_scene(scene: dict | None) -> list[StockItem]:
    out: list[StockItem] = []
    for raw in (scene or {}).get("stock") or []:
        try:
            item = StockItem(
                length_mm=float(raw["length_mm"]),
                width_mm=float(raw.get("width_mm") or 70),
                thickness_mm=float(raw.get("thickness_mm") or 15),
                qty=int(raw.get("qty") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if item.qty > 0:
            merge_stock(out, item)
    return out


def site_from_scene(scene: dict | None) -> Site:
    raw = (scene or {}).get("site") or {}
    def f(key: str) -> float:
        try:
            return float(raw.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    return Site(
        width_mm=f("width_mm"),
        length_mm=f("length_mm"),
        min_headroom_mm=f("min_headroom_mm"),
        wall_height_mm=f("wall_height_mm"),
        house_height_mm=f("house_height_mm"),
    )


def hints_from_scene(scene: dict | None) -> Hints:
    raw = (scene or {}).get("hints") or {}
    try:
        n = int(raw.get("uprights") or 0)
    except (TypeError, ValueError):
        n = 0
    try:
        c = float(raw.get("centres_mm") or 0)
    except (TypeError, ValueError):
        c = 0.0
    return Hints(uprights=n, centres_mm=c)


def stock_to_scene(stock: list[StockItem]) -> list[dict]:
    rows = [s for s in stock if s.qty > 0]
    rows.sort(key=lambda s: (-s.length_mm, -s.thickness_mm, -s.width_mm))
    return [
        {
            "length_mm": round(s.length_mm, 2),
            "width_mm": round(s.width_mm, 2),
            "thickness_mm": round(s.thickness_mm, 2),
            "qty": int(s.qty),
        }
        for s in rows
    ]


def check_from_scene(scene: dict | None) -> Check:
    raw = (scene or {}).get("check") or {}
    notes = raw.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]
    def f(key: str) -> float:
        try:
            return float(raw.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    return Check(
        span_mm=f("span_mm"),
        length_mm=f("length_mm"),
        mid_underside_mm=f("mid_underside_mm"),
        span_ok=bool(raw.get("span_ok")),
        length_ok=bool(raw.get("length_ok")),
        headroom_ok=bool(raw.get("headroom_ok")),
        notes=[str(n) for n in notes],
    )


def site_to_scene(site: Site) -> dict:
    return {
        "width_mm": round(site.width_mm, 2),
        "length_mm": round(site.length_mm, 2),
        "min_headroom_mm": round(site.min_headroom_mm, 2),
        "wall_height_mm": round(site.wall_height_mm, 2),
        "house_height_mm": round(site.house_height_mm, 2),
    }


def hints_to_scene(hints: Hints) -> dict:
    return {"uprights": int(hints.uprights or 0), "centres_mm": round(hints.centres_mm, 2)}


def parse_brief(text: str, scene: dict | None = None) -> Brief:
    spoken = parse_stock(text)
    site_spoken = parse_site(text)
    hints_spoken = parse_hints(text)
    filed = (scene or {}).get("pile") or (scene or {}).get("stock")
    return Brief(
        stock=spoken or stock_from_scene({"stock": filed}),
        site=merge_site(site_from_scene(scene), site_spoken),
        hints=merge_hints(hints_from_scene(scene), hints_spoken),
        wants_inventory=bool(spoken) or is_inventory_request(text),
        wants_design=is_design_request(text),
    )


def consume(
    stock: list[StockItem],
    length_mm: float,
    *,
    section: tuple[float, float] | None = None,
    prefer_long: bool = False,
) -> StockItem | None:
    """Take one board at least length_mm. Offcuts of 50mm+ go back on the pile."""
    need = float(length_mm)
    best_i = None
    best_key = None
    for i, row in enumerate(stock):
        if row.qty < 1 or row.length_mm + 1e-6 < need:
            continue
        if section is not None and row.section() != section:
            continue
        leftover = row.length_mm - need
        if prefer_long:
            key = (-row.length_mm, leftover, -row.thickness_mm)
        else:
            key = (row.length_mm, leftover, -row.thickness_mm)
        if best_key is None or key < best_key:
            best_key = key
            best_i = i
    if best_i is None:
        return None
    src = stock[best_i]
    src.qty -= 1
    taken = StockItem(need, src.width_mm, src.thickness_mm, 1)
    off = src.length_mm - need
    if off >= _OFFCUT_MIN:
        merge_stock(stock, StockItem(off, src.width_mm, src.thickness_mm, 1))
    if src.qty <= 0:
        stock.pop(best_i)
    return taken


def _rad(deg: float) -> float:
    return math.radians(float(deg or 0))


def _rot_x(a: float, x: float, y: float, z: float) -> tuple[float, float, float]:
    c, s = math.cos(a), math.sin(a)
    return x, y * c - z * s, y * s + z * c


def _rot_y(a: float, x: float, y: float, z: float) -> tuple[float, float, float]:
    c, s = math.cos(a), math.sin(a)
    return x * c + z * s, y, -x * s + z * c


def _rot_z(a: float, x: float, y: float, z: float) -> tuple[float, float, float]:
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c, z


def local_extents(part: dict) -> tuple[float, float, float]:
    """Holder-space box (three.js x, y-up, z) matching bench.js."""
    length = float(part.get("length_mm") or 0)
    width = float(part.get("width_mm") or 0)
    thick = float(part.get("thickness_mm") or 0)
    if part.get("upright"):
        return thick, length, width
    return length, thick, width


def corners_world(part: dict) -> list[tuple[float, float, float]]:
    """Scene-space corners: x along, y across, z up. Euler matches three.js XYZ."""
    sx, sy, sz = local_extents(part)
    rx, ry, rz = (
        _rad(part.get("rx_deg") or 0),
        _rad(part.get("ry_deg") or 0),
        _rad(part.get("rz_deg") or 0),
    )
    ox = float(part.get("x_mm") or 0)
    oy = float(part.get("y_mm") or 0)
    oz = float(part.get("z_mm") or 0)
    out: list[tuple[float, float, float]] = []
    for tx in (0.0, sx):
        for ty in (0.0, sy):
            for tz in (0.0, sz):
                x, y, z = _rot_z(rz, tx, ty, tz)
                x, y, z = _rot_y(ry, x, y, z)
                x, y, z = _rot_x(rx, x, y, z)
                three_x, three_y, three_z = x + ox, y + oz, z + oy
                out.append((three_x, three_z, three_y))
    return out


def aabb(part: dict) -> tuple[float, float, float, float, float, float]:
    pts = corners_world(part)
    xs, ys, zs = zip(*pts)
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def structure_aabb(parts: list[dict]) -> tuple[float, float, float, float, float, float]:
    if not parts:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    box = aabb(parts[0])
    for p in parts[1:]:
        a = aabb(p)
        box = (
            min(box[0], a[0]),
            min(box[1], a[1]),
            min(box[2], a[2]),
            max(box[3], a[3]),
            max(box[4], a[4]),
            max(box[5], a[5]),
        )
    return box


def headroom_at(parts: list[dict], x_mm: float, y_mm: float) -> float:
    """Lowest underside of members over (x,y), ignoring posts that meet the floor."""
    overhead: list[float] = []
    for p in parts:
        xmin, ymin, zmin, xmax, ymax, zmax = aabb(p)
        if xmin - 0.5 <= x_mm <= xmax + 0.5 and ymin - 0.5 <= y_mm <= ymax + 0.5:
            if zmin > 40:
                overhead.append(zmin)
    return min(overhead) if overhead else 0.0


def midpoint_headroom(parts: list[dict], site: Site) -> float:
    if not parts or site.width_mm <= 0:
        return 0.0
    xmin, _ymin, _zmin, xmax, _ymax, _zmax = structure_aabb(parts)
    y = site.width_mm / 2.0
    xs = [xmin, (xmin + xmax) / 2.0, xmax]
    if site.length_mm:
        xs.extend([0.0, site.length_mm / 2.0, min(site.length_mm, xmax)])
    hits = [headroom_at(parts, x, y) for x in xs]
    hits = [h for h in hits if h > 0]
    return min(hits) if hits else 0.0


def check_constraints(parts: list[dict], site: Site) -> Check:
    box = structure_aabb(parts)
    span = max(0.0, box[4] - box[1])
    length = max(0.0, box[3] - box[0])
    mid = midpoint_headroom(parts, site)
    span_lim = site.width_mm if site.width_mm else span
    len_lim = site.length_mm if site.length_mm else length
    head = site.min_headroom_mm
    notes: list[str] = []
    span_ok = span <= span_lim + 0.5 and box[4] <= span_lim + 0.5 and box[1] >= -0.5
    length_ok = length <= len_lim + 0.5 and box[3] <= len_lim + 0.5 and box[0] >= -0.5
    head_ok = (mid + 0.5 >= head) if head else True
    if not span_ok:
        notes.append(
            f"span {span:.0f} mm is outside the {span_lim:.0f} mm alley"
        )
    if not length_ok:
        notes.append(
            f"length {length:.0f} mm is outside the {len_lim:.0f} mm along the alley"
        )
    if head and not head_ok:
        notes.append(
            f"midpoint underside {mid:.0f} mm is under the {head:.0f} mm headroom"
        )
    return Check(
        span_mm=span,
        length_mm=length,
        mid_underside_mm=mid,
        span_ok=span_ok,
        length_ok=length_ok,
        headroom_ok=head_ok,
        notes=notes,
    )


def _spec(
    name: str,
    piece: StockItem,
    *,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    upright: bool = False,
    rx_deg: float = 0.0,
    ry_deg: float = 0.0,
    rz_deg: float = 0.0,
) -> dict:
    return {
        "name": name,
        "length_mm": round(piece.length_mm, 2),
        "width_mm": round(piece.width_mm, 2),
        "thickness_mm": round(piece.thickness_mm, 2),
        "x_mm": round(x_mm, 2),
        "y_mm": round(y_mm, 2),
        "z_mm": round(z_mm, 2),
        "rx_deg": round(rx_deg, 2),
        "ry_deg": round(ry_deg, 2),
        "rz_deg": round(rz_deg, 2),
        "upright": bool(upright),
        "role": name.split()[0],
    }


def _thickest(stock: list[StockItem], n: int) -> StockItem | None:
    rows = [s for s in stock if s.qty >= n]
    if not rows:
        rows = [s for s in stock if s.qty >= 1]
    if not rows:
        return None
    rows.sort(key=lambda s: (s.thickness_mm, s.width_mm, s.length_mm, s.qty), reverse=True)
    return rows[0]


def _longest_span(stock: list[StockItem], need: float) -> StockItem | None:
    rows = [s for s in stock if s.qty >= 1]
    if not rows:
        return None
    fit = [s for s in rows if s.length_mm + 1e-6 >= need]
    pool = fit or rows
    pool.sort(key=lambda s: (s.length_mm, s.thickness_mm, s.width_mm), reverse=True)
    return pool[0]


def layout(brief: Brief) -> tuple[list[dict], list[StockItem], Check, list[str]]:
    """Place a frame in the alley from stock. Does not invent timber."""
    stock = [
        StockItem(s.length_mm, s.width_mm, s.thickness_mm, s.qty) for s in brief.stock
    ]
    site = brief.site
    hints = brief.hints
    notes: list[str] = []
    parts: list[dict] = []
    if not stock:
        check = Check(notes=["no stock on file"])
        return parts, stock, check, ["I haven't got the timber sizes, sir."]
    if site.width_mm <= 0:
        check = Check(notes=["no alley width"])
        return parts, stock, check, ["How wide is the alley, sir?"]

    n = int(hints.uprights or 3)
    n = max(2, min(n, 8))
    span = site.width_mm
    depth = site.length_mm or max((n - 1) * (hints.centres_mm or 333.0), 1000.0)
    head = site.min_headroom_mm or site.wall_height_mm or 0.0
    wall_h = site.wall_height_mm or head
    asked_centres = float(hints.centres_mm or 0)

    post_src = _thickest(stock, n)
    if post_src is None:
        check = Check(notes=["no posts"])
        return parts, stock, check, ["Not enough timber for posts, sir."]
    post_section = post_src.section()
    post_len = post_src.length_mm
    splice_len = 0.0
    if head and post_len + 0.5 < head:
        splice_len = round(head - post_len, 2)

    posts: list[StockItem] = []
    splices: list[StockItem] = []
    for _ in range(n):
        taken = consume(stock, post_len, section=post_section, prefer_long=True)
        if taken is None:
            taken = consume(stock, post_len, prefer_long=True)
        if taken is None:
            check = Check(notes=["ran out of posts"])
            return [], [s for s in brief.stock], check, [
                "Not enough lengths for those uprights, sir."
            ]
        posts.append(taken)
    if splice_len > 0:
        for i in range(n):
            taken = consume(stock, splice_len, section=posts[i].section())
            if taken is None:
                taken = consume(stock, splice_len)
            if taken is None:
                splice_len = 0.0
                splices = []
                notes.append(
                    f"Could not splice the posts to {head:.0f} mm; they stay {post_len:.0f} mm."
                )
                break
            splices.append(taken)
        else:
            notes.append(
                f"{n} posts at {post_len:.0f} mm, each spliced with {splice_len:.0f} mm to {head:.0f} mm."
            )
    post_h = post_len + (splice_len if splices else 0.0)

    plate_len = depth
    house_plate = consume(stock, plate_len, section=post_section)
    if house_plate is None:
        house_plate = consume(stock, plate_len)
    wall_plate = consume(stock, plate_len, section=post_section)
    if wall_plate is None:
        wall_plate = consume(stock, plate_len)

    rafter_need = span
    rafter_src = _longest_span(stock, rafter_need)
    if rafter_src is None:
        check = Check(notes=["no rafters"])
        return [], [s for s in brief.stock], check, ["Nothing left for rafters, sir."]
    if rafter_src.length_mm + 1e-6 < rafter_need:
        rafter_need = min(span, rafter_src.length_mm)
        notes.append(
            f"Longest leftover is {rafter_src.length_mm:.0f} mm; span is {rafter_need:.0f} mm."
        )

    post_t = posts[0].thickness_mm
    rafter_w = rafter_src.width_mm
    along = max(post_t, rafter_w)
    if asked_centres:
        centres = asked_centres
        xs = [i * centres for i in range(n)]
        if xs[-1] + along > depth + 0.5:
            span_x = max(depth - along, 0.0)
            xs = [i * span_x / (n - 1) for i in range(n)] if n > 1 else [0.0]
            notes.append(f"Tightened centres to fit the {depth:.0f} mm length.")
        else:
            notes.append(f"{n} uprights at {centres:.0f} mm centres.")
    else:
        span_x = max(depth - along, 0.0)
        centres = span_x / (n - 1) if n > 1 else depth
        xs = [i * centres for i in range(n)] if n > 1 else [0.0]

    rafter_xs = [x for x in xs if x + rafter_w <= depth + 0.5]
    extra = asked_centres or centres
    x_next = (rafter_xs[-1] + extra) if rafter_xs else 0.0
    while x_next + rafter_w <= depth + 0.5:
        rafter_xs.append(x_next)
        x_next += extra

    rafters: list[tuple[float, StockItem]] = []
    for x in rafter_xs:
        taken = consume(stock, rafter_need)
        if taken is None:
            break
        rafters.append((x, taken))
    if not rafters:
        check = Check(notes=["no rafters"])
        return [], [s for s in brief.stock], check, ["Nothing left for rafters, sir."]

    plate_z = post_h
    if wall_h and plate_z > wall_h + 0.5:
        notes.append(
            f"Posts reach {plate_z:.0f} mm; the garden wall is {wall_h:.0f} mm — plate sits on the wall cap."
        )
        plate_z = wall_h
    rafter_z = plate_z
    if house_plate:
        rafter_z = plate_z + house_plate.thickness_mm
    elif wall_plate:
        rafter_z = plate_z + wall_plate.thickness_mm

    for i, piece in enumerate(posts):
        x = xs[i]
        parts.append(
            _spec(
                f"post {i + 1}",
                piece,
                x_mm=x,
                y_mm=0.0,
                z_mm=0.0,
                upright=True,
            )
        )
        if i < len(splices):
            parts.append(
                _spec(
                    f"splice {i + 1}",
                    splices[i],
                    x_mm=x,
                    y_mm=0.0,
                    z_mm=piece.length_mm,
                    upright=True,
                )
            )

    if house_plate:
        parts.append(
            _spec(
                "house plate",
                house_plate,
                x_mm=0.0,
                y_mm=0.0,
                z_mm=plate_z,
            )
        )
    if wall_plate:
        y = max(0.0, span - wall_plate.width_mm)
        parts.append(
            _spec(
                "wall plate",
                wall_plate,
                x_mm=0.0,
                y_mm=y,
                z_mm=plate_z,
            )
        )

    for i, (x, piece) in enumerate(rafters):
        # ry = -90°: length runs +Y. Width runs -X in holder space, so
        # origin sits at station + width to keep the board in +X.
        parts.append(
            _spec(
                f"rafter {i + 1}",
                piece,
                x_mm=x + piece.width_mm,
                y_mm=0.0,
                z_mm=rafter_z,
                ry_deg=-90.0,
            )
        )

    check = check_constraints(parts, site)
    if check.headroom_ok and check.span_ok and check.length_ok:
        notes.append(
            f"Midpoint underside {check.mid_underside_mm:.0f} mm; "
            f"span {check.span_mm:.0f} mm inside the {span:.0f} mm alley; "
            f"length {check.length_mm:.0f} mm."
        )
    notes.extend(check.notes)
    return parts, stock, check, notes


def format_stock(stock: list[StockItem]) -> str:
    rows = [s for s in stock if s.qty > 0]
    if not rows:
        return "none"
    bits = []
    for s in stock_to_scene(rows):
        n = int(s["qty"])
        bits.append(
            f"{n}× {s['length_mm']:.0f}×{s['width_mm']:.0f}×{s['thickness_mm']:.0f}"
        )
    return ", ".join(bits)


def speak_design(check: Check, notes: list[str], remaining: list[StockItem]) -> str:
    left = format_stock(remaining)
    if not check.headroom_ok or not check.span_ok or not check.length_ok:
        why = "; ".join(check.notes) or "the checks did not all pass"
        return (
            f"It's on the bench, sir, but {why}. "
            f"Stock left: {left}."
        )
    story = next((n for n in notes if n[0].isdigit() or n[:2].lower() == "th"), "")
    mid = (
        f"Midpoint underside {check.mid_underside_mm:.0f} millimetres, "
        f"span {check.span_mm:.0f} inside the alley."
    )
    if story:
        return f"On the bench, sir. {story} {mid} Left: {left}."
    return f"On the bench, sir. {mid} Left: {left}."


def speak_stock(stock: list[StockItem], site: Site) -> str:
    pile = format_stock(stock)
    extra = []
    if site.width_mm:
        extra.append(f"alley {site.width_mm:.0f} mm across")
    if site.length_mm:
        extra.append(f"{site.length_mm:.0f} mm along")
    if site.min_headroom_mm:
        extra.append(f"{site.min_headroom_mm:.0f} mm headroom at the midpoint")
    tail = "; ".join(extra)
    if tail:
        return f"Stock on file, sir: {pile}. {tail.capitalize()}."
    return f"Stock on file, sir: {pile}."
