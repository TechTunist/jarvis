"""Session working memory: weather place + recent turns, not the whole vault."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.session import SessionLog
from memory.jobs import JobBoard
from memory.working import (
    desk_prefix,
    hands_brief,
    looks_like_weather,
    pack_recent,
    search_prompt,
    spoken_user,
    weather_fresh,
    weather_place,
    workshop_brief,
)
from memory.bench import bench_note


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

    def test_bench_note_is_on_the_mouth(self) -> None:
        dest = self.home.root / "bench"
        dest.mkdir(parents=True)
        (dest / "scene.json").write_text(
            json.dumps(
                {
                    "units": "mm",
                    "parts": [
                        {"id": "p1", "name": "post 1"},
                        {"id": "p2", "name": "rafter 1"},
                    ],
                    "project": {"id": "pergola", "name": "pergola"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (dest / "projects.json").write_text(
            json.dumps(
                {
                    "current": "pergola",
                    "previous": "",
                    "projects": [{"id": "pergola", "name": "pergola", "parts": 2}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        note = bench_note(self.home)
        self.assertIn("pergola", note.lower())
        self.assertIn("2 parts", note)
        pre = desk_prefix(self.home)
        self.assertIn("[bench]", pre)
        self.assertIn("pergola", pre.lower())
        self.assertIn("[kit]", pre)
        self.assertIn("ESP32-S3-DevKitC-1", pre)
        named = desk_prefix(self.home, asked="the pallet pergola rafters")
        self.assertIn("[projects]", named)
        self.assertIn("[project:pergola]", named)
        node = desk_prefix(self.home, asked="what ESP devices do we have for the room node")
        self.assertIn("[project:room-node]", node)
        self.assertIn("DevKitC-1", node)

    def test_daily_brief_only_on_checkin(self) -> None:
        from datetime import date

        from memory.brief import assemble_brief, wants_brief

        (self.home.cache / "weather.md").write_text(
            "Fair in Canterbury.\n\n_cached 2026-08-29 10:00 UTC_\n",
            encoding="utf-8",
        )
        (self.home.vault / "calendar.md").write_text(
            f"- {date.today().isoformat()} - Dentist 09:00\n",
            encoding="utf-8",
        )
        body = assemble_brief(self.home)
        self.assertIn("Fair in Canterbury", body)
        self.assertIn("Dentist", body)
        self.assertIn("20:00 daily", body)
        self.assertTrue(wants_brief("how are you"))
        self.assertTrue(wants_brief("what's going on"))
        self.assertTrue(wants_brief("anything I should know"))
        self.assertFalse(wants_brief("hello jarvis"))
        self.assertFalse(wants_brief("lamp on"))
        self.assertFalse(wants_brief("what are the headlines"))
        hello = desk_prefix(self.home, asked="hello jarvis")
        self.assertNotIn("[brief]", hello)
        self.assertNotIn("Dentist", hello)
        check = desk_prefix(self.home, asked="how are you")
        self.assertIn("[brief]", check)
        self.assertIn("Dentist", check)

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

    def test_hands_brief_and_fresh_weather(self) -> None:
        self.assertTrue(looks_like_weather("what's the weather this week"))
        self.assertFalse(looks_like_weather("look up the Premier League table"))
        cache = self.home.cache / "weather.md"
        cache.write_text("Rain later.\n", encoding="utf-8")
        self.assertTrue(weather_fresh(self.home))
        board = JobBoard(self.home)
        jid = board.enqueue("imagine", "draw a cat")
        board.claim(jid, "host-a")
        board.progress(jid, "Drawing that.")
        brief = hands_brief(self.home)
        self.assertIn("imagine", brief)
        self.assertIn("Drawing that", brief)
        pre = desk_prefix(self.home)
        self.assertIn("[hands]", pre)
        self.assertIn("Canterbury", pre)
        board.finish(jid, speak="Thirteen deals on the board, sir.", result="ok")
        pre = desk_prefix(self.home)
        self.assertIn("[last jobs]", pre)
        self.assertIn("Thirteen deals", pre)

    def test_pack_recent_keeps_jarvis_initiated_lines(self) -> None:
        log = SessionLog.start(self.home)
        log.record("[reminder]", "It's time, sir. Check Jarvis codebase.")
        log.record(
            "im working on the codebase now jarvis, thanks or the reminder",
            "I'll leave you to it, sir.",
        )
        packed = pack_recent(self.home)
        self.assertIn("It's time, sir. Check Jarvis codebase.", packed)
        self.assertNotIn("You: [reminder]", packed)
        self.assertIn("You: im working on the codebase now", packed)
        self.assertIn("Jarvis: I'll leave you to it, sir.", packed)


if __name__ == "__main__":
    unittest.main()
