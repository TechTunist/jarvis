"""Laptop shell workshop — no Grok, no git network."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.shell import (
    looks_like_tests,
    refuse_reason,
    repo_root,
    run_unittests,
    speak_from_grok,
    speak_tests,
)
from memory.worker import HOST_CAPS, HostWorker
from memory.workshops import WorkshopRegistry


def _tiny_repo(root: Path, *, failing: bool = False) -> Path:
    tests = root / "tests"
    tests.mkdir(parents=True)
    body = (
        "import unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        f"        self.assertTrue({False if failing else True})\n"
    )
    (tests / "test_ok.py").write_text(body, encoding="utf-8")
    return root


class ShellDomainTests(unittest.TestCase):
    def test_looks_like_tests(self) -> None:
        self.assertTrue(looks_like_tests("Run the tests in this repo"))
        self.assertTrue(looks_like_tests("please run the tests"))
        self.assertTrue(looks_like_tests("run pytest"))
        self.assertFalse(looks_like_tests("run the tests and fix failures"))
        self.assertFalse(looks_like_tests("patch intent.py"))
        self.assertFalse(looks_like_tests("turn on the lamp"))

    def test_refuse_merge_push_restart(self) -> None:
        self.assertIn("merge", refuse_reason("merge that to main").lower())
        self.assertIn("push", refuse_reason("git push origin main").lower())
        self.assertIn("restart", refuse_reason("restart Talk").lower())
        self.assertEqual(refuse_reason("Run the tests in this repo"), "")
        self.assertEqual(refuse_reason("patch the intent gate"), "")

    def test_speak_tests(self) -> None:
        speak, result = speak_tests(0, "Ran 12 tests in 0.4s\n\nOK\n", "")
        self.assertEqual(speak, "All 12 tests passed, sir.")
        self.assertEqual(result, "ok:12")
        speak, result = speak_tests(
            1, "", "Ran 12 tests in 0.4s\n\nFAILED (failures=2, errors=1)\n"
        )
        self.assertEqual(speak, "3 tests failed, sir.")
        self.assertEqual(result, "fail:3")

    def test_speak_from_grok_json(self) -> None:
        speak, result = speak_from_grok(
            json.dumps(
                {
                    "speak": "Patch is on branch jarvis/workshop-intent.",
                    "ok": True,
                    "branch": "jarvis/workshop-intent",
                }
            )
        )
        self.assertIn("workshop-intent", speak)
        self.assertEqual(result, "jarvis/workshop-intent")

    def test_repo_root_is_this_checkout(self) -> None:
        root = repo_root()
        self.assertTrue((root / "memory" / "worker.py").is_file())
        self.assertTrue((root / ".git").exists())

    def test_run_unittests_tiny_repo(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = _tiny_repo(Path(tmp.name) / "repo")
        speak, result = run_unittests(repo)
        self.assertIn("passed", speak.lower())
        self.assertTrue(result.startswith("ok:"))
        bad = _tiny_repo(Path(tmp.name) / "bad", failing=True)
        speak, result = run_unittests(bad)
        self.assertIn("failed", speak.lower())
        self.assertTrue(result.startswith("fail:"))


class ShellWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)
        self.repo = _tiny_repo(Path(self.tmp.name) / "repo").resolve()

    def test_host_does_not_advertise_shell(self) -> None:
        worker = HostWorker(self.home, worker_id="host-test", complete=lambda *_a, **_k: "")
        worker.advertise()
        reg = WorkshopRegistry(self.home)
        self.assertTrue(reg.has_cap("search"))
        self.assertFalse(reg.has_cap("shell"))
        self.assertNotIn("shell", HOST_CAPS)

    def test_shell_worker_runs_unittests(self) -> None:
        worker = HostWorker(
            self.home,
            worker_id="shell-test",
            caps=("shell",),
            repo=self.repo,
            complete=lambda *_a, **_k: self.fail("grok should not run for tests"),
        )
        worker.advertise()
        self.assertTrue(WorkshopRegistry(self.home).has_cap("shell"))
        jid = self.board.enqueue("shell", "Run the tests in this repo")
        self.assertTrue(worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        self.assertIn("passed", str(snap.get("speak") or "").lower())

    def test_shell_refuses_merge_without_grok(self) -> None:
        worker = HostWorker(
            self.home,
            worker_id="shell-test",
            caps=("shell",),
            repo=self.repo,
            complete=lambda *_a, **_k: self.fail("grok should not run"),
        )
        jid = self.board.enqueue("shell", "merge that to main")
        self.assertTrue(worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        self.assertIn("won't merge", str(snap.get("speak") or "").lower())
        self.assertEqual(snap.get("result"), "refused")

    def test_shell_patch_allowlists_tools(self) -> None:
        seen: dict = {}

        def complete(prompt: str, **kwargs) -> str:
            seen.update(kwargs)
            seen["prompt"] = prompt
            return json.dumps(
                {
                    "speak": "Patch is on branch jarvis/workshop-intent.",
                    "ok": True,
                    "branch": "jarvis/workshop-intent",
                }
            )

        worker = HostWorker(
            self.home,
            worker_id="shell-test",
            caps=("shell",),
            repo=self.repo,
            complete=complete,
        )
        jid = self.board.enqueue("shell", "Patch intent.py to rotate acks")
        self.assertTrue(worker.tick())
        self.assertTrue(seen.get("subagents"))
        self.assertEqual(seen.get("effort"), "high")
        self.assertIn("image_gen", str(seen.get("disallowed") or ""))
        self.assertEqual(Path(str(seen.get("cwd"))), self.repo)
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        self.assertIn("workshop-intent", str(snap.get("speak") or ""))


if __name__ == "__main__":
    unittest.main()
