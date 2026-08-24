"""Mouth can request hands without a phrase catalogue."""
from __future__ import annotations

import unittest

from memory.dispatch import audible, intents_from_mouth, parse_hands, strip_hands
from memory.intent import CODE, SEARCH


class DispatchTests(unittest.TestCase):
    def test_parse_and_strip(self) -> None:
        raw = (
            "I'll look at those listings now, sir.\n"
            "[hands:shell] curl watcher deals and say which are complete computers"
        )
        self.assertEqual(parse_hands(raw)[0][0], "shell")
        self.assertIn("complete computers", parse_hands(raw)[0][1])
        self.assertEqual(strip_hands(raw), "I'll look at those listings now, sir.")

    def test_intents(self) -> None:
        jobs = intents_from_mouth(
            "One moment.\n[hands:search] bitcoin price\n",
            "what's bitcoin",
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0][1].cap, SEARCH.cap)
        jobs = intents_from_mouth(
            "[hands:shell] start watcher and open the UI",
            "start watcher",
        )
        self.assertEqual(jobs[0][1].cap, CODE.cap)
        self.assertEqual(
            intents_from_mouth("Hello sir.", "hi"),
            [],
        )
        self.assertEqual(intents_from_mouth("[hands:chat] nope", "hi"), [])

    def test_hands_payload_is_not_for_ears(self) -> None:
        raw = (
            "I'll have a look at the board, sir. "
            "[hands:shell] Fetch Watcher at http://127.0.0.1:8765 (curl or similar). "
            "Summarise the search results/deals on the board: titles, prices, counts. "
            "Do not restart the server or open another browser window."
        )
        self.assertEqual(strip_hands(raw), "I'll have a look at the board, sir.")
        self.assertIn("shell", parse_hands(raw)[0][0])
        self.assertIn("Summarise", parse_hands(raw)[0][1])
        self.assertNotIn("Summarise", strip_hands(raw))
        self.assertNotIn("Do not restart", strip_hands(raw))

    def test_audible_drops_planning_aside(self) -> None:
        speak = (
            "Checking typical UK asking prices for a working used Lifebook U728 "
            "so I can judge the £90 listing.Sir, a working U728 on UK Gumtree is "
            "usually about a hundred to a hundred and thirty."
        )
        heard = audible(speak)
        self.assertNotIn("Checking typical", heard)
        self.assertIn("hundred and thirty", heard)
        self.assertIn("sir", heard.lower())
