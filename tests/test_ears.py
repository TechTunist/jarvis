"""Mic picker and STT vocab. No Whisper, no audio hardware."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.ears import (
    EnergyGate,
    after_wake,
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


class EnergyGateTests(unittest.TestCase):
    def test_silence_stays_idle(self) -> None:
        g = EnergyGate()
        for _ in range(40):
            self.assertEqual(g.feed(0.001), "idle")

    def test_click_does_not_start(self) -> None:
        g = EnergyGate(start_n=4)
        self.assertEqual(g.feed(0.2, 0.2), "idle")
        self.assertEqual(g.feed(0.2, 0.2), "idle")
        self.assertEqual(g.feed(0.001, 0.001), "idle")

    def test_speech_then_silence_ends(self) -> None:
        g = EnergyGate(start_n=3, end_n=4, min_n=3, max_n=80)
        for _ in range(20):
            g.feed(0.001, 0.001)
        events = []
        for _ in range(6):
            events.append(g.feed(0.05, 0.12))
        for _ in range(8):
            events.append(g.feed(0.0005, 0.0005))
        self.assertIn("start", events)
        self.assertIn("end", events)

    def test_mid_sentence_gap_does_not_end(self) -> None:
        g = EnergyGate()
        for _ in range(20):
            g.feed(0.001, 0.001)
        self.assertEqual(g.feed(0.05, 0.12), "idle")
        while g.feed(0.05, 0.12) != "start":
            pass
        for _ in range(12):
            self.assertEqual(g.feed(0.05, 0.12), "speech")
        # ~240 ms dip — a comma, not the end of the thought.
        for _ in range(8):
            self.assertEqual(g.feed(0.0004, 0.0004), "speech")
        self.assertEqual(g.feed(0.05, 0.12), "speech")


class WakeTests(unittest.TestCase):
    def test_strips_leading_name(self) -> None:
        self.assertEqual(after_wake("Jarvis, lights off"), "lights off")
        self.assertEqual(after_wake("hey jarvis what time is it"), "what time is it")
        self.assertEqual(after_wake("Okay Jarvis."), "")
        self.assertEqual(after_wake("Jarvus lights off"), "lights off")
        self.assertIsNone(after_wake("turn the lights off"))
        self.assertIsNone(after_wake("tell jack dinner is ready"))


if __name__ == "__main__":
    unittest.main()
