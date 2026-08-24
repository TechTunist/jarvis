"""Local app catalogue for shell hands."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.apps import brief_for_prompt, match_app, roots_for_shell
from memory.home import JarvisHome
from memory.intent import _shell_root
from memory.workshops import WorkshopRegistry


class AppsTests(unittest.TestCase):
    def test_match_watcher_and_brief(self) -> None:
        app = match_app("start the watcher program")
        self.assertIsNotNone(app)
        assert app is not None
        self.assertEqual(app["id"], "watcher")
        self.assertIn("8765", str(app.get("url") or ""))
        home = JarvisHome(Path(tempfile.mkdtemp()) / "j")
        home.ensure()
        brief = brief_for_prompt(home, "hunt on the watcher")
        self.assertIn("hunt", brief.lower())
        self.assertIn("8765", brief)

    def test_shell_root_picks_watcher_when_advertised(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        watcher = Path(tmp.name) / "watcher"
        watcher.mkdir()
        repo = Path(tmp.name) / "jarvis-src"
        repo.mkdir()
        reg = WorkshopRegistry(home)
        reg.advertise("shell-x", ["shell"], roots=[str(repo), str(watcher)])
        got = _shell_root(reg, "start the watcher")
        self.assertTrue(got)
        self.assertIn("watcher", got.lower())
        self.assertEqual(_shell_root(reg, "run the tests in this repo"), str(repo))
