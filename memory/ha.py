"""Home Assistant on the LAN. Token never goes in the vault, jobs, or Grok.

Same-network REST. Outside-network access is a later proxy on the Pi;
this module only reads ~/.jarvis/secrets (or JARVIS_HA_TOKEN).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from memory.home import JarvisHome

DEFAULT_URL = "http://homeassistant.local:8123"
PENDING_S = 90
TIMEOUT_S = 8
ACTUATE_DOMAINS = frozenset(
    {"light", "switch", "lock", "cover", "climate", "fan", "alarm_control_panel"}
)
CONFIRM_ACTIONS = frozenset({"unlock", "open", "lock", "close", "disarm", "arm"})

_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|confirm|do it|proceed|go ahead)"
    r"(?:\s+(?:please|sir|jarvis))*[.!]?$",
    re.I,
)
_NO = re.compile(
    r"^(?:no|nope|cancel|stop|don't|do not|never mind|no thanks)"
    r"(?:\s+(?:please|sir|jarvis))*[.!]?$",
    re.I,
)
_ON = re.compile(
    r"\b(?:turn(?:ed)?\s+on|switch(?:ed)?\s+on|put\s+on|lights?\s+on|lamps?\s+on)\b",
    re.I,
)
_OFF = re.compile(
    r"\b(?:turn(?:ed)?\s+off|switch(?:ed)?\s+off|shut\s+off|lights?\s+off|lamps?\s+off)\b",
    re.I,
)
_TURN_TAIL = re.compile(
    r"\bturn\s+(?:the\s+)?(?:\w+\s+){0,3}"
    r"(?:lights?|lamps?|heating|lock|garage|thermostat)\s+(on|off)\b",
    re.I,
)
_UNLOCK = re.compile(r"\bunlock", re.I)
_LOCK = re.compile(r"(?<!un)\block\b", re.I)
_OPEN = re.compile(r"\bopen\b", re.I)
_CLOSE = re.compile(r"\b(?:close|shut)\b", re.I)
_QUERY = re.compile(
    r"\b(?:is|are|how's|how is|status|what(?:'s| is)(?: the)?)\b", re.I
)
_SET = re.compile(
    r"\b(?:set|make|change)\b.*?\b(?:to|at)\s+(\d{1,2}(?:\.\d)?)\b",
    re.I,
)
_TEMP = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*(?:degrees?|c(?:elsius)?)\b", re.I)
_PCT = re.compile(r"\b(\d{1,3})\s*(?:%|percent)\b", re.I)
_ALL = re.compile(r"\ball\b", re.I)
_TOO_BRIGHT = re.compile(
    r"\b(?:(?:too|so|still|quite|rather|pretty|very|a little|a bit)\s+bright|"
    r"blinding|glaring|(?:way )?too much light|bright in)\b",
    re.I,
)
_TOO_DARK = re.compile(
    r"\b(?:(?:too|so|still|quite|rather|pretty|very|a little|a bit)\s+dark|"
    r"pitch black|can'?t see|cannot see|not bright enough|too dim|dark in)\b",
    re.I,
)
_DIM = re.compile(
    r"\b(?:dim(?:mer)?|darken|lights?\s+down|"
    r"turn(?:\s+the)?(?:\s+\w+){0,4}\s+down|"
    r"lower(?:\s+the)?\s+lights?)\b",
    re.I,
)
_BRIGHTEN = re.compile(
    r"\b(?:brighten|brighter|lights?\s+up|"
    r"turn(?:\s+the)?(?:\s+\w+){0,4}\s+up)\b",
    re.I,
)
_LIST = re.compile(
    r"\b(?:what(?:'s|s| is| are)?|which|list)\b.{0,40}"
    r"\b(?:lights?|lamps?|devices?|switches|house)\b",
    re.I,
)
_SKIP_ENTITY = re.compile(
    r"auto[_-]?update|do_not_disturb|motion_detection|announcements|"
    r"communications|cloud_connection|overheated|smooth_on|smooth_off|"
    r"light_preset|firmware",
    re.I,
)
_AREA_TEMPLATE = (
    "{% for s in states %}{{ s.entity_id }}|{{ area_name(s.entity_id) }}\n{% endfor %}"
)
DIM_PCT = 30
BRIGHT_PCT = 80
LOW_BRIGHT_PCT = 40

_NOUN_DOMAIN = (
    (re.compile(r"\b(?:lights?|lamps?)\b", re.I), "light"),
    (re.compile(r"\b(?:outlets?|plugs?|switches)\b", re.I), "switch"),
    (re.compile(r"\b(?:locks?|deadbolt)\b", re.I), "lock"),
    (re.compile(r"\b(?:garage|gate)\b", re.I), "cover"),
    (re.compile(r"\b(?:blinds?|curtains?|covers?)\b", re.I), "cover"),
    (re.compile(r"\bdoors?\b", re.I), "lock"),
    (re.compile(r"\b(?:thermostat|heating|boiler|radiator)\b", re.I), "climate"),
    (re.compile(r"\balarm\b", re.I), "alarm_control_panel"),
)

_AREAS = (
    "kitchen",
    "lounge",
    "living",
    "sitting",
    "hall",
    "hallway",
    "landing",
    "bedroom",
    "bathroom",
    "ensuite",
    "office",
    "study",
    "garage",
    "garden",
    "porch",
    "dining",
    "downstairs",
    "upstairs",
    "conservatory",
    "utility",
    "cloakroom",
    "front",
    "back",
    "guest",
    "spare",
    "entrance",
    "jak",
    "jack",
    "bear",
    "master",
)

_AREA_ALIASES: dict[str, tuple[str, ...]] = {
    "living": ("living", "lounge", "sitting"),
    "lounge": ("living", "lounge", "sitting"),
    "sitting": ("living", "lounge", "sitting"),
    "garden": ("garden", "back"),
    "back": ("garden", "back"),
    "hall": ("hall", "hallway"),
    "hallway": ("hall", "hallway"),
    "entrance": ("entrance", "front", "porch"),
    "front": ("front", "entrance"),
    "jak": ("jak", "jack"),
    "jack": ("jak", "jack"),
    "bear": ("bear", "annabelle"),
    "bedroom": ("bedroom", "master"),
    "master": ("master", "bedroom"),
}

_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "on",
        "off",
        "please",
        "jarvis",
        "job",
        "sir",
        "my",
        "me",
        "in",
        "of",
        "for",
        "is",
        "are",
        "it",
        "that",
        "this",
        "some",
        "all",
        "let",
        "turn",
        "turned",
        "switch",
        "switched",
        "put",
        "room",
        "rooms",
        "light",
        "lights",
        "lamp",
        "lamps",
        "home",
        "assistant",
        "house",
        "named",
        "called",
        "can",
        "you",
        "now",
        "just",
        "and",
        "or",
        "with",
        "from",
        "too",
        "bright",
        "brighter",
        "brightness",
        "dark",
        "darker",
        "dim",
        "dimmer",
        "blinding",
        "glare",
        "glaring",
        "harsh",
        "percent",
        "down",
        "up",
        "make",
        "set",
        "change",
        "what",
        "which",
        "list",
        "have",
        "devices",
        "device",
        "little",
        "still",
        "quite",
        "rather",
        "pretty",
        "very",
        "somewhat",
        "really",
        "bit",
    }
)


def _fold(text: str) -> str:
    t = (text or "").lower()
    for ch in "'`´\u2018\u2019":
        t = t.replace(ch, "")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _stem(tok: str) -> str:
    t = _fold(tok)
    if len(t) > 3 and t.endswith("s"):
        t = t[:-1]
    if t in {"jack", "jak", "jac"}:
        return "jak"
    return t


def _stems(text: str) -> set[str]:
    return {_stem(tok) for tok in _fold(text).split() if _stem(tok)}


def _close(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) >= 3 and abs(len(a) - len(b)) <= 2:
        return a.startswith(b) or b.startswith(a)
    return False


def _area_of(ent: dict) -> str:
    attrs = ent.get("attributes") or {}
    return str(attrs.get("area") or ent.get("area") or "").strip()


def _entity_stems(ent: dict) -> set[str]:
    eid = str(ent.get("entity_id") or "")
    return _stems(
        _label(ent)
        + " "
        + eid.replace(".", " ").replace("_", " ")
        + " "
        + _area_of(ent)
    )


def _hint_score(hint: str, ent: dict) -> int:
    hs = _stem(hint)
    if not hs:
        return 0
    keys = _entity_stems(ent)
    if hs in keys:
        return 10
    if any(_close(hs, k) for k in keys):
        return 8
    return 0


def utterance_hints(raw: str) -> list[str]:
    hints: list[str] = []
    if re.search(r"\blamps?\b", raw, re.I):
        hints.append("lamp")
    for tok in _fold(raw).split():
        if not tok or tok in _STOP or len(tok) < 3:
            continue
        stem = _stem(tok)
        if not stem or stem in _STOP or len(stem) < 3:
            continue
        if stem not in hints:
            hints.append(stem)
    return hints


class HATransport(Protocol):
    def get_states(self) -> list[dict]: ...
    def call_service(self, domain: str, service: str, data: dict) -> Any: ...


@dataclass
class HouseCommand:
    action: str
    domain: str | None
    area: str | None
    all_of: bool = False
    temperature: float | None = None
    brightness: int | None = None
    hints: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()


HouseMapper = Callable[[str, list[dict]], "HouseCommand | None"]


class HAError(RuntimeError):
    pass


def secrets_dir(home: JarvisHome) -> Path:
    return home.root / "secrets"


def token_path(home: JarvisHome) -> Path:
    return secrets_dir(home) / "ha.token"


def config_path(home: JarvisHome) -> Path:
    return secrets_dir(home) / "ha.json"


def pending_path(home: JarvisHome) -> Path:
    return home.cache / "ha-pending.json"


def clarify_path(home: JarvisHome) -> Path:
    return home.cache / "ha-clarify.json"


def _yesno_norm(text: str) -> str:
    t = re.sub(r"[,.!?]", " ", text or "")
    return " ".join(t.split())


def is_yes(text: str) -> bool:
    return bool(_YES.match(_yesno_norm(text)))


def is_no(text: str) -> bool:
    return bool(_NO.match(_yesno_norm(text)))


def load_url(home: JarvisHome) -> str:
    env = os.environ.get("JARVIS_HA_URL")
    if env:
        return env.rstrip("/")
    path = config_path(home)
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = {}
        url = str(doc.get("url") or "").strip()
        if url:
            return url.rstrip("/")
    return DEFAULT_URL


def load_token(home: JarvisHome) -> str:
    env = os.environ.get("JARVIS_HA_TOKEN") or os.environ.get("HA_TOKEN")
    if env:
        return env.strip()
    path = token_path(home)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def pending_confirm(home: JarvisHome) -> dict | None:
    path = pending_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = float(doc.get("ts") or 0)
    if time.time() - ts > PENDING_S:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return doc if isinstance(doc, dict) else None


def _write_pending(home: JarvisHome, doc: dict) -> None:
    home.cache.mkdir(parents=True, exist_ok=True)
    pending_path(home).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _clear_pending(home: JarvisHome) -> None:
    try:
        pending_path(home).unlink()
    except OSError:
        pass


def pending_clarify(home: JarvisHome) -> dict | None:
    path = clarify_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = float(doc.get("ts") or 0)
    if time.time() - ts > PENDING_S:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return doc if isinstance(doc, dict) else None


def _write_clarify(home: JarvisHome, prompt: str) -> None:
    home.cache.mkdir(parents=True, exist_ok=True)
    clarify_path(home).write_text(
        json.dumps({"ts": time.time(), "prompt": prompt}) + "\n",
        encoding="utf-8",
    )


def _clear_clarify(home: JarvisHome) -> None:
    try:
        clarify_path(home).unlink()
    except OSError:
        pass


def is_house_followup(text: str) -> bool:
    t = " ".join((text or "").split()).strip(" .!")
    if not t:
        return False
    areas = "|".join(re.escape(a) for a in _AREAS)
    if re.match(
        rf"^(?:the\s+)?(?:{areas})(?:\s+(?:room|one|lights?|lamps?|please))*$",
        t,
        re.I,
    ):
        return True
    if re.search(r"\b(?:lamp|lights?|living\s+room)\b", t, re.I):
        return True
    if re.search(r"\b\w{3,}(?:['’]s)?\s+(?:room|light|lamp)s?\b", t, re.I):
        return True
    return False


class RestHA:
    def __init__(self, url: str, token: str, timeout: float = TIMEOUT_S):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            if exc.code == 401:
                raise HAError("Home Assistant rejected the token.") from exc
            raise HAError(f"Home Assistant HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise HAError(f"Home Assistant unreachable: {exc.reason}") from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    def ping(self) -> dict:
        return self._req("GET", "/api/")

    def get_states(self) -> list[dict]:
        val = self._req("GET", "/api/states")
        return val if isinstance(val, list) else []

    def call_service(self, domain: str, service: str, data: dict) -> Any:
        return self._req("POST", f"/api/services/{domain}/{service}", data)

    def area_map(self) -> dict[str, str]:
        val = self._req("POST", "/api/template", {"template": _AREA_TEMPLATE})
        text = val.get("raw") if isinstance(val, dict) else str(val or "")
        out: dict[str, str] = {}
        for line in str(text or "").splitlines():
            if "|" not in line:
                continue
            eid, area = line.split("|", 1)
            eid, area = eid.strip(), area.strip()
            if eid and area and area.lower() not in {"none", "null"}:
                out[eid] = area
        return out


def parse_command(text: str) -> HouseCommand | None:
    raw = " ".join((text or "").split())
    if not raw:
        return None
    domain = None
    for rx, dom in _NOUN_DOMAIN:
        if rx.search(raw):
            domain = dom
            break
    area = None
    low = raw.lower()
    for name in _AREAS:
        if re.search(rf"\b{re.escape(name)}\b", low):
            area = name
            break
    temp = None
    mset = _SET.search(raw) or _TEMP.search(raw)
    if mset:
        try:
            temp = float(mset.group(1))
        except (TypeError, ValueError):
            temp = None
    brightness = None
    mpct = _PCT.search(raw)
    if mpct:
        try:
            brightness = int(mpct.group(1))
        except (TypeError, ValueError):
            brightness = None
        if brightness is not None and not 0 <= brightness <= 100:
            brightness = None
    action = ""
    tail = _TURN_TAIL.search(raw)
    listing = bool(_LIST.search(raw))
    if _TOO_BRIGHT.search(raw):
        action = "dim"
    elif _TOO_DARK.search(raw):
        action = "brighten"
    elif listing or re.match(
        r"^(?:is|are|what|how's|how is|status|which|list)\b", raw, re.I
    ):
        action = "query"
    elif _UNLOCK.search(raw):
        action = "unlock"
    elif _LOCK.search(raw):
        action = "lock"
    elif _ON.search(raw) or (tail and tail.group(1).lower() == "on"):
        action = "on"
    elif _OFF.search(raw) or (tail and tail.group(1).lower() == "off"):
        action = "off"
    elif _DIM.search(raw):
        action = "dim"
    elif _BRIGHTEN.search(raw):
        action = "brighten"
    elif brightness is not None and (domain == "light" or area):
        action = "dim" if brightness < 100 else "brighten"
        if brightness == 0:
            action = "off"
    elif _OPEN.search(raw):
        action = "open"
    elif _CLOSE.search(raw):
        action = "off" if domain == "light" else "close"
    elif temp is not None or (domain == "climate" and re.search(r"\bset\b", raw, re.I)):
        action = "set"
    elif _QUERY.search(raw) or re.search(r"\b(?:how|what)\b", raw, re.I):
        action = "query"
    if not action:
        return None
    if not domain:
        if action in ("on", "off", "dim", "brighten"):
            domain = "light"
        elif action in ("lock", "unlock"):
            domain = "lock"
        elif action in ("open", "close") and area == "garage":
            domain = "cover"
        elif action == "set":
            domain = "climate"
        elif action == "query" and listing:
            domain = "light"
    if action == "dim" and brightness is None:
        brightness = DIM_PCT
    if action == "brighten" and brightness is None:
        brightness = BRIGHT_PCT
    return HouseCommand(
        action=action,
        domain=domain,
        area=area,
        all_of=bool(_ALL.search(raw)) or listing,
        temperature=temp,
        brightness=brightness,
        hints=tuple(utterance_hints(raw)),
    )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _label(ent: dict) -> str:
    attrs = ent.get("attributes") or {}
    name = str(attrs.get("friendly_name") or "").strip()
    return name or str(ent.get("entity_id") or "").replace("_", " ")


def _blob(ent: dict) -> str:
    eid = str(ent.get("entity_id") or "")
    return _norm(
        _label(ent)
        + " "
        + eid.replace(".", " ").replace("_", " ")
        + " "
        + _area_of(ent)
    )


def _area_hit(cmd_area: str, ent: dict) -> bool:
    if not cmd_area:
        return False
    aliases = _AREA_ALIASES.get(cmd_area, (cmd_area,))
    area_fold = _fold(_area_of(ent))
    if area_fold:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", area_fold):
                return True
    blob = _blob(ent)
    if re.search(rf"\b{re.escape(cmd_area)}\b", blob):
        return True
    return False


def _junk(ent: dict) -> bool:
    eid = str(ent.get("entity_id") or "")
    return bool(_SKIP_ENTITY.search(eid) or _SKIP_ENTITY.search(_blob(ent)))


def _compatible(domain: str, want: str | None) -> bool:
    if not want:
        return domain in ACTUATE_DOMAINS
    if domain == want:
        return True
    if want == "light" and domain == "switch":
        return True
    if want == "lock" and domain in {"cover", "lock"}:
        return True
    if want == "cover" and domain in {"cover", "lock"}:
        return True
    return False


def resolve_entities(states: list[dict], cmd: HouseCommand) -> list[dict]:
    if cmd.entity_ids:
        want = set(cmd.entity_ids)
        return [e for e in states if str(e.get("entity_id") or "") in want]
    scored: list[tuple[int, dict]] = []
    for ent in states:
        eid = str(ent.get("entity_id") or "")
        domain = eid.split(".", 1)[0]
        if _junk(ent) and cmd.action != "query":
            continue
        if cmd.action != "query" and domain not in ACTUATE_DOMAINS:
            continue
        if cmd.action == "query" and domain not in ACTUATE_DOMAINS | {
            "binary_sensor",
            "sensor",
            "media_player",
            "camera",
        }:
            continue
        if _junk(ent) and cmd.action == "query" and domain != "light":
            continue
        if cmd.action == "query" and domain in {"binary_sensor", "sensor"}:
            if not (cmd.area and _area_hit(cmd.area, ent)):
                continue
        elif not _compatible(domain, cmd.domain):
            continue
        if cmd.domain == "light" and domain == "switch" and cmd.action != "query":
            continue
        blob = _blob(ent)
        score = 0
        if cmd.area and _area_hit(cmd.area, ent):
            score += 8
        elif cmd.area and cmd.area in blob:
            score += 6
        if cmd.domain and domain == cmd.domain:
            score += 2
        if cmd.domain == "cover" and "garage" in blob:
            score += 3
        for hint in cmd.hints:
            score += _hint_score(hint, ent)
        if cmd.action in ("dim", "brighten") and domain == "light":
            score += 1
        if score <= 0 and not cmd.all_of:
            if cmd.area:
                continue
            score = 1 if domain == cmd.domain else 0
        if score > 0:
            scored.append((score, ent))
    scored.sort(key=lambda row: (-row[0], row[1].get("entity_id") or ""))
    if not scored:
        return []
    if cmd.all_of:
        top = scored[0][0]
        return [e for s, e in scored if s >= max(1, top - 2)]
    best = scored[0][0]
    tied = [e for s, e in scored if s == best]
    lighting = cmd.action in ("on", "off", "dim", "brighten")
    if not cmd.area:
        if len(tied) == 1:
            return tied
        if cmd.hints:
            hinted = [
                e
                for s, e in scored
                if any(_hint_score(h, e) > 0 for h in cmd.hints)
            ]
            if len(hinted) == 1:
                return hinted
        if lighting and not cmd.hints:
            return []
        if cmd.action == "query" and cmd.domain:
            return [e for s, e in scored if s >= 1][:12]
        return tied if len(tied) == 1 else []
    if lighting and cmd.domain in {"light", "switch"}:
        picked = [e for s, e in scored if s >= best - 2][:8]
        if cmd.action in ("dim", "brighten"):
            on = [e for e in picked if str(e.get("state")) == "on"]
            if on and cmd.action == "dim":
                return on
        return picked
    return [e for s, e in scored if s == best]


def _service(cmd: HouseCommand, domain: str) -> tuple[str, dict]:
    if cmd.action == "on":
        return "turn_on", {}
    if cmd.action == "off":
        return "turn_off", {}
    if cmd.action == "dim":
        pct = DIM_PCT if cmd.brightness is None else cmd.brightness
        return "turn_on", {"brightness_pct": pct}
    if cmd.action == "brighten":
        pct = BRIGHT_PCT if cmd.brightness is None else cmd.brightness
        return "turn_on", {"brightness_pct": pct}
    if cmd.action == "lock":
        return "lock", {}
    if cmd.action == "unlock":
        return "unlock", {}
    if cmd.action == "open":
        if domain == "cover":
            return "open_cover", {}
        return "unlock", {}
    if cmd.action == "close":
        if domain == "cover":
            return "close_cover", {}
        return "lock", {}
    if cmd.action == "set":
        data: dict = {}
        if cmd.temperature is not None:
            data["temperature"] = cmd.temperature
        return "set_temperature", data
    raise HAError(f"no service for {cmd.action}")


def _can_dim(ent: dict) -> bool:
    attrs = ent.get("attributes") or {}
    modes = list(attrs.get("supported_color_modes") or [])
    if modes == ["onoff"]:
        return False
    if attrs.get("brightness") is not None:
        return True
    return any(
        m in modes
        for m in (
            "brightness",
            "color_temp",
            "hs",
            "xy",
            "rgb",
            "rgbw",
            "rgbww",
            "white",
        )
    )


def _brightness_pct(ent: dict) -> int | None:
    attrs = ent.get("attributes") or {}
    if str(ent.get("state")) != "on":
        return 0
    raw = attrs.get("brightness_pct")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    bri = attrs.get("brightness")
    if bri is not None:
        try:
            return int(round(int(bri) * 100 / 255))
        except (TypeError, ValueError):
            return None
    return 100 if _can_dim(ent) else None


def _needs_confirm(action: str, domain: str) -> bool:
    if action not in CONFIRM_ACTIONS:
        return False
    return domain in {"lock", "cover", "alarm_control_panel"}


def _state_phrase(ent: dict) -> str:
    state = str(ent.get("state") or "unknown")
    label = _label(ent)
    attrs = ent.get("attributes") or {}
    if str(ent.get("entity_id") or "").startswith("climate."):
        temp = attrs.get("current_temperature")
        target = attrs.get("temperature")
        extra = []
        if temp is not None:
            extra.append(f"{temp}°")
        if target is not None:
            extra.append(f"set to {target}°")
        more = ", ".join(str(x) for x in extra)
        return f"{label} is {state}" + (f" ({more})" if more else "")
    pretty = {
        "on": "on",
        "off": "off",
        "locked": "locked",
        "unlocked": "unlocked",
        "open": "open",
        "closed": "closed",
        "opening": "opening",
        "closing": "closing",
    }.get(state, state)
    return f"{label} is {pretty}"


def _list_names(ents: list[dict], conj: str = "or") -> str:
    names = [_label(e) for e in ents[:3]]
    if len(ents) > 3:
        names.append("more")
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" {conj} " + names[-1]


def _client(home: JarvisHome, transport: HATransport | None) -> HATransport:
    if transport is not None:
        return transport
    token = load_token(home)
    if not token:
        raise HAError(
            "No Home Assistant token. In HA: profile (bottom left) → Security → "
            "Long-lived access tokens. Save the token as one line in "
            f"{token_path(home)}."
        )
    return RestHA(load_url(home), token)


def _confident_parse(cmd: HouseCommand | None) -> bool:
    """Local parse is enough; skip Grok. Explicit on/off/lock, not 'is it dark'."""
    if cmd is None:
        return False
    if cmd.entity_ids:
        return True
    if cmd.action in ("unlock", "lock", "open", "close"):
        return True
    if cmd.action == "set" and cmd.temperature is not None:
        return True
    if cmd.action in ("on", "off") and (cmd.area or cmd.hints or cmd.all_of):
        return True
    if cmd.action in ("dim", "brighten") and (cmd.area or cmd.hints):
        return True
    if cmd.action == "query" and (
        cmd.all_of or cmd.domain in {"cover", "lock", "climate"}
    ):
        return True
    return False


def run_home(
    home: JarvisHome,
    snap: dict,
    transport: HATransport | None = None,
    mapper: HouseMapper | None = None,
) -> tuple[str, str]:
    """Execute a house job. Returns (speak, result). Never logs the token."""
    if "confirm" in snap:
        return _finish_confirm(home, bool(snap.get("confirm")), transport)
    prompt = str(snap.get("prompt") or "").strip()
    prior = pending_clarify(home)
    cmd = parse_command(prompt)
    if prior and (cmd is None or (not cmd.area and is_house_followup(prompt))):
        prompt = str(prior.get("prompt") or "") + " " + prompt
        cmd = parse_command(prompt)
    try:
        client = _client(home, transport)
        states = client.get_states()
    except HAError as exc:
        return str(exc), "ha-error"
    _attach_areas(client, states)
    _store_roster(home, states)
    if mapper is not None and not _confident_parse(cmd):
        mapped = mapper(prompt, roster_rows(states))
        if mapped is not None:
            cmd = mapped
    if cmd is None:
        return "I didn't catch which house action, sir.", "unparsed"
    _clear_clarify(home)
    ents = resolve_entities(states, cmd)
    if not ents and mapper is not None and not cmd.entity_ids:
        mapped = mapper(prompt, roster_rows(states))
        if mapped is not None:
            cmd = mapped
            ents = resolve_entities(states, cmd)
    if not ents:
        if (
            cmd.action in ("on", "off", "dim", "brighten")
            and not cmd.area
            and not cmd.all_of
        ):
            _write_clarify(home, prompt)
            return "Which lights, sir? Name the room.", "ambiguous"
        return "I couldn't find that in the house, sir.", "none"
    if cmd.action == "query":
        shown = ents
        if re.search(r"\bare on\b", prompt, re.I):
            on = [e for e in ents if str(e.get("state")) == "on"]
            if not on:
                return "No lights are on, sir.", "query"
            shown = on
        limit = 8 if cmd.all_of else 4
        phrase = "; ".join(_state_phrase(e) for e in shown[:limit])
        if len(shown) > limit:
            phrase += f"; {len(shown) - limit} more"
        return f"{phrase}, sir.", "query"
    lighting = cmd.action in ("on", "off", "dim", "brighten")
    if not cmd.area and not cmd.all_of and lighting and len(ents) > 1:
        _write_clarify(home, prompt)
        return f"Which lights, sir? {_list_names(ents)}.", "ambiguous"
    domain = str(ents[0].get("entity_id") or "light").split(".", 1)[0]
    if _needs_confirm(cmd.action, domain):
        try:
            service, data = _service(cmd, domain)
        except HAError as exc:
            return str(exc), "bad-action"
        ids = [str(e.get("entity_id")) for e in ents]
        _write_pending(
            home,
            {
                "ts": time.time(),
                "domain": domain,
                "service": service,
                "entity_id": ids if len(ids) > 1 else ids[0],
                "label": _list_names(ents, "and"),
                "action": cmd.action,
            },
        )
        return (
            f"{cmd.action.capitalize()} {_list_names(ents)}, sir? Say yes to confirm.",
            "needs-confirm",
        )
    return _act(client, cmd, ents)


def _finish_confirm(
    home: JarvisHome,
    yes: bool,
    transport: HATransport | None,
) -> tuple[str, str]:
    pending = pending_confirm(home)
    if not pending:
        return "Nothing to confirm, sir.", "no-pending"
    _clear_pending(home)
    if not yes:
        return "Cancelled, sir.", "cancelled"
    try:
        client = _client(home, transport)
        domain = str(pending.get("domain") or "")
        service = str(pending.get("service") or "")
        eid = pending.get("entity_id")
        data = {"entity_id": eid}
        client.call_service(domain, service, data)
    except HAError as exc:
        return str(exc), "ha-error"
    label = str(pending.get("label") or "that")
    action = str(pending.get("action") or "done")
    return f"{action.capitalize()} {label}, sir.", "done"


def _call(
    client: HATransport, domain: str, service: str, ents: list[dict], extra: dict | None = None
) -> None:
    ids = [str(e.get("entity_id")) for e in ents]
    data = dict(extra or {})
    data["entity_id"] = ids if len(ids) > 1 else ids[0]
    client.call_service(domain, service, data)


def _act(
    client: HATransport, cmd: HouseCommand, ents: list[dict]
) -> tuple[str, str]:
    if cmd.action in ("dim", "brighten"):
        return _act_brightness(client, cmd, ents)
    domain = str(ents[0].get("entity_id") or "").split(".", 1)[0]
    try:
        service, extra = _service(cmd, domain)
    except HAError as exc:
        return str(exc), "bad-action"
    _call(client, domain, service, ents, extra)
    label = _list_names(ents, "and")
    if cmd.action == "on":
        return f"{label} on, sir.", "done"
    if cmd.action == "off":
        return f"{label} off, sir.", "done"
    if cmd.action == "set" and cmd.temperature is not None:
        return f"{label} set to {cmd.temperature:g}°, sir.", "done"
    return f"{cmd.action} {label}, sir.", "done"


def _act_brightness(
    client: HATransport, cmd: HouseCommand, ents: list[dict]
) -> tuple[str, str]:
    domain = "light"
    lights = [
        e
        for e in ents
        if str(e.get("entity_id") or "").startswith("light.")
    ] or ents
    on = [e for e in lights if str(e.get("state")) == "on"]
    off = [e for e in lights if str(e.get("state")) != "on"]
    want = cmd.brightness
    if cmd.action == "dim":
        if not on:
            return (
                f"{_list_names(lights, 'and')} already off, sir.",
                "done",
            )
        pct = DIM_PCT if want is None else want
        dim_these: list[dict] = []
        off_these: list[dict] = []
        explicit = want is not None and want != DIM_PCT
        for ent in on:
            if not _can_dim(ent):
                off_these.append(ent)
                continue
            cur = _brightness_pct(ent)
            if not explicit and cur is not None and cur <= LOW_BRIGHT_PCT:
                off_these.append(ent)
            else:
                dim_these.append(ent)
        if dim_these:
            _call(client, domain, "turn_on", dim_these, {"brightness_pct": pct})
        if off_these:
            _call(client, domain, "turn_off", off_these)
        bits = []
        if dim_these:
            bits.append(f"{_list_names(dim_these, 'and')} dimmed to {pct}%")
        if off_these:
            bits.append(f"{_list_names(off_these, 'and')} off")
        return ", ".join(bits) + ", sir.", "done"
    pct = BRIGHT_PCT if want is None else want
    targets = off + [e for e in on if _can_dim(e)]
    if not targets:
        targets = lights
    dimmable = [e for e in targets if _can_dim(e)]
    onoff = [e for e in targets if not _can_dim(e)]
    if dimmable:
        _call(client, domain, "turn_on", dimmable, {"brightness_pct": pct})
    if onoff:
        _call(client, domain, "turn_on", onoff)
    label = _list_names(targets, "and")
    if dimmable:
        return f"{label} up to {pct}%, sir.", "done"
    return f"{label} on, sir.", "done"


def roster_path(home: JarvisHome) -> Path:
    return home.cache / "ha-roster.md"


def _attach_areas(client: HATransport, states: list[dict]) -> None:
    fn = getattr(client, "area_map", None)
    areas: dict[str, str] = {}
    if callable(fn):
        try:
            areas = dict(fn() or {})
        except Exception:
            areas = {}
    for ent in states:
        attrs = ent.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
            ent["attributes"] = attrs
        if attrs.get("area"):
            continue
        eid = str(ent.get("entity_id") or "")
        area = areas.get(eid)
        if area and str(area).lower() not in {"none", "null", ""}:
            attrs["area"] = str(area)


def roster_rows(states: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for ent in states:
        eid = str(ent.get("entity_id") or "")
        domain = eid.split(".", 1)[0]
        if domain not in ACTUATE_DOMAINS | {"media_player", "camera"}:
            continue
        if _junk(ent):
            continue
        rows.append(
            {
                "id": eid,
                "name": _label(ent),
                "domain": domain,
                "state": str(ent.get("state") or ""),
                "area": _area_of(ent),
                "dim": _can_dim(ent),
                "brightness": _brightness_pct(ent),
            }
        )
    return rows


def roster_markdown(states: list[dict]) -> str:
    lights: list[str] = []
    speakers: list[str] = []
    extras: list[str] = []
    rooms: list[str] = []
    for row in roster_rows(states):
        loc = f" in {row['area']}" if row["area"] else ""
        bit = f"{row['name']}{loc} ({row['state']})"
        if row["domain"] == "light":
            lights.append(bit)
        elif row["domain"] == "media_player" and row["state"] != "unavailable":
            speakers.append(f"{row['name']}{loc}")
        elif row["domain"] in {"lock", "cover", "climate", "camera"}:
            extras.append(bit)
        area = str(row.get("area") or "")
        if area and area not in rooms:
            rooms.append(area)
    parts = [
        "House devices from Home Assistant. The workshop actuates these; "
        "the desk does not flip switches."
    ]
    if lights:
        parts.append("Lights: " + "; ".join(lights) + ".")
    if speakers:
        parts.append("Speakers: " + "; ".join(speakers[:8]) + ".")
    if extras:
        parts.append("Also: " + "; ".join(extras[:8]) + ".")
    if rooms:
        parts.append("Rooms: " + ", ".join(rooms) + ".")
    return "\n".join(parts)


def _store_roster(home: JarvisHome, states: list[dict]) -> None:
    home.cache.mkdir(parents=True, exist_ok=True)
    try:
        roster_path(home).write_text(roster_markdown(states) + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        from memory.ears import cache_ha_names

        labels = []
        for row in roster_rows(states):
            if row["domain"] in ACTUATE_DOMAINS:
                labels.append(str(row["name"]))
        cache_ha_names(home, labels)
    except Exception:
        pass


def refresh_roster(home: JarvisHome, transport: HATransport | None = None) -> None:
    """Pull HA states into ~/.jarvis/cache so the desk can see device names."""
    try:
        client = _client(home, transport)
        states = client.get_states()
    except HAError:
        return
    _attach_areas(client, states)
    _store_roster(home, states)


def _command_from_map(data: dict) -> HouseCommand | None:
    action = str(data.get("action") or "").strip().lower()
    if not action or action in {"none", "chat", "unknown"}:
        return None
    ids = data.get("entity_ids") or data.get("entity_id") or []
    if isinstance(ids, str):
        ids = [ids]
    entity_ids = tuple(str(x) for x in ids if x)
    brightness = data.get("brightness")
    try:
        brightness_i = int(brightness) if brightness is not None else None
    except (TypeError, ValueError):
        brightness_i = None
    domain = str(data.get("domain") or "") or None
    if not domain and entity_ids:
        domain = entity_ids[0].split(".", 1)[0]
    area = str(data.get("area") or "") or None
    return HouseCommand(
        action=action,
        domain=domain,
        area=area,
        brightness=brightness_i,
        entity_ids=entity_ids,
        hints=(),
    )


MAP_SYSTEM = (
    "Map a spoken house request onto Home Assistant devices. "
    "JSON only: "
    '{"action":"on|off|dim|brighten|query|unlock|lock|open|close|none",'
    '"entity_ids":["light.x"],"brightness":30,"area":"Living Room"}. '
    "Use only entity_id values from the roster. "
    "Prefer lights in the named room. "
    "too bright → dim (brightness 30) or off if already dim or on/off-only. "
    "too dark → brighten. Ignore auto-update and do-not-disturb. "
    "If it is not a house request, action none."
)


def grok_map_command(
    prompt: str,
    roster: list[dict],
    *,
    grok: Path | None = None,
    model: str = "grok-4.5",
) -> HouseCommand | None:
    if not prompt.strip() or not roster:
        return None
    try:
        from memory.grokrun import extract_json, find_grok, run_prompt
    except Exception:
        return None
    path = grok or find_grok()
    compact = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "area": r.get("area"),
            "state": r.get("state"),
            "dim": r.get("dim"),
        }
        for r in roster
        if r.get("domain") in ACTUATE_DOMAINS
    ]
    asked = (
        "Roster:\n"
        + json.dumps(compact, ensure_ascii=False)
        + "\nUtterance: "
        + prompt.strip()
    )
    try:
        text = run_prompt(
            asked,
            grok=path,
            model=model,
            system=MAP_SYSTEM,
            web=False,
            max_turns=2,
            timeout=20,
        )
    except Exception:
        return None
    data = extract_json(text)
    if not isinstance(data, dict):
        return None
    return _command_from_map(data)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jarvis Home Assistant client")
    p.add_argument("--data-dir", default=None)
    p.add_argument("--check", action="store_true")
    p.add_argument("--entities", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    home = JarvisHome.discover(args.data_dir)
    home.ensure()
    token = load_token(home)
    url = load_url(home)
    dest = token_path(home)
    print(f"url={url}")
    print(f"token_file={dest} exists={dest.is_file()}")
    if not token:
        print(
            "No token. In Home Assistant: profile (bottom left) → Security → "
            "Long-lived access tokens → Create Token.\n"
            f"Save it as one line: {dest}"
        )
        raise SystemExit(2)
    client = RestHA(url, token)
    try:
        ping = client.ping()
    except HAError as exc:
        print(exc)
        raise SystemExit(1) from exc
    print("api=", ping)
    if args.entities or args.check:
        states = client.get_states()
        print(f"entities={len(states)}")
        if args.entities:
            _attach_areas(client, states)
            _store_roster(home, states)
            for ent in states:
                eid = str(ent.get("entity_id") or "")
                domain = eid.split(".", 1)[0]
                if domain in ACTUATE_DOMAINS and not _junk(ent):
                    area = _area_of(ent)
                    loc = f"\t{area}" if area else ""
                    print(f"  {eid}\t{_label(ent)}\t{ent.get('state')}{loc}")


if __name__ == "__main__":
    main()
