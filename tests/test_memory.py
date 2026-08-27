"""Foundations: vault boot stays small; jobs/workshops are files; Talk does not dump memory."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from memory.distill import distill_session
from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.prompt import BOOT_BUDGET, SPEECH_RULES, build_system_prompt, fit_notes, load_boot_notes
from memory.session import SessionLog
from memory.workshops import WorkshopRegistry


class HomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")

    def test_seed_creates_vault_and_does_not_overwrite(self) -> None:
        self.home.ensure()
        boot = self.home.vault / "BOOT.md"
        self.assertTrue(boot.is_file())
        self.assertTrue((self.home.vault / "people" / "_household.md").is_file())
        self.assertTrue((self.home.vault / "never.md").is_file())
        self.assertTrue((self.home.vault / "reminders.md").is_file())
        self.assertTrue((self.home.secrets / "README.md").is_file())
        self.assertTrue(self.home.imagine.is_dir())
        self.assertFalse((self.home.secrets / "ha.token").exists())
        boot.write_text("edited by matt\n", encoding="utf-8")
        self.home.ensure()
        self.assertEqual(boot.read_text(encoding="utf-8"), "edited by matt\n")

    def test_discover_env_and_override(self) -> None:
        custom = Path(self.tmp.name) / "custom"
        self.assertEqual(JarvisHome.discover(custom).root, custom.resolve())
        prev = os.environ.get("JARVIS_HOME")
        os.environ["JARVIS_HOME"] = str(custom)

        def restore() -> None:
            if prev is None:
                os.environ.pop("JARVIS_HOME", None)
            else:
                os.environ["JARVIS_HOME"] = prev

        self.addCleanup(restore)
        self.assertEqual(JarvisHome.discover().root, custom.resolve())

    def test_lease_warns_other_host(self) -> None:
        self.home.ensure()
        self.home.lease_path.write_text(
            json.dumps({"host": "other-box", "pid": 9, "ts": time.time()}) + "\n",
            encoding="utf-8",
        )
        warn = self.home.take_lease(os.getpid())
        self.assertIsNotNone(warn)
        self.assertIn("other-box", warn or "")
        self.home.drop_lease(os.getpid())
        self.assertFalse(self.home.lease_path.exists())

    def test_lease_same_pid_is_quiet(self) -> None:
        self.home.ensure()
        first = self.home.take_lease(os.getpid())
        self.assertIsNone(first)
        again = self.home.take_lease(os.getpid())
        self.assertIsNone(again)


class PromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()

    def test_rules_always_first_and_budget_respected(self) -> None:
        huge = [("boot", "X" * 20_000)]
        prompt = build_system_prompt(huge, budget=500)
        self.assertTrue(prompt.startswith(SPEECH_RULES[:40]))
        self.assertNotIn("workbench is not connected yet", SPEECH_RULES)
        self.assertIn("do not emit [hands:]", SPEECH_RULES.lower())
        self.assertIn("already doing the work", SPEECH_RULES)
        self.assertNotIn("Do not discuss microphones", SPEECH_RULES)
        extra = prompt[len(SPEECH_RULES) :]
        self.assertLessEqual(len(extra), 500 + 80)
        self.assertIn("Notes", prompt)

    def test_load_priority_today_over_empty_yesterday(self) -> None:
        today = date(2026, 8, 22)
        daily = self.home.vault / "daily"
        (daily / f"{today.isoformat()}.md").write_text("# today\nhello\n", encoding="utf-8")
        notes = load_boot_notes(self.home, today=today)
        labels = [n[0] for n in notes]
        self.assertIn("boot", labels)
        self.assertIn("today", labels)
        self.assertNotIn("yesterday", labels)

    def test_fit_notes_drops_tail_when_over_budget(self) -> None:
        notes = [("a", "A" * 100), ("b", "B" * 100), ("c", "C" * 100)]
        text = fit_notes(notes, budget=130)
        self.assertIn("[a]", text)
        self.assertNotIn("[c]", text)

    def test_workers_line_in_prompt(self) -> None:
        prompt = build_system_prompt([], workers="Workers: none.")
        self.assertIn("Workers: none.", prompt)

    def test_weather_cache_in_boot(self) -> None:
        (self.home.cache / "weather.md").write_text("Rain later.\n", encoding="utf-8")
        notes = load_boot_notes(self.home, today=date(2026, 8, 22))
        labels = [n[0] for n in notes]
        self.assertIn("weather", labels)
        self.assertIn("reminders", labels)

    def test_house_roster_in_boot(self) -> None:
        (self.home.cache / "ha-roster.md").write_text(
            "Lights: Living Room Main Light in Living Room (off).\n",
            encoding="utf-8",
        )
        notes = load_boot_notes(self.home, today=date(2026, 8, 22))
        labels = [n[0] for n in notes]
        self.assertIn("house", labels)
        bundle = "\n".join(body for _label, body in notes)
        self.assertIn("Living Room Main Light", bundle)


class SessionDistillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()

    def test_jsonl_and_daily_note(self) -> None:
        log = SessionLog.start(self.home)
        log.record("Hello Jarvis", "Good evening, sir.", total_ms=2100, model="grok-4.5")
        log.record("Remember I take tea at five.", "Noted, sir.", total_ms=1800)
        log.close()
        raw = log.path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in raw.splitlines()]
        kinds = [e["event"] for e in events]
        self.assertEqual(kinds, ["start", "turn", "turn", "end"])
        self.assertIn("tea at five", raw)
        dest = distill_session(log)
        self.assertIsNotNone(dest)
        body = dest.read_text(encoding="utf-8")
        self.assertNotIn("tea at five", body)
        self.assertNotIn("Good evening", body)
        self.assertNotIn("You:", body)
        self.assertIn("2 turns", body)
        self.assertTrue(body.startswith("# "))

    def test_close_enqueues_distill_job(self) -> None:
        log = SessionLog.start(self.home)
        log.record("Hello", "Sir.")
        log.close()
        board = JobBoard(self.home)
        distill_session(log, board=board)
        jobs = board.runnable(["distill"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["path"], str(log.path))

    def test_empty_session_does_not_write_daily(self) -> None:
        log = SessionLog.start(self.home)
        log.close()
        self.assertIsNone(distill_session(log))
        daily = self.home.vault / "daily"
        self.assertEqual(list(daily.glob("*.md")), [])


class JobBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)

    def test_enqueue_and_status(self) -> None:
        jid = self.board.enqueue("search", "weather London")
        self.assertEqual(self.board.latest_status(jid), "enqueued")
        self.board.append(jid, {"event": "done", "result": "rain"})
        self.assertEqual(self.board.latest_status(jid), "done")
        evs = self.board.events(jid)
        self.assertEqual(evs[0]["cap"], "search")
        self.assertEqual(evs[-1]["result"], "rain")

    def test_status_line_tells_the_truth(self) -> None:
        self.assertIn(
            "Nothing queued",
            self.board.status_line("have you initiated the animation yet?"),
        )
        jid = self.board.enqueue("imagine", "assembly animation")
        line = self.board.status_line(
            "is the workshop busy", pending_ids={jid}
        )
        self.assertIn("imagine", line.lower())

    def test_rejects_path_escape(self) -> None:
        with self.assertRaises(ValueError):
            self.board.path_for("../secret")

    def test_claim_finish_and_stale_retry(self) -> None:
        jid = self.board.enqueue("search", "weather London")
        self.assertEqual(len(self.board.runnable(["search"])), 1)
        self.assertTrue(self.board.claim(jid, "host-a"))
        self.assertEqual(self.board.latest_status(jid), "claimed")
        self.assertEqual(self.board.runnable(["search"]), [])
        self.assertEqual(len(self.board.active(["search"])), 1)
        self.board.finish(jid, speak="Rain later, sir.", result="rain")
        self.assertEqual(self.board.latest_status(jid), "done")
        self.assertEqual(self.board.snapshot(jid)["speak"], "Rain later, sir.")
        self.assertEqual(self.board.active(), [])

        jid2 = self.board.enqueue("search", "news")
        self.board.append(
            jid2,
            {"event": "claimed", "worker": "dead", "ts": "2020-01-01T00:00:00Z"},
        )
        retry = self.board.runnable(["search"])
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0]["id"], jid2)


class WorkshopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.reg = WorkshopRegistry(self.home, stale_s=0.2)

    def test_online_and_stale(self) -> None:
        self.assertIn("none", self.reg.prompt_line().lower())
        self.reg.advertise("laptop-matt", ["shell"], roots=["/tmp/src"])
        line = self.reg.prompt_line()
        self.assertIn("laptop-matt", line)
        self.assertIn("shell", line)
        time.sleep(0.25)
        self.assertFalse(self.reg.online()[0]["online"])
        self.assertIn("none", self.reg.prompt_line().lower())
        self.assertFalse(self.reg.has_cap("shell"))


class ClosingTalkMustNotDeleteVault(unittest.TestCase):
    def test_drop_lease_keeps_boot(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        home.take_lease(1)
        boot = home.vault / "BOOT.md"
        text = boot.read_text(encoding="utf-8")
        home.drop_lease(1)
        self.assertTrue(boot.is_file())
        self.assertEqual(boot.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
