"""HUD assets exist so the desktop face can boot without a CDN."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUD = ROOT / "receptionist" / "hud"


class HudAssetsTests(unittest.TestCase):
    def test_desktop_hud_files(self) -> None:
        self.assertTrue((HUD / "index.html").is_file())
        self.assertTrue((HUD / "hud.js").is_file())
        vendor = HUD / "vendor" / "three.module.min.js"
        self.assertTrue(vendor.is_file(), "vendor three.js missing")
        self.assertGreater(vendor.stat().st_size, 50_000)
        html = (HUD / "index.html").read_text(encoding="utf-8")
        self.assertIn("./hud.js", html)
        js = (HUD / "hud.js").read_text(encoding="utf-8")
        self.assertIn("three", js.lower())
        self.assertIn("/state", js)

    def test_server_serves_javascript_mime(self) -> None:
        src = (ROOT / "receptionist" / "hud_server.py").read_text(encoding="utf-8")
        self.assertIn("text/javascript", src)
        self.assertIn(".js", src)


if __name__ == "__main__":
    unittest.main()
