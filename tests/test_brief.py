"""Daily brief stays off the mouth unless he asked, or a check-in."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from memory.brief import (
    assemble_brief,
    looks_like_news,
    news_fresh,
    wants_brief,
    wants_checkin,
)
from memory.home import JarvisHome
from memory.working import desk_prefix


class BriefGateTests(unittest.TestCase):
    def test_checkin_phrases(self) -> None:
        for text in (
            "how are you",
            "How are you?",
            "how are you doing today",
            "how are you this morning",
            "how's it going",
            "how's it going, jarvis",
            "how are things",
            "what's going on",
            "what's happening",
            "what's up",
            "anything I should know",
            "catch me up",
            "fill me in",
            "so how are you",
        ):
            with self.subTest(text=text):
                self.assertTrue(wants_checkin(text), text)
                self.assertTrue(wants_brief(text), text)

    def test_hello_is_not_a_brief(self) -> None:
        for text in (
            "hello",
            "hello jarvis",
            "hi",
            "good morning",
            "thanks",
            "lamp on",
            "how's it going with the animation",
            "what are the headlines",
            "what's the weather",
        ):
            with self.subTest(text=text):
                self.assertFalse(wants_brief(text), text)
                self.assertFalse(wants_checkin(text), text)

    def test_explicit_day_prompt(self) -> None:
        self.assertTrue(wants_brief("daily brief"))
        self.assertTrue(wants_brief("what's on today"))
        self.assertTrue(wants_brief("what are my reminders"))
        self.assertTrue(wants_brief("what's on the calendar"))
        self.assertFalse(wants_checkin("daily brief"))

    def test_news_is_not_the_full_brief(self) -> None:
        self.assertTrue(looks_like_news("what are the headlines"))
        self.assertFalse(wants_brief("what are the headlines"))


class AssembleBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()

    def test_assembles_local_bits_and_skips_stale_news(self) -> None:
        today = date(2026, 8, 29)
        (self.home.cache / "weather.md").write_text(
            "Fair in Canterbury.\n\n_cached 2026-08-29 10:00 UTC_\n",
            encoding="utf-8",
        )
        (self.home.vault / "calendar.md").write_text(
            "- 2026-08-29 - Dentist 09:00\n"
            "- weekly Sat - Shop run\n",
            encoding="utf-8",
        )
        (self.home.cache / "news.md").write_text("Old headline.\n", encoding="utf-8")
        body = assemble_brief(self.home, today=today, now=1_000_000_000)
        self.assertIn("Saturday 29 Aug 2026", body)
        self.assertIn("Dentist", body)
        self.assertIn("Shop run", body)
        self.assertIn("Fair in Canterbury", body)
        self.assertIn("20:00 daily", body)
        self.assertNotIn("Old headline", body)
        self.assertFalse(news_fresh(self.home, now=1_000_000_000))

    def test_desk_prefix_only_on_checkin(self) -> None:
        (self.home.cache / "weather.md").write_text("Fair in Canterbury.\n", encoding="utf-8")
        (self.home.vault / "calendar.md").write_text(
            f"- {date.today().isoformat()} - Dentist 09:00\n",
            encoding="utf-8",
        )
        (self.home.cache / "news.md").write_text("SPCX quiet.\n", encoding="utf-8")
        hello = desk_prefix(self.home, asked="hello jarvis")
        self.assertNotIn("[brief]", hello)
        self.assertNotIn("[weather]", hello)
        self.assertNotIn("[news]", hello)
        self.assertNotIn("Dentist", hello)
        self.assertNotIn("Fair in Canterbury", hello)
        check = desk_prefix(self.home, asked="what's going on")
        self.assertIn("[brief]", check)
        self.assertIn("Dentist", check)
        self.assertIn("Fair in Canterbury", check)
        wx = desk_prefix(self.home, asked="what's the weather")
        self.assertNotIn("[brief]", wx)
        self.assertIn("[weather]", wx)
        self.assertIn("Fair in Canterbury", wx)
        news = desk_prefix(self.home, asked="what are the headlines")
        self.assertNotIn("[brief]", news)
        self.assertIn("[news]", news)
        self.assertIn("SPCX quiet", news)
        self.assertNotIn("Dentist", news)
