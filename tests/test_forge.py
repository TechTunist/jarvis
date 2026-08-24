"""BearJacked log compacting — no live Supabase."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.forge import compact_log, load_secrets
from memory.home import JarvisHome
from memory.intent import FORGE, classify
from memory.jobs import JobBoard
from memory.worker import HostWorker
from memory.workshops import WorkshopRegistry


class CompactLogTests(unittest.TestCase):
    def test_summarises_sets(self) -> None:
        workouts = [
            {
                "date": "2026-08-20",
                "name": "Push",
                "duration": 54,
                "exercises": [
                    {
                        "name": "Bench Press",
                        "sets": [
                            {"reps": 5, "weight": 80, "completed": True},
                            {"reps": 5, "weight": 80, "completed": True},
                        ],
                    }
                ],
            }
        ]
        weights = [{"logged_date": "2026-08-18", "weight": 86.2}]
        text = compact_log(workouts, weights)
        self.assertIn("Bench Press", text)
        self.assertIn("80", text)
        self.assertIn("86.2", text)

    def test_empty(self) -> None:
        self.assertEqual(compact_log([], []), "No training rows.")


class ForgeIntentTests(unittest.TestCase):
    def test_classify(self) -> None:
        self.assertEqual(classify("how was my last workout").cap, FORGE.cap)
        self.assertEqual(classify("what did I lift").cap, FORGE.cap)
        self.assertEqual(classify("What's the weather?").cap, "search")


class ForgeWorkerTests(unittest.TestCase):
    def test_missing_secrets(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        self.assertEqual(load_secrets(home), {})
        worker = HostWorker(
            home, worker_id="host-test", complete=lambda *_a, **_k: "unused"
        )
        board = JobBoard(home)
        jid = board.enqueue("forge", "how was my last workout")
        self.assertTrue(worker.tick())
        snap = board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        self.assertIn("not configured", str(snap.get("speak") or "").lower())


if __name__ == "__main__":
    unittest.main()
