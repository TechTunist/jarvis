"""Queued user lines become one desk turn, not a pile of replies."""
from __future__ import annotations

import unittest

from memory.batch import coalesce_chat, is_ping, latest_wins, split_batch
from memory.intent import classify


class BatchTests(unittest.TestCase):
    def test_holographic_animation_is_imagine(self) -> None:
        text = (
            "create a cool Iron Man looking holographic animation "
            "that resembles a scene from the movie"
        )
        self.assertEqual(classify(text).cap, "imagine")

    def test_generate_a_report_stays_chat(self) -> None:
        self.assertEqual(classify("Generate a report").kind, "chat")

    def test_half_done_is_status(self) -> None:
        self.assertEqual(
            classify("let me knoe when half done pleae").kind, "status"
        )

    def test_split_uses_resolved_intents(self) -> None:
        from memory.intent import HOME

        jobs, status, chat = split_batch(
            ["kill the glow by the sofa", "hello?"],
            intents=[HOME, classify("hello?")],
        )
        self.assertEqual(jobs, ["kill the glow by the sofa"])
        self.assertEqual(chat, ["hello?"])
        self.assertEqual(status, [])

    def test_split_and_coalesce(self) -> None:
        jobs, status, chat = split_batch(
            [
                "create a quick animation of an arsenal badge",
                "hello?",
                "anyone there?",
                "what's for dinner",
            ]
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(chat[-1], "what's for dinner")
        prompt = coalesce_chat(
            ["hello?", "anyone there?", "what's for dinner"], occupied=True
        )
        self.assertIn("occupied", prompt.lower())
        self.assertIn("what's for dinner", prompt)
        self.assertIn("ONE short reply", prompt)

    def test_single_chat_is_verbatim(self) -> None:
        self.assertEqual(coalesce_chat(["Hello Jarvis"]), "Hello Jarvis")

    def test_ping(self) -> None:
        self.assertTrue(is_ping("hello?"))
        self.assertTrue(is_ping("anyone there"))
        self.assertFalse(is_ping("what's for dinner"))

    def test_latest_wins_drops_backlog(self) -> None:
        items = [
            ("what's the time", None),
            ("is that gmt", None),
            ("stop talking", None),
        ]
        got = latest_wins(items)
        self.assertEqual(got, [("stop talking", None)])

    def test_latest_wins_keeps_quit(self) -> None:
        got = latest_wins(
            [("old command", 1), ("newest", 2), ("__quit__", None)]
        )
        self.assertEqual([t for t, _ in got], ["newest", "__quit__"])

    def test_latest_wins_quiet_only(self) -> None:
        self.assertEqual(latest_wins([("__quiet__", None)]), [("__quiet__", None)])


if __name__ == "__main__":
    unittest.main()
