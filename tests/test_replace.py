"""Replace in-flight work only after a spoken confirm. No per-job vocabulary."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.replace import (
    ask,
    confirm_line,
    contended,
    job_label,
    keep_line,
    pending,
)
from memory.workshops import WorkshopRegistry
from memory.worker import HostWorker


class LabelTests(unittest.TestCase):
    def test_label_is_his_words_not_a_cap_name(self) -> None:
        self.assertEqual(
            job_label("Bitcoin price right now."),
            "Bitcoin price right now",
        )
        self.assertEqual(
            job_label("What's the weather today Jarvis?"),
            "What's the weather today",
        )
        self.assertIn(
            "bitcoin price",
            confirm_line(
                job_label("Bitcoin price right now."),
                job_label("What's the weather today, Jarvis?"),
            ).lower(),
        )
        self.assertIn(
            "weather today",
            confirm_line(
                job_label("Bitcoin price right now."),
                job_label("What's the weather today, Jarvis?"),
            ).lower(),
        )
        self.assertTrue(
            confirm_line("that job", "this job").startswith("Are you sure")
        )

    def test_keep_line_uses_the_same_label(self) -> None:
        self.assertIn("bitcoin price", keep_line("bitcoin price").lower())


class ContendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)
        self.reg = WorkshopRegistry(self.home)
        self.reg.advertise("host", ["search", "imagine", "home"])
        self.reg.advertise("shell", ["shell"])

    def test_same_worker_is_contended_other_worker_is_not(self) -> None:
        jid = self.board.enqueue("search", "Bitcoin price right now.")
        self.board.claim(jid, "host")
        busy = contended(self.board, self.reg, "search")
        self.assertEqual(len(busy), 1)
        self.assertEqual(busy[0]["id"], jid)
        also = contended(self.board, self.reg, "imagine")
        self.assertEqual(len(also), 1)
        free = contended(self.board, self.reg, "shell")
        self.assertEqual(free, [])

    def test_chat_cap_is_never_contended(self) -> None:
        self.board.enqueue("search", "Bitcoin price right now.")
        self.assertEqual(contended(self.board, self.reg, None), [])

    def test_ask_stores_both_prompts(self) -> None:
        jid = self.board.enqueue("search", "Bitcoin price right now.")
        snaps = [self.board.snapshot(jid)]
        line = ask(
            self.home,
            current=snaps,
            next_prompt="What's the weather today Jarvis?",
            next_cap="search",
        )
        self.assertIn("Bitcoin price", line)
        self.assertIn("weather today", line)
        doc = pending(self.home)
        assert doc is not None
        self.assertEqual(doc["cancel_ids"], [jid])
        self.assertEqual(doc["next_cap"], "search")

    def test_tick_does_not_finish_a_cancelled_job(self) -> None:
        box: dict[str, str] = {}

        def complete(*_a, **_k):
            self.board.cancel(box["id"], reason="replaced")
            return "late speak"

        worker = HostWorker(
            self.home,
            worker_id="host-test",
            caps=("search",),
            complete=complete,
        )
        jid = self.board.enqueue("search", "Bitcoin price right now.")
        box["id"] = jid
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "cancelled")
        self.assertNotEqual(self.board.snapshot(jid).get("speak"), "late speak")


if __name__ == "__main__":
    unittest.main()
