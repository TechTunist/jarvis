"""Host workshop with a fake grok runner — no network, no GPU."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.session import SessionLog
from memory.grokrun import extract_json, text_from_stream
from memory.worker import HostWorker, append_bullet, dest_path
from memory.workshops import WorkshopRegistry


def fake_complete(prompt: str, **kwargs) -> str:
    if kwargs.get("web"):
        return "Rain later, sir. Take a coat."
    if "Transcript:" in prompt:
        return json.dumps(
            {"facts": [{"dest": "household", "bullet": "Prefers tea at five."}]}
        )
    return json.dumps({"bullet": "Tea at five."})


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)
        self.worker = HostWorker(
            self.home,
            worker_id="host-test",
            complete=fake_complete,
            heartbeat_s=0.01,
        )

    def test_search_and_weather_cache(self) -> None:
        jid = self.board.enqueue("search", "What's the weather in London?")
        self.worker.advertise()
        self.assertTrue(self.worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        self.assertIn("Rain later", snap["speak"])
        weather = (self.home.cache / "weather.md").read_text(encoding="utf-8")
        self.assertIn("Rain later", weather)

    def test_remember_appends_household(self) -> None:
        jid = self.board.enqueue(
            "vault-write",
            "Remember I take tea at five.",
            extra={"dest": "household"},
        )
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.board.latest_status(jid), "done")
        body = (self.home.vault / "people" / "_household.md").read_text(encoding="utf-8")
        self.assertIn("Tea at five", body)
        self.assertTrue(self.worker.tick() is False)

    def test_remember_without_grok_still_files(self) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("no grok")

        worker = HostWorker(self.home, worker_id="host-offline", complete=boom)
        jid = self.board.enqueue("vault-write", "Remember I take tea at five.")
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "done")
        body = (self.home.vault / "people" / "_household.md").read_text(encoding="utf-8")
        self.assertIn("I take tea at five", body)

    def test_distill_files_facts(self) -> None:
        log = SessionLog.start(self.home)
        log.record("Remember I take tea at five.", "Noted, sir.")
        log.close()
        jid = self.board.enqueue(
            "distill",
            "file facts",
            path=str(log.path),
        )
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.board.latest_status(jid), "done")
        household = (self.home.vault / "people" / "_household.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Prefers tea at five", household)

    def test_heartbeat_has_caps(self) -> None:
        self.worker.advertise()
        reg = WorkshopRegistry(self.home)
        self.assertTrue(reg.has_cap("search"))
        self.assertTrue(reg.has_cap("vault-write"))
        self.assertTrue(reg.has_cap("distill"))
        self.assertTrue(reg.has_cap("home"))

    def test_unsupported_cap_fails_job(self) -> None:
        jid = self.board.enqueue("spaceship", "launch")
        worker = HostWorker(
            self.home,
            worker_id="host-test",
            complete=fake_complete,
            caps=("spaceship",),
        )
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "error")

    def test_append_bullet_dedupes(self) -> None:
        path = dest_path(self.home, "household")
        assert path is not None
        self.assertTrue(append_bullet(path, "Tea at five."))
        self.assertFalse(append_bullet(path, "Tea at five."))
        self.assertEqual((self.home.vault / "people" / "_household.md").read_text(encoding="utf-8").count("Tea at five."), 1)

    def test_parent_gone(self) -> None:
        from memory.worker import _parent_gone

        self.assertTrue(_parent_gone(999_999_999))
        self.assertFalse(_parent_gone(os.getpid()))


class GrokrunParseTests(unittest.TestCase):
    def test_extract_json_and_stream_text(self) -> None:
        self.assertEqual(extract_json('{"bullet": "Tea at five."}')["bullet"], "Tea at five.")
        wrapped = 'Sure.\n{"facts": []}\n'
        self.assertEqual(extract_json(wrapped), {"facts": []})
        stream = '{"type":"text","data":"Rain "}\n{"type":"text","data":"later."}\n{"type":"end"}\n'
        self.assertEqual(text_from_stream(stream), "Rain later.")


if __name__ == "__main__":
    unittest.main()
