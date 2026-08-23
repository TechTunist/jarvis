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
    r"\b(?:set|make|change)\b.*?\b(?:to|at)\s+(\d{1,2}(?:\.\d)?)\b", re.I
)
_TEMP = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*(?:degrees?|c(?:elsius)?)\b", re.I)
_ALL = re.compile(r"\ball\b", re.I)

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
)

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


def _entity_stems(ent: dict) -> set[str]:
    eid = str(ent.get("entity_id") or "")
    return _stems(_label(ent) + " " + eid.replace(".", " ").replace("_", " "))


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
    hints: tuple[str, ...] = ()


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
    action = ""
    tail = _TURN_TAIL.search(raw)
    if re.match(r"^(?:is|are|what|how's|how is|status)\b", raw, re.I):
        action = "query"
    elif _UNLOCK.search(raw):
        action = "unlock"
    elif _LOCK.search(raw):
        action = "lock"
    elif _ON.search(raw) or (tail and tail.group(1).lower() == "on"):
        action = "on"
    elif _OFF.search(raw) or (tail and tail.group(1).lower() == "off"):
        action = "off"
    elif _OPEN.search(raw):
        action = "open"
    elif _CLOSE.search(raw):
        action = "close"
    elif temp is not None or (domain == "climate" and re.search(r"\bset\b", raw, re.I)):
        action = "set"
    elif _QUERY.search(raw) or re.search(r"\b(?:how|what)\b", raw, re.I):
        action = "query"
    if not action:
        return None
    if not domain:
        if action in ("on", "off"):
            domain = "light"
        elif action in ("lock", "unlock"):
            domain = "lock"
        elif action in ("open", "close") and area == "garage":
            domain = "cover"
        elif action == "set":
            domain = "climate"
    return HouseCommand(
        action=action,
        domain=domain,
        area=area,
        all_of=bool(_ALL.search(raw)),
        temperature=temp,
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
    return _norm(_label(ent) + " " + eid.replace(".", " ").replace("_", " "))


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
    scored: list[tuple[int, dict]] = []
    for ent in states:
        eid = str(ent.get("entity_id") or "")
        domain = eid.split(".", 1)[0]
        if cmd.action != "query" and domain not in ACTUATE_DOMAINS:
            continue
        if cmd.action == "query" and domain not in ACTUATE_DOMAINS | {
            "binary_sensor",
            "sensor",
        }:
            continue
        if cmd.action == "query" and domain in {"binary_sensor", "sensor"}:
            if not (cmd.area and cmd.area in _blob(ent)):
                continue
        elif not _compatible(domain, cmd.domain):
            continue
        if cmd.action != "query" and (
            "auto_update" in eid or "auto-update" in _blob(ent)
        ):
            continue
        blob = _blob(ent)
        score = 0
        if cmd.area and cmd.area in blob:
            score += 6
        if cmd.domain and domain == cmd.domain:
            score += 2
        if cmd.domain == "cover" and "garage" in blob:
            score += 3
        for hint in cmd.hints:
            score += _hint_score(hint, ent)
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
        if cmd.action in ("on", "off") and not cmd.hints:
            return []
        return tied if len(tied) == 1 else []
    best = scored[0][0]
    picked = [e for s, e in scored if s == best]
    if cmd.action in ("on", "off") and cmd.domain in {"light", "switch"}:
        return [e for s, e in scored if s >= best - 1][:8]
    return picked


def _service(cmd: HouseCommand, domain: str) -> tuple[str, dict]:
    if cmd.action == "on":
        return "turn_on", {}
    if cmd.action == "off":
        return "turn_off", {}
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


def _list_names(ents: list[dict]) -> str:
    names = [_label(e) for e in ents[:3]]
    if len(ents) > 3:
        names.append("more")
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


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


def run_home(
    home: JarvisHome,
    snap: dict,
    transport: HATransport | None = None,
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
    if cmd is None:
        return "I didn't catch which house action, sir.", "unparsed"
    _clear_clarify(home)
    try:
        client = _client(home, transport)
        states = client.get_states()
    except HAError as exc:
        return str(exc), "ha-error"
    try:
        from memory.ears import cache_ha_names

        labels = []
        for st in states:
            eid = str(st.get("entity_id") or "")
            if eid.split(".", 1)[0] in ACTUATE_DOMAINS and "auto_update" not in eid:
                labels.append(_label(st))
        cache_ha_names(home, labels)
    except Exception:
        pass
    ents = resolve_entities(states, cmd)
    if not ents:
        if cmd.action in ("on", "off") and not cmd.area and not cmd.all_of:
            _write_clarify(home, prompt)
            return "Which lights, sir? Name the room.", "ambiguous"
        return "I couldn't find that in the house, sir.", "none"
    if cmd.action == "query":
        phrase = "; ".join(_state_phrase(e) for e in ents[:4])
        return f"{phrase}, sir.", "query"
    if (
        not cmd.area
        and not cmd.all_of
        and cmd.action in ("on", "off")
        and len(ents) > 1
    ):
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
                "label": _list_names(ents),
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


def _act(
    client: HATransport, cmd: HouseCommand, ents: list[dict]
) -> tuple[str, str]:
    domain = str(ents[0].get("entity_id") or "").split(".", 1)[0]
    try:
        service, extra = _service(cmd, domain)
    except HAError as exc:
        return str(exc), "bad-action"
    ids = [str(e.get("entity_id")) for e in ents]
    data = dict(extra)
    data["entity_id"] = ids if len(ids) > 1 else ids[0]
    client.call_service(domain, service, data)
    label = _list_names(ents)
    if cmd.action == "on":
        return f"{label} on, sir.", "done"
    if cmd.action == "off":
        return f"{label} off, sir.", "done"
    if cmd.action == "set" and cmd.temperature is not None:
        return f"{label} set to {cmd.temperature:g}°, sir.", "done"
    return f"{cmd.action} {label}, sir.", "done"


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
            for ent in states:
                eid = str(ent.get("entity_id") or "")
                domain = eid.split(".", 1)[0]
                if domain in ACTUATE_DOMAINS:
                    print(f"  {eid}\t{_label(ent)}\t{ent.get('state')}")


if __name__ == "__main__":
    main()
