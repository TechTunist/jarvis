"""Home Assistant: local parse + fake transport. No live Pi, no token."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.ha import (
    HouseCommand,
    is_house_followup,
    is_no,
    is_yes,
    parse_command,
    pending_clarify,
    pending_confirm,
    resolve_entities,
    run_home,
)
from memory.home import JarvisHome
from memory.intent import HOME, classify, maybe_enqueue
from memory.jobs import JobBoard
from memory.workshops import WorkshopRegistry


def _ent(eid: str, name: str, state: str = "off", **attrs) -> dict:
    a = {"friendly_name": name}
    a.update(attrs)
    return {"entity_id": eid, "state": state, "attributes": a}


STATES = [
    _ent("light.kitchen", "Kitchen", "off"),
    _ent("light.kitchen_sink", "Kitchen sink", "off"),
    _ent("light.lounge", "Lounge", "on"),
    _ent("light.lamp", "Lamp", "off"),
    _ent("light.jaks_light", "Jak\u2019s Light", "off"),
    _ent("lock.front_door", "Front door", "locked"),
    _ent("cover.garage_door", "Garage door", "closed"),
    _ent("climate.hallway", "Hallway thermostat", "heat", current_temperature=19, temperature=20),
]


class FakeHA:
    def __init__(self, states: list[dict] | None = None):
        self.states = [dict(s) for s in (states or STATES)]
        self.calls: list[tuple[str, str, dict]] = []

    def get_states(self) -> list[dict]:
        return self.states

    def call_service(self, domain: str, service: str, data: dict):
        self.calls.append((domain, service, data))
        eid = data.get("entity_id")
        ids = eid if isinstance(eid, list) else [eid]
        new = "on" if service == "turn_on" else "off" if service == "turn_off" else None
        if service == "unlock":
            new = "unlocked"
        if service == "lock":
            new = "locked"
        if service == "open_cover":
            new = "open"
        if service == "close_cover":
            new = "closed"
        if new:
            for ent in self.states:
                if ent["entity_id"] in ids:
                    ent["state"] = new
        return []


class ParseTests(unittest.TestCase):
    def test_kitchen_lights(self) -> None:
        cmd = parse_command("turn on the kitchen lights")
        self.assertEqual(cmd.action, "on")
        self.assertEqual(cmd.domain, "light")
        self.assertEqual(cmd.area, "kitchen")
        cmd = parse_command("turn the kitchen lights off")
        self.assertEqual(cmd.action, "off")
        self.assertEqual(cmd.area, "kitchen")

    def test_query_not_actuate(self) -> None:
        cmd = parse_command("is the garage closed")
        self.assertEqual(cmd.action, "query")
        self.assertEqual(cmd.domain, "cover")
        cmd = parse_command("is the garage open")
        self.assertEqual(cmd.action, "query")

    def test_the_lamp_and_turned_on(self) -> None:
        cmd = parse_command("Let me turn on the lamp, please.")
        self.assertEqual(cmd.action, "on")
        self.assertEqual(cmd.hints, ("lamp",))
        cmd = parse_command("Job is turned on the lamp in home assistant.")
        self.assertEqual(cmd.action, "on")
        self.assertEqual(cmd.hints, ("lamp",))

    def test_unlock(self) -> None:
        cmd = parse_command("unlock the front door")
        self.assertEqual(cmd.action, "unlock")
        self.assertEqual(cmd.domain, "lock")
        self.assertEqual(cmd.area, "front")

    def test_yes_no(self) -> None:
        self.assertTrue(is_yes("yes"))
        self.assertTrue(is_yes("Yes, sir."))
        self.assertFalse(is_yes("yesterday"))
        self.assertTrue(is_no("no"))
        self.assertTrue(is_no("cancel"))


class ResolveTests(unittest.TestCase):
    def test_kitchen_group(self) -> None:
        cmd = HouseCommand(action="on", domain="light", area="kitchen")
        ents = resolve_entities(STATES, cmd)
        ids = {e["entity_id"] for e in ents}
        self.assertIn("light.kitchen", ids)
        self.assertIn("light.kitchen_sink", ids)
        self.assertNotIn("light.lounge", ids)

    def test_ambiguous_lights_without_room(self) -> None:
        cmd = HouseCommand(action="on", domain="light", area=None)
        self.assertEqual(resolve_entities(STATES, cmd), [])

    def test_the_lamp_picks_named_entity(self) -> None:
        cmd = parse_command("turn on the lamp")
        ents = resolve_entities(STATES, cmd)
        self.assertEqual([e["entity_id"] for e in ents], ["light.lamp"])

    def test_jacks_light_survives_stt_spelling(self) -> None:
        for said in (
            "turn on Jack's light",
            "turn on jacks light",
            "turn on Jak's light",
            "turn on the light in Jack's room",
        ):
            with self.subTest(said=said):
                cmd = parse_command(said)
                ents = resolve_entities(STATES, cmd)
                self.assertEqual(
                    [e["entity_id"] for e in ents],
                    ["light.jaks_light"],
                    said,
                )


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.ha = FakeHA()

    def test_token_missing_message(self) -> None:
        speak, result = run_home(
            self.home, {"prompt": "turn on the kitchen lights"}
        )
        self.assertEqual(result, "ha-error")
        self.assertIn("token", speak.lower())

    def test_lights_no_confirm(self) -> None:
        speak, result = run_home(
            self.home,
            {"prompt": "turn on the kitchen lights"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertIn("on", speak.lower())
        self.assertEqual(self.ha.calls[0][0], "light")
        self.assertEqual(self.ha.calls[0][1], "turn_on")

    def test_unlock_needs_yes(self) -> None:
        speak, result = run_home(
            self.home,
            {"prompt": "unlock the front door"},
            transport=self.ha,
        )
        self.assertEqual(result, "needs-confirm")
        self.assertIn("yes", speak.lower())
        self.assertEqual(self.ha.calls, [])
        self.assertIsNotNone(pending_confirm(self.home))
        speak, result = run_home(
            self.home, {"confirm": True}, transport=self.ha
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][1], "unlock")
        self.assertIsNone(pending_confirm(self.home))

    def test_unlock_cancel(self) -> None:
        run_home(self.home, {"prompt": "unlock the front door"}, transport=self.ha)
        speak, result = run_home(
            self.home, {"confirm": False}, transport=self.ha
        )
        self.assertEqual(result, "cancelled")
        self.assertEqual(self.ha.calls, [])

    def test_garage_query(self) -> None:
        speak, result = run_home(
            self.home, {"prompt": "is the garage closed"}, transport=self.ha
        )
        self.assertEqual(result, "query")
        self.assertIn("Garage", speak)
        self.assertEqual(self.ha.calls, [])

    def test_which_lights(self) -> None:
        speak, result = run_home(
            self.home, {"prompt": "turn on the lights"}, transport=self.ha
        )
        self.assertEqual(result, "ambiguous")
        self.assertEqual(self.ha.calls, [])
        self.assertIsNotNone(pending_clarify(self.home))
        speak, result = run_home(
            self.home, {"prompt": "kitchen"}, transport=self.ha
        )
        self.assertEqual(result, "done")
        self.assertTrue(self.ha.calls)

    def test_named_lamp(self) -> None:
        speak, result = run_home(
            self.home,
            {"prompt": "Let me turn on the lamp, please."},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        eid = self.ha.calls[0][2]["entity_id"]
        self.assertEqual(eid, "light.lamp")
        self.assertIn("Lamp", speak)

    def test_jacks_light_runs(self) -> None:
        speak, result = run_home(
            self.home,
            {"prompt": "turn on the light in Jack's room"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][2]["entity_id"], "light.jaks_light")
        self.assertRegex(speak, r"Jak")


class IntentHomeTests(unittest.TestCase):
    def test_gate_phrases(self) -> None:
        self.assertEqual(classify("turn the kitchen lights off").cap, HOME.cap)
        self.assertEqual(classify("Let me turn on the lamp, please.").cap, HOME.cap)
        self.assertEqual(classify("turn on the light in Jack's room").cap, HOME.cap)
        self.assertEqual(
            classify("Job is turned on the lamp in home assistant.").cap, HOME.cap
        )
        self.assertEqual(classify("is the garage closed").cap, HOME.cap)
        self.assertEqual(classify("unlock the front door").cap, HOME.cap)
        self.assertTrue(is_house_followup("kitchen"))

    def test_yes_enqueues_when_pending(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        board = JobBoard(home)
        reg = WorkshopRegistry(home)
        reg.advertise("host", ["home"])
        ha = FakeHA()
        run_home(home, {"prompt": "unlock the front door"}, transport=ha)
        hit = maybe_enqueue("yes", board, reg)
        self.assertIsNotNone(hit)
        assert hit is not None
        _, jid = hit
        self.assertTrue(board.snapshot(jid).get("confirm") is True)

    def test_yes_without_pending_is_chat(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        board = JobBoard(home)
        reg = WorkshopRegistry(home)
        reg.advertise("host", ["home"])
        self.assertIsNone(maybe_enqueue("yes", board, reg))


if __name__ == "__main__":
    unittest.main()
