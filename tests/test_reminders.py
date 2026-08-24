"""Timed reminders: parse utterances, due once per day."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.reminders import (
    collapse_file,
    file_reminder,
    format_from_utterance,
    from_utterance,
    similar_body,
    take_due,
)
from memory.worker import HostWorker


class ParseTests(unittest.TestCase):
    def test_eight_pm_daily(self) -> None:
        uttered = "remember, I need to check your codebase at 8pm every day"
        rem = from_utterance(uttered)
        self.assertIsNotNone(rem)
        assert rem is not None
        self.assertEqual(rem.hhmm, "20:00")
        self.assertTrue(rem.daily)
        self.assertIn("codebase", rem.text.lower())
        self.assertTrue(format_from_utterance(uttered).startswith("20:00 daily"))

    def test_tea_at_five_is_not_a_clock(self) -> None:
        self.assertIsNone(from_utterance("Remember I take tea at five."))


class DueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        path = self.home.vault / "reminders.md"
        path.write_text(
            "# Reminders\n\n- 20:00 daily - Check Jarvis codebase\n",
            encoding="utf-8",
        )

    def test_not_before_time(self) -> None:
        now = datetime(2026, 8, 23, 19, 59)
        self.assertEqual(take_due(self.home, now=now), [])

    def test_fires_once_when_due(self) -> None:
        now = datetime(2026, 8, 23, 20, 1)
        lines = take_due(self.home, now=now)
        self.assertEqual(len(lines), 1)
        self.assertIn("Check Jarvis codebase", lines[0])
        again = take_due(self.home, now=datetime(2026, 8, 23, 21, 0))
        self.assertEqual(again, [])
        nxt = take_due(self.home, now=datetime(2026, 8, 24, 20, 5))
        self.assertEqual(len(nxt), 1)

    def test_near_duplicate_bullets_speak_once(self) -> None:
        path = self.home.vault / "reminders.md"
        path.write_text(
            "# Reminders\n\n"
            "- 20:00 daily - Check Jarvis codebase\n"
            "- 20:00 daily - check codebase\n"
            "- 20:00 daily - check Jarvis codebase\n"
            "- 20:00 daily - Check the Jarvis codebase\n",
            encoding="utf-8",
        )
        lines = take_due(self.home, now=datetime(2026, 8, 23, 20, 0))
        self.assertEqual(len(lines), 1)
        self.assertIn("codebase", lines[0].lower())
        again = take_due(self.home, now=datetime(2026, 8, 23, 20, 1))
        self.assertEqual(again, [])
        body = path.read_text(encoding="utf-8")
        self.assertEqual(body.lower().count("codebase"), 1)

    def test_file_reminder_skips_similar(self) -> None:
        path = self.home.vault / "reminders.md"
        path.write_text("# Reminders\n\n", encoding="utf-8")
        self.assertTrue(file_reminder(self.home, "20:00 daily - Check Jarvis codebase"))
        self.assertFalse(file_reminder(self.home, "20:00 daily - check the jarvis codebase"))
        body = path.read_text(encoding="utf-8")
        self.assertEqual(body.lower().count("codebase"), 1)

    def test_similar_body(self) -> None:
        self.assertTrue(similar_body("Check Jarvis codebase", "check the codebase"))
        self.assertFalse(similar_body("check the bins", "check the codebase"))

    def test_collapse_keeps_longest(self) -> None:
        path = self.home.vault / "reminders.md"
        path.write_text(
            "# Reminders\n\n"
            "- 20:00 daily - check codebase\n"
            "- 20:00 daily - Check the Jarvis codebase\n",
            encoding="utf-8",
        )
        self.assertEqual(collapse_file(path), 1)
        body = path.read_text(encoding="utf-8")
        self.assertIn("Check the Jarvis codebase", body)
        self.assertNotIn("- 20:00 daily - check codebase\n", body)


class WorkerReminderTests(unittest.TestCase):
    def test_files_structured_bullet(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        board = JobBoard(home)

        def boom(*_a, **_k):
            raise RuntimeError("no grok")

        worker = HostWorker(home, worker_id="host-test", complete=boom)
        uttered = "remember, I need to check your codebase at 8pm every day"
        board.enqueue("vault-write", uttered, extra={"dest": "reminders"})
        self.assertTrue(worker.tick())
        body = (home.vault / "reminders.md").read_text(encoding="utf-8")
        self.assertIn("20:00 daily", body)
        self.assertIn("codebase", body.lower())


if __name__ == "__main__":
    unittest.main()
