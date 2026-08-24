"""Phone HUD path: suffixes, ffmpeg stdin, hold/playback script."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PhoneScriptTests(unittest.TestCase):
    def test_phone_html_plays_mpeg_on_element(self) -> None:
        html = (ROOT / "receptionist" / "hud" / "phone.html").read_text(encoding="utf-8")
        self.assertIn("webkit-playsinline", html)
        self.assertIn("recNow.onstop", html)
        self.assertIn("audio/mpeg", html)
        self.assertNotIn("decodeAudioData", html)
        self.assertIn("cancelHold", html)
        self.assertIn("setPointerCapture", html)
        self.assertIn("getUserMedia", html)
        self.assertIn("SILENT_WAV", html)
        self.assertIn("out.loop", html)
        self.assertIn("stopReply", html)
        self.assertIn("revokeObjectURL", html)
        self.assertIn("out.src = SILENT_WAV", html)
        self.assertNotIn('out.src.indexOf("blob:")', html)
        self.assertNotIn("touchstart", html)
        self.assertIn("X-Jarvis-Who", html)
        self.assertIn("jarvis_who", html)
        self.assertIn("/people", html)
        self.assertIn("/people.json", html)
        self.assertIn("Tap your name first", html)
        self.assertIn('hud.state = "listening"', html)
        self.assertNotIn("/glance", html)
        self.assertNotIn("lookOnce", html)
        self.assertIn('state: "listening"', html)
        talk = (ROOT / "receptionist" / "talk.py").read_text(encoding="utf-8")
        self.assertIn("self.hear = True", talk)
        self.assertIn("phone-only", talk)
        self.assertIn("_edge_mp3_only", talk)
        self.assertIn("-nostdin", (ROOT / "receptionist" / "talk.py").read_text(encoding="utf-8"))

    def test_upload_suffix(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "receptionist"))
        sys.path.insert(0, str(ROOT))
        from talk import upload_suffix

        self.assertEqual(upload_suffix("audio/mp4"), ".mp4")
        self.assertEqual(upload_suffix("audio/mp4;codecs=mp4a.40.2"), ".mp4")
        self.assertEqual(upload_suffix("audio/webm;codecs=opus"), ".webm")
        self.assertEqual(upload_suffix("audio/mpeg"), ".mp3")
        self.assertEqual(upload_suffix(""), ".mp4")

    def test_ffmpeg_argv_nostdin(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "receptionist"))
        sys.path.insert(0, str(ROOT))
        from talk import ffmpeg_argv

        argv = ffmpeg_argv("-i", "x.mp4", "pipe:1")
        self.assertIn("-nostdin", argv)
        self.assertEqual(argv[argv.index("-i") + 1], "x.mp4")

    def test_lan_ips_lists_something(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "receptionist"))
        from hud_server import lan_ips

        ips = lan_ips()
        self.assertTrue(ips)
        self.assertTrue(all(":" not in ip for ip in ips))


if __name__ == "__main__":
    unittest.main()
