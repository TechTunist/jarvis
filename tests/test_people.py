"""Speaker roster: names from the household file, vocative, intros."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.people import (
    guest,
    match_intro,
    parse_household,
    public_roster,
    resolve_who,
    vocative,
    with_vocative,
)


SAMPLE = """
# Household
- **Matt** — primary. Address as sir unless asked otherwise.
- **Jack (Jak)** — son. Address as Master Jak.
- **Annabelle** — daughter. Address as Miss Annabelle.
- Weather location is Canterbury
"""


class ParseTests(unittest.TestCase):
    def test_matt_is_sir_jak_is_jak(self) -> None:
        people = parse_household(SAMPLE)
        self.assertEqual([p.slug for p in people], ["matt", "jak", "annabelle"])
        matt = people[0]
        jak = people[1]
        annabelle = people[2]
        self.assertTrue(matt.primary)
        self.assertEqual(vocative(matt), "sir")
        self.assertEqual(jak.name, "Jak")
        self.assertEqual(vocative(jak), "Master Jak")
        self.assertIn("Jack", jak.aliases)
        self.assertEqual(annabelle.name, "Annabelle")
        self.assertEqual(vocative(annabelle), "Miss Annabelle")

    def test_intro_and_guest(self) -> None:
        people = parse_household(SAMPLE)
        self.assertEqual(match_intro("This is Jak", people).slug, "jak")
        self.assertEqual(match_intro("hi, I'm Matt", people).slug, "matt")
        self.assertIsNone(match_intro("it's dark in here", people))
        self.assertIsNone(match_intro("What's the weather", people))
        self.assertIsNone(match_intro("this is embarassing", people))
        self.assertIsNone(match_intro("I'm going to assassinate you", people))
        self.assertIsNone(match_intro("this is Emma", people))
        emma = resolve_who("Emma", people)
        self.assertTrue(emma.guest)
        self.assertEqual(vocative(emma), "Emma")

    def test_with_vocative_swaps_sir(self) -> None:
        jak = parse_household(SAMPLE)[1]
        self.assertEqual(
            with_vocative("I didn't catch that, sir.", jak),
            "I didn't catch that, Master Jak.",
        )
        self.assertEqual(
            with_vocative("I'll have a look at that now, sir.", jak),
            "I'll have a look at that now, Master Jak.",
        )
        self.assertEqual(
            with_vocative("Yes, sir.", parse_household(SAMPLE)[2]),
            "Yes, Miss Annabelle.",
        )
        self.assertEqual(
            with_vocative("Hello.", guest("Emma")),
            "Hello, Emma.",
        )

    def test_public_roster(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        (home.vault / "people" / "_household.md").write_text(SAMPLE, encoding="utf-8")
        rows = public_roster(home)
        self.assertEqual([r["slug"] for r in rows], ["matt", "jak", "annabelle"])
        self.assertEqual(rows[1]["address"], "Master Jak")
        self.assertEqual(rows[2]["address"], "Miss Annabelle")
        self.assertEqual(rows[2]["name"], "Annabelle")


if __name__ == "__main__":
    unittest.main()
