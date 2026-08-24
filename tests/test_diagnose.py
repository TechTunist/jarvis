"""Last-job recap for a diagnose cap. No phrase matching."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory.diagnose import inspect
from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.worker import HostWorker


class DiagnoseTests(unittest.TestCase):
    def test_inspect_repeats_last_claim_as_unverified(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "j")
        home.ensure()
        board = JobBoard(home)
        jid = board.enqueue("shell", "start something")
        board.finish(jid, speak="It's open in Brave, sir.", result="ok")
        speak, result = inspect(home)
        self.assertEqual(result, "diagnosed")
        self.assertIn("unverified", speak.lower())
        self.assertIn("Brave", speak)

    def test_worker_diagnose_skips_grok(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "j")
        home.ensure()

        def complete(prompt: str, **kwargs) -> str:
            self.fail("diagnose must not call grok")
            return "nope"

        worker = HostWorker(
            home,
            worker_id="host-test",
            complete=complete,
        )
        with patch(
            "memory.diagnose.inspect",
            return_value=("Something's off. Checking it, sir.", "diagnosed"),
        ):
            speak, result = worker._diagnose({"prompt": "that didn't happen"})
        self.assertEqual(result, "diagnosed")
        self.assertIn("off", speak.lower())
