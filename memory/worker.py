"""Hands thread: heartbeat + pull jobs.

The mouth stays free. This process is Jarvis's other thread: grok -p with web
search, Grok Imagine, vault writes, house, and coding on advertised checkouts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

from memory.grokrun import extract_json, find_grok, run_prompt, run_prompt_result
from memory.home import JarvisHome
from memory.intent import file_line, remember_dest
from memory.jobs import JobBoard
from memory.prompt import HANDS_RULES, JARVIS_PERSONA
from memory.shell import SHELL_CAPS, repo_root
from memory.workshops import WorkshopRegistry

HOST_CAPS = (
    "search",
    "vault-write",
    "distill",
    "home",
    "imagine",
    "docs",
    "forge",
    "see",
    "diagnose",
    "bench",
)
FORGE_SYSTEM = (
    JARVIS_PERSONA
    + "You have Matt's training log. Answer what he asked. "
    "No medical advice. If the log is empty or missing, say so. Do not invent lifts."
)
SEARCH_SYSTEM = (
    HANDS_RULES
    + "Search the web if needed. Do not say you will check, look, or "
    "get back — answer now. No URLs unless essential. "
    "If a default weather location is given and Matt does not name a city, "
    "use that location. Do not ask which city."
)
REMEMBER_SYSTEM = (
    'Return JSON only: {"bullet": "one short durable fact", '
    '"action": "file"|"forget"|"place"}. '
    "place = weather location as 'City, Region, Country'. "
    "forget = the thing to drop. file = a lasting household fact. "
    "No markdown, no leading dash."
)
DOCS_SYSTEM = (
    "You write a markdown document Jarvis will save as a guide and a PDF. "
    "Return markdown only — title, frozen parts list with quantities, "
    "wiring/power, firmware flash, assembly steps, test. "
    "No spoken butler voice, no JSON, no preamble. "
    "You have NO files and NO workspace. All context is in the user message. "
    "Never say you are searching, never ask for details already in the brief, "
    "never write a one-line stall. Freeze one repeatable recipe from what "
    "Matt already chose. British English, room-by-room cloneable."
)
DISTILL_SYSTEM = (
    "Extract durable household facts from this transcript. "
    "Ignore chit-chat, jokes, hellos, and one-off questions. "
    'Return JSON only: {"facts": [{"dest": "household"|"never"|"daily"|"reminders", '
    '"bullet": "one short fact"}]}. '
    "household = lasting preferences and people. never = hard constraints. "
    "daily = only if it matters today and not later. "
    'reminders = timed items as "HH:MM daily - fact" or "YYYY-MM-DD HH:MM - fact". '
    'If nothing durable, {"facts": []}.'
)
IMAGINE_SYSTEM = (
    HANDS_RULES
    + "Call the image_gen tool once with a strong visual prompt for the picture "
    "Matt asked for. Do not call image_edit, image_to_video, or any other tool. "
    "Do not write code or touch the git checkout. After the image is saved, "
    "reply with JSON only: "
    '{"path": "<absolute path of the saved file>", "title": "<two or three words>"}. '
    "No markdown, no preamble."
)
IMAGINE_VIDEO_SYSTEM = (
    HANDS_RULES
    + "Matt asked for a rotating or animated clip. Call image_gen once for a "
    "clean hero still, then image_to_video once to animate a slow rotation "
    "or orbit (about 6 seconds). Do not write code. If video generation is "
    "blocked, keep the still and return that path. Reply with JSON only: "
    '{"path": "<absolute path>", "title": "<two or three words>", '
    '"kind": "video"|"still"}. No markdown, no preamble.'
)
IMAGINE_ASSEMBLY_SYSTEM = (
    HANDS_RULES
    + "Matt wants an assembly animation of a real kit, not a finished mystery gadget. "
    "Read the brief. Name the actual parts in the image_gen prompt "
    "(board, microphone capsule, cells, BMS with USB-C, switch, LED, enclosure). "
    "First still: those parts laid out on a workbench, labelled enough to tell apart, "
    "technical product viz. Then image_to_video: those SAME parts fitting together "
    "into the enclosure — exploded-to-assembled, not an orbit of a sealed unit. "
    "Do not invent a different product. Do not write code. If video is blocked, "
    "keep the exploded still. JSON only: "
    '{"path": "<absolute path>", "title": "<two or three words>", '
    '"kind": "video"|"still"}. No markdown, no preamble.'
)
IMAGINE_USER = (
    "{brief}\n"
    "Return the JSON after the file is saved."
)

CompleteFn = Callable[..., str]


def log(msg: str) -> None:
    print(msg, flush=True)


def dest_path(home: JarvisHome, dest: str, today: date | None = None) -> Path | None:
    today = today or date.today()
    if dest == "household":
        return home.vault / "people" / "_household.md"
    if dest == "never":
        return home.vault / "never.md"
    if dest == "daily":
        return home.vault / "daily" / f"{today.isoformat()}.md"
    if dest == "inbox":
        return home.vault / "inbox.md"
    if dest == "reminders":
        return home.vault / "reminders.md"
    return None


def append_bullet(path: Path, bullet: str) -> bool:
    bullet = " ".join((bullet or "").split()).lstrip("- ").strip()
    if not bullet:
        return False
    line = f"- {bullet}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if bullet in text:
            return False
        with path.open("a", encoding="utf-8") as fh:
            if text and not text.endswith("\n"):
                fh.write("\n")
            fh.write(line)
    else:
        path.write_text(line, encoding="utf-8")
    return True


def remove_matching_lines(path: Path, pattern: re.Pattern[str]) -> int:
    if not path.is_file():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    keep: list[str] = []
    n = 0
    for line in lines:
        if line.lstrip().startswith("-") and pattern.search(line):
            n += 1
            continue
        keep.append(line)
    if n:
        path.write_text("".join(keep), encoding="utf-8")
    return n


def extract_place(text: str) -> str:
    raw = " ".join((text or "").split())
    hit = re.search(
        r"(?:live in|i'?m in|i am in|not in \w+,\s*i am in|to|use)\s+"
        r"([A-Za-z][A-Za-z]+(?:[\s,][A-Za-z]+){0,4})",
        raw,
        re.I,
    )
    if not hit:
        return ""
    place = hit.group(1)
    place = re.sub(
        r"\b(?:weather|location|please|instead|of|from|the)\b",
        "",
        place,
        flags=re.I,
    )
    return " ".join(place.split()).strip(" ,.")


def _session_turns(path: Path, limit: int = 40) -> str:
    if not path.is_file():
        return ""
    rows: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") != "turn":
            continue
        user = " ".join(str(ev.get("user") or "").split())[:240]
        reply = " ".join(str(ev.get("reply") or "").split())[:240]
        if user:
            rows.append(f"You: {user}")
        if reply:
            rows.append(f"Jarvis: {reply}")
    return "\n".join(rows[-(limit * 2) :])


def _parent_gone(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return True
    return False


class HostWorker:
    def __init__(
        self,
        home: JarvisHome,
        *,
        grok: Path | None = None,
        model: str = "grok-4.6",
        worker_id: str | None = None,
        complete: CompleteFn | None = None,
        parent_pid: int = 0,
        heartbeat_s: float = 10.0,
        caps: tuple[str, ...] = HOST_CAPS,
        repo: Path | str | None = None,
    ):
        self.home = home
        self.grok = grok or find_grok()
        self.model = model
        if worker_id:
            self.worker_id = worker_id
        elif "shell" in caps and "search" not in caps:
            self.worker_id = f"shell-{socket.gethostname()}"
        else:
            self.worker_id = f"host-{socket.gethostname()}"
        self.complete = complete
        self.parent_pid = parent_pid
        self.heartbeat_s = heartbeat_s
        self.caps = caps
        self.repo = Path(repo).resolve() if repo else None
        self.board = JobBoard(home)
        self.registry = WorkshopRegistry(home)
        self._last_beat = 0.0
        self._job_id = ""
        self._audience = ""

    def advertise(self) -> None:
        extra: dict = {
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "model": self.model,
        }
        if self.repo:
            if "shell" in self.caps:
                from memory.apps import roots_for_shell

                extra["roots"] = roots_for_shell(self.home, self.repo)
            else:
                extra["roots"] = [str(self.repo)]
        self.registry.advertise(self.worker_id, list(self.caps), **extra)
        self._last_beat = time.monotonic()

    def beat(self) -> None:
        if time.monotonic() - self._last_beat >= self.heartbeat_s:
            self.advertise()

    def _ask(
        self,
        prompt: str,
        *,
        system: str,
        web: bool,
        max_turns: int = 6,
        timeout: float = 90,
        tools: str | None = None,
        cwd: Path | str | None = None,
        effort: str = "low",
        disallowed: str | None = None,
        subagents: bool = False,
        image: Path | str | None = None,
    ) -> str:
        asked = (self._audience or "") + prompt
        if self.complete is not None:
            if self._job_cancelled():
                raise InterruptedError("cancelled")
            return self.complete(
                asked,
                system=system,
                web=web,
                max_turns=max_turns,
                tools=tools,
                cwd=cwd,
                effort=effort,
                disallowed=disallowed,
                subagents=subagents,
                image=image,
            )
        return run_prompt(
            asked,
            grok=self.grok,
            model=self.model,
            system=system,
            web=web,
            max_turns=max_turns,
            timeout=timeout,
            tools=tools,
            cwd=cwd,
            effort=effort,
            disallowed=disallowed,
            subagents=subagents,
            abort=self._job_cancelled,
            image=image,
        )

    def _job_cancelled(self) -> bool:
        jid = self._job_id
        return bool(jid) and self.board.latest_status(jid) == "cancelled"

    def handle(self, snap: dict) -> tuple[str, str]:
        who = str(snap.get("who") or "").strip()
        address = str(snap.get("address") or "").strip()
        self._audience = ""
        if who and address:
            never = "" if address.lower() == "sir" else " Never sir."
            self._audience = f"Speak to {who}. Address as {address}.{never}\n\n"
        try:
            cap = str(snap.get("cap") or "")
            if cap == "search":
                return self._search(snap)
            if cap == "vault-write":
                return self._remember(snap)
            if cap == "distill":
                return self._distill(snap)
            if cap == "home":
                return self._home(snap)
            if cap == "imagine":
                return self._imagine(snap)
            if cap == "docs":
                return self._docs(snap)
            if cap == "shell":
                return self._shell(snap)
            if cap == "forge":
                return self._forge(snap)
            if cap == "see":
                return self._see(snap)
            if cap == "diagnose":
                return self._diagnose(snap)
            if cap == "bench":
                return self._bench(snap)
            raise RuntimeError(f"unsupported cap {cap!r}")
        finally:
            self._audience = ""

    def _see(self, snap: dict) -> tuple[str, str]:
        addr = str(snap.get("address") or "sir").strip() or "sir"
        speak = (
            f"I don't send pictures off this machine, {addr}. "
            "I haven't got eyes that stay in the house yet."
        )
        return speak, "refused-cloud"

    def _diagnose(self, snap: dict) -> tuple[str, str]:
        from memory.diagnose import inspect

        return inspect(self.home, str(snap.get("prompt") or ""))

    def _bench(self, snap: dict) -> tuple[str, str]:
        from memory.bench import apply

        return apply(self.home, str(snap.get("prompt") or ""))

    def _forge(self, snap: dict) -> tuple[str, str]:
        from memory.forge import fetch_brief, load_secrets

        prompt = str(snap.get("prompt") or "").strip()
        secrets = load_secrets(self.home)
        if not secrets.get("url"):
            return "Forge is not configured, sir.", "no secrets"
        try:
            brief = fetch_brief(self.home)
        except RuntimeError as exc:
            msg = str(exc)
            if "not on file" in msg:
                return "Forge login is not on file, sir.", "no login"
            raise
        asked = (
            "Training log:\n"
            + brief
            + "\n\nMatt asked: "
            + prompt
            + "\nAnswer from the log only."
        )
        speak = self._ask(
            asked,
            system=FORGE_SYSTEM,
            web=False,
            max_turns=1,
            timeout=40,
        )
        speak = " ".join((speak or "").split())
        return speak, brief[:200]

    def _shell(self, snap: dict) -> tuple[str, str]:
        from memory.shell import (
            SHELL_DENY,
            SHELL_SYSTEM,
            looks_like_tests,
            refuse_reason,
            run_unittests,
            shell_brief,
            speak_from_grok,
        )

        prompt = str(snap.get("prompt") or "").strip()
        root = Path(str(snap.get("root") or self.repo or repo_root()))
        reason = refuse_reason(prompt)
        if reason:
            return reason, "refused"
        if looks_like_tests(prompt):
            return run_unittests(root)
        asked = shell_brief(self.home, prompt)
        raw = self._ask(
            asked,
            system=SHELL_SYSTEM,
            web=True,
            max_turns=12,
            timeout=180,
            disallowed=SHELL_DENY,
            subagents=True,
            effort="high",
            cwd=root,
        )
        return speak_from_grok(raw)

    def _docs(self, snap: dict) -> tuple[str, str]:
        from memory.docs import looks_like_guide, save_guide, slug_title, speak_ready
        from memory.working import workshop_brief

        prompt = str(snap.get("prompt") or "").strip()
        brief = workshop_brief(self.home, prompt)
        asked = "Write the markdown guide for this request.\n\n" + brief
        markdown = self._ask(
            asked,
            system=DOCS_SYSTEM,
            web=False,
            max_turns=2,
            timeout=90,
        )
        body = (markdown or "").strip()
        if not looks_like_guide(body):
            markdown = self._ask(
                asked
                + "\n\nYour last reply was not a guide. Output the full markdown "
                "spec now: title, parts with quantities, power/BMS, assembly, flash, test.",
                system=DOCS_SYSTEM,
                web=False,
                max_turns=2,
                timeout=90,
            )
            body = (markdown or "").strip()
        if not looks_like_guide(body):
            raise RuntimeError(
                "docs workshop did not write a real guide (refused or too thin)"
            )
        slug = slug_title(prompt)
        if slug.startswith("so-can-you") or slug.startswith("can-you"):
            slug = "build-guide"
        _md, pdf = save_guide(body, slug=slug)
        return speak_ready(pdf), str(pdf)

    def _home(self, snap: dict) -> tuple[str, str]:
        from memory.ha import grok_map_command, run_home

        def mapper(prompt: str, roster: list[dict]):
            return grok_map_command(
                prompt, roster, grok=self.grok, model=self.model
            )

        return run_home(self.home, snap, mapper=mapper)

    def _imagine(self, snap: dict) -> tuple[str, str]:
        from memory.grokrun import session_id_from_stream
        from memory.imagine import (
            album_dir,
            append_index,
            collect_new_images,
            files_from_stream,
            grok_session_folder,
            library_label,
            library_root,
            parse_imagine_request,
            pick_candidate,
            resolve_image_path,
            settle_image,
            slug_title,
            speak_ready,
            wants_animation,
            wants_assembly,
        )
        from memory.working import workshop_brief

        prompt = str(snap.get("prompt") or "").strip()
        brief = workshop_brief(self.home, prompt)
        kind = str(snap.get("media") or "")
        assembly = wants_assembly(prompt) or wants_assembly(brief)
        if assembly:
            kind = "video"
        elif kind not in ("video", "still"):
            kind = "video" if wants_animation(prompt) else "still"
        subject, album = parse_imagine_request(prompt)
        root = library_root(kind)
        dest_dir = album_dir(root, album)
        dest_dir.mkdir(parents=True, exist_ok=True)
        slug = slug_title(subject)
        if assembly and (slug.startswith("so-can-you") or "animation" in slug):
            slug = "kit-assembly"
        started = time.time()
        user = IMAGINE_USER.replace("{brief}", brief)
        tools = "image_gen,image_to_video" if kind == "video" else "image_gen"
        if assembly:
            system = IMAGINE_ASSEMBLY_SYSTEM
            tools = "image_gen,image_to_video"
            kind = "video"
        elif kind == "video":
            system = IMAGINE_VIDEO_SYSTEM
        else:
            system = IMAGINE_SYSTEM
        timeout = 180 if kind == "video" else 120
        max_turns = 6 if kind == "video" else 3
        stdout = ""
        session_id = ""
        if self.complete is not None:
            raw = self._ask(
                user,
                system=system,
                web=False,
                max_turns=max_turns,
                timeout=timeout,
                tools=tools,
                cwd=dest_dir,
            )
        else:
            got = run_prompt_result(
                user,
                grok=self.grok,
                model=self.model,
                system=system,
                web=False,
                max_turns=max_turns,
                timeout=timeout,
                tools=tools,
                cwd=dest_dir,
            )
            raw = got.text
            stdout = got.stdout
            session_id = got.session_id

        candidates: list[Path] = []
        seen: set[Path] = set()

        def add(path: Path | None) -> None:
            if path is None or not path.is_file():
                return
            key = path.resolve()
            if key in seen:
                return
            seen.add(key)
            candidates.append(path)

        parsed = extract_json(raw)
        title = ""
        if isinstance(parsed, dict):
            title = str(parsed.get("title") or "").strip()
            add(resolve_image_path(str(parsed.get("path") or ""), dest_dir))
            if str(parsed.get("kind") or "") == "still":
                kind = "still"
        for blob in (stdout, raw):
            for hit in files_from_stream(blob):
                add(resolve_image_path(hit, dest_dir))
        folders = [dest_dir, dest_dir / "images", dest_dir / "videos"]
        sid = session_id or session_id_from_stream(stdout)
        sess = grok_session_folder(dest_dir, sid) if sid else None
        if sess:
            folders.extend([sess, sess / "images", sess / "videos"])
        for folder in folders:
            for path in collect_new_images(folder, started):
                add(path)
        wanted = kind
        chosen = pick_candidate(candidates, kind)
        if chosen is None:
            raise RuntimeError("imagine produced no image file")
        if chosen.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}:
            kind = "video"
            root = library_root("video")
            dest_dir = album_dir(root, album)
        else:
            kind = "still"
            root = library_root("still")
            dest_dir = album_dir(root, album)
        dest_dir.mkdir(parents=True, exist_ok=True)
        final = settle_image(chosen, dest_dir, slug)
        label = title or subject
        try:
            rel = final.resolve().relative_to(root.resolve())
            append_index(root, rel.as_posix(), label)
        except Exception as exc:
            log(f"[workshop] imagine index skipped ({exc})")
        library = library_label(kind)
        if wanted == "video" and kind != "video":
            return (
                f"Ready, sir. Still in {library}; motion needs privacy mode off.",
                str(final),
            )
        return speak_ready(final, title, root=root, library=library), str(final)

    def _search(self, snap: dict) -> tuple[str, str]:
        from memory.working import search_prompt

        prompt = str(snap.get("prompt") or "").strip()
        asked = search_prompt(self.home, prompt)
        speak = self._ask(asked, system=SEARCH_SYSTEM, web=True, max_turns=6, timeout=80)
        speak = " ".join(speak.split())
        if re.search(r"weather|forecast", prompt, re.I):
            cache = self.home.cache / "weather.md"
            cache.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            cache.write_text(f"{speak}\n\n_cached {stamp}_\n", encoding="utf-8")
        return speak, speak

    def _remember(self, snap: dict) -> tuple[str, str]:
        prompt = str(snap.get("prompt") or "").strip()
        dest = str(snap.get("dest") or remember_dest(prompt))
        action = str(snap.get("action") or "file")
        bullet = ""
        parsed_action = ""
        try:
            raw = self._ask(
                f"Utterance: {prompt}",
                system=REMEMBER_SYSTEM,
                web=False,
                max_turns=1,
                timeout=30,
            )
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                bullet = str(parsed.get("bullet") or "").strip()
                parsed_action = str(parsed.get("action") or "").strip()
        except Exception as exc:
            log(f"[workshop] remember polish skipped ({exc})")
        if parsed_action in ("forget", "place", "file"):
            action = parsed_action
        if action == "forget":
            return self._forget(prompt, dest, bullet)
        if action == "place":
            place = extract_place(prompt) or bullet
            place = re.sub(r"^(?:home weather location is\s+)", "", place, flags=re.I)
            place = place.strip(" .") or "Canterbury, Kent, UK"
            path = dest_path(self.home, "household")
            if path is None:
                raise RuntimeError("refusing vault dest household")
            remove_matching_lines(path, re.compile(r"weather location", re.I))
            append_bullet(path, f"Home weather location is {place}")
            return f"Weather is {place}, sir.", f"place: {place}"
        if not bullet:
            bullet = file_line(prompt)
        if dest == "reminders":
            from memory.reminders import file_reminder, format_from_utterance

            bullet = format_from_utterance(prompt, fallback=bullet)
            wrote = file_reminder(self.home, bullet)
        else:
            path = dest_path(self.home, dest)
            if path is None:
                raise RuntimeError(f"refusing vault dest {dest!r}")
            wrote = append_bullet(path, bullet)
        result = f"{dest}: {bullet}" if wrote else f"{dest}: duplicate"
        if not wrote:
            return "Already noted, sir.", result
        return "Filed, sir.", result

    def _forget(self, prompt: str, dest: str, bullet: str) -> tuple[str, str]:
        bits: list[str] = []
        if re.search(r"\bboy\b", prompt, re.I):
            bits.append(r"\bboy\b")
        if re.search(r"\bentrance\b", prompt, re.I):
            bits.append(r"entrance")
        if bullet:
            token = re.escape(" ".join(bullet.split())[:40])
            if token:
                bits.append(token)
        if not bits:
            return "I couldn't find that, sir.", "forget: none"
        pattern = re.compile("|".join(bits), re.I)
        n = 0
        for name in (dest, "household", "daily"):
            path = dest_path(self.home, name)
            if path is None:
                continue
            n += remove_matching_lines(path, pattern)
        if n:
            return "Removed, sir.", f"forget: {n}"
        return "I couldn't find that, sir.", "forget: 0"

    def _distill(self, snap: dict) -> tuple[str, str]:
        path = Path(str(snap.get("path") or ""))
        transcript = _session_turns(path)
        if not transcript.strip():
            return "", "no turns"
        raw = self._ask(
            "Transcript:\n" + transcript,
            system=DISTILL_SYSTEM,
            web=False,
            max_turns=1,
            timeout=60,
        )
        parsed = extract_json(raw)
        facts = []
        if isinstance(parsed, dict):
            facts = parsed.get("facts") or []
        written = 0
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            dest = str(fact.get("dest") or "")
            bullet = str(fact.get("bullet") or "")
            if dest == "reminders":
                from memory.reminders import file_reminder

                if file_reminder(self.home, bullet):
                    written += 1
                continue
            dest_file = dest_path(self.home, dest)
            if dest_file is None:
                log(f"[workshop] distill skipped dest {dest!r}")
                continue
            if append_bullet(dest_file, bullet):
                written += 1
        result = f"filed {written} fact(s)"
        return "", result

    def tick(self) -> bool:
        """Claim and run at most one runnable job. True if work ran."""
        self.beat()
        jobs = self.board.runnable(list(self.caps))
        if not jobs:
            return False
        snap = jobs[0]
        job_id = str(snap.get("id") or "")
        if not job_id or not self.board.claim(job_id, self.worker_id):
            return False
        cap = str(snap.get("cap") or "job")
        log(f"[workshop] {job_id} {cap}")
        started = {
            "search": "Looking that up.",
            "vault-write": "Filing that.",
            "home": "Seeing to the house.",
            "imagine": "Drawing that.",
            "docs": "Writing that up.",
            "shell": "Working on the checkout.",
            "forge": "Checking the log.",
            "see": "Looking.",
            "diagnose": "Looking at what went wrong.",
            "distill": "Filing notes.",
        }.get(cap, "On it.")
        self.board.progress(job_id, started)
        self._job_id = job_id
        try:
            speak, result = self.handle(self.board.snapshot(job_id))
        except InterruptedError:
            log(f"[workshop] {job_id} cancelled")
            return True
        except Exception as exc:
            if self.board.latest_status(job_id) == "cancelled":
                log(f"[workshop] {job_id} cancelled")
                return True
            log(f"[workshop] {job_id} error {exc}")
            self.board.fail(job_id, str(exc))
            return True
        finally:
            self._job_id = ""
        if self.board.latest_status(job_id) == "cancelled":
            log(f"[workshop] {job_id} cancelled")
            return True
        self.board.finish(job_id, speak=speak, result=result)
        log(f"[workshop] {job_id} done {result!r}")
        return True

    def run(self, *, once: bool = False, idle_s: float = 0.25) -> None:
        self.home.ensure()
        self.advertise()
        if "home" in self.caps:
            try:
                from memory.ha import refresh_roster

                refresh_roster(self.home)
            except Exception:
                pass
        extra = f" repo={self.repo}" if self.repo else ""
        log(
            f"[workshop] {self.worker_id} caps={','.join(self.caps)} "
            f"home={self.home.root}{extra}"
        )
        while True:
            if self.parent_pid and _parent_gone(self.parent_pid):
                log("[workshop] parent gone, exit")
                return
            ran = self.tick()
            if once:
                return
            if not ran:
                time.sleep(idle_s)


def spawn_host_workshop(
    home: JarvisHome,
    *,
    grok: Path,
    model: str,
    parent_pid: int,
) -> subprocess.Popen:
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "memory.worker",
        "--data-dir",
        str(home.root),
        "--grok",
        str(grok),
        "--model",
        model,
        "--parent-pid",
        str(parent_pid),
    ]
    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    return subprocess.Popen(cmd, cwd=str(root), env=env, **extra)


def spawn_shell_workshop(
    home: JarvisHome,
    *,
    grok: Path,
    model: str,
    parent_pid: int,
    repo: Path | None = None,
) -> subprocess.Popen:
    root = repo or repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable,
        "-m",
        "memory.worker",
        "--data-dir",
        str(home.root),
        "--grok",
        str(grok),
        "--model",
        model,
        "--parent-pid",
        str(parent_pid),
        "--caps",
        ",".join(SHELL_CAPS),
        "--repo",
        str(root),
        "--worker-id",
        f"shell-{socket.gethostname()}",
    ]
    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    return subprocess.Popen(cmd, cwd=str(root), env=env, **extra)


def drain_runnable(
    home: JarvisHome,
    *,
    grok: Path | None = None,
    model: str = "grok-4.5",
    complete: CompleteFn | None = None,
    limit: int = 8,
) -> int:
    """Run leftover jobs in-process (session close / dead worker)."""
    worker = HostWorker(
        home,
        grok=grok,
        model=model,
        worker_id="host-close",
        complete=complete,
    )
    n = 0
    for _ in range(limit):
        if not worker.tick():
            break
        n += 1
    return n


def _ignore_sigint() -> None:
    if sys.platform == "win32":
        return
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jarvis host workshop")
    p.add_argument("--data-dir", default=None)
    p.add_argument("--grok", default=None)
    p.add_argument("--model", default="grok-4.6")
    p.add_argument("--worker-id", default=None)
    p.add_argument("--parent-pid", type=int, default=0)
    p.add_argument("--once", action="store_true")
    p.add_argument(
        "--caps",
        default="",
        help="comma-separated caps (default: host workshop)",
    )
    p.add_argument("--repo", default=None, help="git checkout for the shell cap")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    _ignore_sigint()
    args = parse_args(argv)
    home = JarvisHome.discover(args.data_dir)
    grok = Path(args.grok).expanduser() if args.grok else find_grok()
    caps = tuple(c.strip() for c in (args.caps or "").split(",") if c.strip())
    repo = Path(args.repo).expanduser().resolve() if args.repo else None
    worker = HostWorker(
        home,
        grok=grok,
        model=args.model,
        worker_id=args.worker_id,
        parent_pid=args.parent_pid,
        caps=caps or HOST_CAPS,
        repo=repo,
    )
    worker.run(once=args.once)


if __name__ == "__main__":
    main()
