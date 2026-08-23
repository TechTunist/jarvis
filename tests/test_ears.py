"""Mic picker and STT vocab. No Whisper, no audio hardware."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.ears import (
    cache_ha_names,
    list_inputs,
    pick_input,
    rms_peak,
    vocabulary,
)
from memory.home import JarvisHome


DEVICES = [
    {"name": "HDA Intel PCH: ALC3271 Analog (hw:0,0)", "max_input_channels": 2},
    {"name": "HDMI", "max_input_channels": 2},
    {"name": "Focusrite Scarlett 2i2", "max_input_channels": 2},
    {"name": "pulse", "max_input_channels": 32},
    {"name": "speexrate", "max_input_channels": 128},
]


class MicPickTests(unittest.TestCase):
    def test_prefers_focusrite(self) -> None:
        rows = list_inputs(DEVICES)
        names = [r["name"] for r in rows]
        self.assertIn("Focusrite Scarlett 2i2", names)
        self.assertNotIn("HDMI", names)
        self.assertNotIn("speexrate", names)
        chosen = pick_input(DEVICES)
        self.assertEqual(chosen["name"], "Focusrite Scarlett 2i2")
        self.assertEqual(chosen["kind"], "usb")

    def test_substring_and_index(self) -> None:
        self.assertEqual(pick_input(DEVICES, want="ALC")["kind"], "builtin")
        self.assertEqual(pick_input(DEVICES, want="2")["name"], "Focusrite Scarlett 2i2")

    def test_builtin_when_nothing_else(self) -> None:
        only = [{"name": "HDA Intel PCH: ALC3271 Analog", "max_input_channels": 2}]
        chosen = pick_input(only)
        self.assertEqual(chosen["kind"], "builtin")


class VocabTests(unittest.TestCase):
    def test_includes_household_and_ha_names(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        people = home.vault / "people" / "_household.md"
        people.write_text("**Jak** lives here.\n**Matt** is primary.\n", encoding="utf-8")
        cache_ha_names(home, ["Jak's Light", "Living Room Main Light", "Lamp"])
        prompt, hot = vocabulary(home)
        self.assertIn("Jarvis", prompt)
        self.assertIn("Jak", prompt)
        self.assertIn("Lamp", prompt)
        self.assertIn("Jak", hot)


class LevelTests(unittest.TestCase):
    def test_rms_peak(self) -> None:
        rms, peak = rms_peak([0.0, 0.5, -0.5, 0.0])
        self.assertGreater(peak, 0.49)
        self.assertGreater(rms, 0.2)


if __name__ == "__main__":
    unittest.main()
