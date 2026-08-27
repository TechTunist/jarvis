"""HUD assets exist so the desktop face can boot without a CDN."""
from __future__ import annotations

import sys
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
        self.assertIn("svc:jarvis", src)
        self.assertIn("advertise_phone_door", src)

    def test_phone_url_follows_the_service_not_the_pc(self) -> None:
        sys.path.insert(0, str(ROOT / "receptionist"))
        from hud_server import phone_url_from_dns

        self.assertEqual(
            phone_url_from_dns("xps.tail9f6146.ts.net."),
            "https://jarvis.tail9f6146.ts.net/phone",
        )
        self.assertEqual(phone_url_from_dns(""), "")


if __name__ == "__main__":
    unittest.main()
