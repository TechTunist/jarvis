"""Opt-in stills. No camera in CI."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.eyes import save_still, wants_screen
from memory.grokrun import prompt_argv
from memory.home import JarvisHome


class EyesTests(unittest.TestCase):
    def test_save_still_and_screen_hint(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        dest = save_still(home, b"\xff\xd8\xff\xd9", suffix=".jpg")
        self.assertTrue(dest.is_file())
        self.assertIn("eyes", str(dest))
        self.assertTrue(wants_screen("look at the screen"))
        self.assertFalse(wants_screen("have a look at this"))

    def test_prompt_argv_never_attaches_a_still(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        img = Path(tmp.name) / "x.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")
        argv = prompt_argv(
            "What do you see?",
            grok=Path("/tmp/grok"),
            model="grok-4.6",
            system="sys",
            web=False,
            image=img,
        )
        joined = " ".join(argv)
        self.assertIn("-p", argv)
        self.assertNotIn("--prompt-file", argv)
        self.assertNotIn("--prompt-json", argv)
        self.assertNotIn("image/jpeg", joined)


if __name__ == "__main__":
    unittest.main()
