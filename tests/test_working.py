"""Session working memory: weather place + recent turns, not the whole vault."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.session import SessionLog
from memory.working import (
    pack_recent,
    search_prompt,
    spoken_user,
    weather_place,
    workshop_brief,
)


class WorkingMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        household = self.home.vault / "people" / "_household.md"
        household.write_text(
            "- Home weather location is Canterbury, Kent, UK\n",
            encoding="utf-8",
        )

    def test_weather_place_and_search_prompt(self) -> None:
        self.assertEqual(weather_place(self.home), "Canterbury, Kent, UK")
        log = SessionLog.start(self.home)
        log.record("change the weather to Canterbury", "I'll file that, sir.")
        log.record("what is the weather like today", "Which city, sir?")
        asked = search_prompt(self.home, "what is the weather like today")
        self.assertIn("Canterbury", asked)
        self.assertIn("what is the weather like today", asked)
        self.assertIn("You:", pack_recent(self.home))

    def test_spoken_user_strips_working_memory_prefix(self) -> None:
        blob = (
            "[working memory — this session only]\n"
            "Weather location: Canterbury, Kent, UK.\n"
            "Use this if Matt refers to something he just said.\n\n"
            "Matt: it is a little dark in the living room"
        )
        self.assertEqual(
            spoken_user(blob), "it is a little dark in the living room"
        )
        log = SessionLog.start(self.home)
        log.record(blob, "I'll brighten that, sir.")
        packed = pack_recent(self.home)
        self.assertIn("it is a little dark in the living room", packed)
        self.assertNotIn("[working memory", packed)

    def test_workshop_brief_keeps_todays_spec_across_restart(self) -> None:
        log = SessionLog.start(self.home)
        spec = (
            "Cloneable Wi-Fi room nodes: ESP32-S3, MEMS capsule, "
            "reclaimed vape cells through a BMS with USB-C charging, "
            "mute switch and status LED, MQTT back to host-xps."
        )
        log.record(
            "engineering a wireless microphone specification",
            spec,
        )
        log.close()
        SessionLog.start(self.home)
        brief = workshop_brief(
            self.home, "create an animation of how the parts go together and a pdf"
        )
        self.assertIn("ESP32-S3", brief)
        self.assertIn("BMS", brief)
        self.assertIn("Matt asked:", brief)


if __name__ == "__main__":
    unittest.main()
