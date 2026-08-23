"""Local intent gate: false positives steal hellos."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.intent import (
    CHAT,
    CODE,
    HOME,
    REMEMBER,
    SEARCH,
    classify,
    file_line,
    maybe_enqueue,
    remember_dest,
)
from memory.jobs import JobBoard
from memory.workshops import WorkshopRegistry


class ClassifyTests(unittest.TestCase):
    def test_chat_is_the_default(self) -> None:
        for text in (
            "Hello Jarvis",
            "How are you?",
            "Remember me?",
            "Search your feelings",
            "Turn on the charm",
            "That's news to me",
            "I need to commit to this diet",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).kind, CHAT.kind)

    def test_search(self) -> None:
        for text in (
            "What's the weather in London?",
            "Look up the Premier League table",
            "Search for the nearest pharmacy",
            "What are the headlines?",
            "What's the stock price of Tesla?",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).cap, SEARCH.cap)

    def test_remember(self) -> None:
        self.assertEqual(classify("Remember I take tea at five.").cap, REMEMBER.cap)
        self.assertEqual(classify("Please remember that Matt hates beets.").kind, "remember")
        self.assertEqual(classify("Don't forget I work from home on Fridays.").kind, "remember")
        self.assertEqual(classify("Never do that again.").kind, "remember")
        self.assertEqual(remember_dest("Never do that again."), "never")
        self.assertEqual(remember_dest("Remember I take tea at five."), "household")

    def test_remember_comma_and_timed_reminder(self) -> None:
        uttered = "remember, I need to check your codebase at 8pm every day"
        self.assertEqual(classify(uttered).cap, REMEMBER.cap)
        self.assertEqual(remember_dest(uttered), "reminders")
        self.assertEqual(classify("Remind me at 8pm to check the codebase").cap, REMEMBER.cap)
        self.assertEqual(classify("Set a reminder for 8pm").kind, "remember")
        self.assertEqual(remember_dest("Set a reminder for 8pm"), "reminders")

    def test_home_needs_a_house_noun(self) -> None:
        self.assertEqual(classify("Turn on the kitchen lights").cap, HOME.cap)
        self.assertEqual(classify("turn the kitchen lights off").cap, HOME.cap)
        self.assertEqual(classify("Let me turn on the lamp, please.").cap, HOME.cap)
        self.assertEqual(classify("Is the garage closed?").cap, HOME.cap)
        self.assertEqual(classify("Unlock the door").cap, HOME.cap)
        self.assertEqual(classify("Turn on the radio").kind, CHAT.kind)

    def test_code_is_conservative(self) -> None:
        self.assertEqual(classify("Run the tests in this repo").cap, CODE.cap)
        self.assertEqual(classify("Edit talk.py please").kind, CHAT.kind)
        self.assertEqual(classify("Edit talk.py in the repo").cap, CODE.cap)

    def test_file_line_strips_wrapper(self) -> None:
        self.assertEqual(file_line("Remember I take tea at five."), "I take tea at five")
        self.assertEqual(file_line("Please remember that Matt hates beets."), "Matt hates beets")
        self.assertTrue(
            file_line("remember, I need to check your codebase at 8pm every day")
            .lower()
            .startswith("i need")
        )


class EnqueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)
        self.reg = WorkshopRegistry(self.home)

    def test_chat_does_not_enqueue(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(maybe_enqueue("Hello Jarvis", self.board, self.reg))

    def test_search_without_worker_falls_through(self) -> None:
        self.assertIsNone(maybe_enqueue("What's the weather?", self.board, self.reg))
        self.assertEqual(self.board.job_ids(), [])

    def test_search_with_worker_enqueues(self) -> None:
        self.reg.advertise("host", ["search"])
        hit = maybe_enqueue("What's the weather in London?", self.board, self.reg)
        self.assertIsNotNone(hit)
        assert hit is not None
        intent, job_id = hit
        self.assertEqual(intent.cap, "search")
        self.assertEqual(self.board.latest_status(job_id), "enqueued")

    def test_remember_needs_vault_write_cap(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(maybe_enqueue("Remember I take tea at five.", self.board, self.reg))
        self.reg.advertise("host", ["search", "vault-write"])
        hit = maybe_enqueue("Remember I take tea at five.", self.board, self.reg)
        self.assertIsNotNone(hit)


if __name__ == "__main__":
    unittest.main()
