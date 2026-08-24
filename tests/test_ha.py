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
    roster_markdown,
    roster_path,
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
    _ent("switch.kitchen_do_not_disturb", "Kitchen Do not disturb", "off"),
    _ent("light.lounge", "Lounge", "on"),
    _ent(
        "light.living_room_living_room_main_light",
        "Living Room Main Light",
        "off",
        supported_color_modes=["color_temp", "hs"],
        area="Living Room",
    ),
    _ent(
        "light.lamp",
        "Lamp",
        "off",
        supported_color_modes=["color_temp", "hs"],
        area="Living Room",
    ),
    _ent(
        "light.garden_light",
        "Garden Light",
        "off",
        supported_color_modes=["onoff"],
        area="Back Door",
    ),
    _ent("light.jaks_light", "Jak\u2019s Light", "off", area="Jak's Room"),
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
        pct = data.get("brightness_pct")
        if new:
            for ent in self.states:
                if ent["entity_id"] in ids:
                    ent["state"] = new
                    if service == "turn_on" and pct is not None:
                        attrs = dict(ent.get("attributes") or {})
                        attrs["brightness"] = int(int(pct) * 255 / 100)
                        attrs["brightness_pct"] = int(pct)
                        ent["attributes"] = attrs
                    if service == "turn_off":
                        attrs = dict(ent.get("attributes") or {})
                        attrs["brightness"] = None
                        ent["attributes"] = attrs
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

    def test_too_bright_living_room(self) -> None:
        cmd = parse_command("it is too bright in the living room jarvis")
        self.assertIsNotNone(cmd)
        assert cmd is not None
        self.assertEqual(cmd.action, "dim")
        self.assertEqual(cmd.domain, "light")
        self.assertEqual(cmd.area, "living")
        self.assertEqual(cmd.brightness, 30)

    def test_too_dark_and_percent(self) -> None:
        cmd = parse_command("it's too dark in the kitchen")
        self.assertEqual(cmd.action, "brighten")
        self.assertEqual(cmd.area, "kitchen")
        cmd = parse_command("set the living room to 20 percent")
        self.assertEqual(cmd.action, "dim")
        self.assertEqual(cmd.brightness, 20)
        self.assertEqual(cmd.area, "living")
        for said in (
            "it is a little dark in the living room",
            "it is still dark in the living room jarvis",
        ):
            with self.subTest(said=said):
                cmd = parse_command(said)
                self.assertIsNotNone(cmd)
                assert cmd is not None
                self.assertEqual(cmd.action, "brighten")
                self.assertEqual(cmd.domain, "light")
                self.assertEqual(cmd.area, "living")

    def test_what_lights(self) -> None:
        cmd = parse_command("what lights are on")
        self.assertEqual(cmd.action, "query")
        self.assertTrue(cmd.all_of)

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
        self.assertNotIn("switch.kitchen_do_not_disturb", ids)

    def test_living_room_includes_lamp_via_area(self) -> None:
        cmd = parse_command("turn on the living room lights")
        ents = resolve_entities(STATES, cmd)
        ids = {e["entity_id"] for e in ents}
        self.assertIn("light.living_room_living_room_main_light", ids)
        self.assertIn("light.lamp", ids)
        self.assertNotIn("light.lounge", ids)
        self.assertNotIn("light.kitchen", ids)

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

    def test_too_bright_without_room_asks(self) -> None:
        speak, result = run_home(
            self.home, {"prompt": "it's too bright"}, transport=self.ha
        )
        self.assertEqual(result, "ambiguous")
        self.assertIn("Which lights", speak)
        self.assertEqual(self.ha.calls, [])

    def test_too_bright_dims_living_room(self) -> None:
        for eid in (
            "light.living_room_living_room_main_light",
            "light.lamp",
        ):
            for ent in self.ha.states:
                if ent["entity_id"] == eid:
                    ent["state"] = "on"
                    attrs = dict(ent.get("attributes") or {})
                    attrs["brightness"] = 255
                    ent["attributes"] = attrs
        speak, result = run_home(
            self.home,
            {"prompt": "it is too bright in the living room jarvis"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertIn("dimmed", speak.lower())
        self.assertTrue(self.ha.calls)
        domain, service, data = self.ha.calls[0]
        self.assertEqual(domain, "light")
        self.assertEqual(service, "turn_on")
        self.assertEqual(data.get("brightness_pct"), 30)
        ids = data["entity_id"]
        if isinstance(ids, str):
            ids = [ids]
        self.assertIn("light.living_room_living_room_main_light", ids)
        self.assertIn("light.lamp", ids)
        self.assertIn("Living Room Main Light", roster_path(self.home).read_text(encoding="utf-8"))

    def test_too_bright_turns_off_onoff_garden(self) -> None:
        for ent in self.ha.states:
            if ent["entity_id"] == "light.garden_light":
                ent["state"] = "on"
        speak, result = run_home(
            self.home,
            {"prompt": "too bright in the garden"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][1], "turn_off")
        self.assertIn("Garden", speak)

    def test_too_bright_already_dim_turns_off(self) -> None:
        for ent in self.ha.states:
            if ent["entity_id"] == "light.living_room_living_room_main_light":
                ent["state"] = "on"
                attrs = dict(ent.get("attributes") or {})
                attrs["brightness"] = 50
                ent["attributes"] = attrs
        speak, result = run_home(
            self.home,
            {"prompt": "it's too bright in the living room"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][1], "turn_off")
        self.assertIn("off", speak.lower())

    def test_too_dark_turns_living_room_on(self) -> None:
        speak, result = run_home(
            self.home,
            {"prompt": "it's too dark in the living room"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][1], "turn_on")
        self.assertEqual(self.ha.calls[0][2].get("brightness_pct"), 80)

    def test_a_little_dark_turns_living_room_on(self) -> None:
        speak, result = run_home(
            self.home,
            {"prompt": "it is a little dark in the living room"},
            transport=self.ha,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][1], "turn_on")
        ids = self.ha.calls[0][2]["entity_id"]
        if isinstance(ids, str):
            ids = [ids]
        self.assertIn("light.living_room_living_room_main_light", ids)
        self.assertIn("light.lamp", ids)

    def test_kitchen_lights_skip_dnd_switch(self) -> None:
        run_home(
            self.home,
            {"prompt": "turn on the kitchen lights"},
            transport=self.ha,
        )
        ids = []
        for _d, _s, data in self.ha.calls:
            eid = data.get("entity_id")
            ids.extend(eid if isinstance(eid, list) else [eid])
        self.assertIn("light.kitchen", ids)
        self.assertNotIn("switch.kitchen_do_not_disturb", ids)

    def test_what_lights_lists_them(self) -> None:
        speak, result = run_home(
            self.home, {"prompt": "what lights do we have"}, transport=self.ha
        )
        self.assertEqual(result, "query")
        self.assertIn("Lamp", speak)
        self.assertIn("Kitchen", speak)

    def test_confident_kitchen_skips_mapper(self) -> None:
        called: list[int] = []

        def mapper(prompt: str, roster: list[dict]):
            called.append(1)
            return None

        speak, result = run_home(
            self.home,
            {"prompt": "turn on the kitchen lights"},
            transport=self.ha,
            mapper=mapper,
        )
        self.assertEqual(result, "done")
        self.assertEqual(called, [])
        self.assertTrue(self.ha.calls)

    def test_unconfident_query_uses_mapper(self) -> None:
        def mapper(prompt: str, roster: list[dict]) -> HouseCommand:
            self.assertIn("gloomy", prompt)
            return HouseCommand(
                action="on",
                domain="light",
                area="living",
                entity_ids=(
                    "light.living_room_living_room_main_light",
                    "light.lamp",
                ),
            )

        speak, result = run_home(
            self.home,
            {"prompt": "it is gloomy in the living room"},
            transport=self.ha,
            mapper=mapper,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][1], "turn_on")

    def test_mapper_when_local_misses(self) -> None:
        def mapper(prompt: str, roster: list[dict]) -> HouseCommand:
            self.assertTrue(roster)
            self.assertIn("sofa", prompt)
            return HouseCommand(
                action="off",
                domain="light",
                area=None,
                entity_ids=("light.lamp",),
            )

        speak, result = run_home(
            self.home,
            {"prompt": "kill the glow by the sofa"},
            transport=self.ha,
            mapper=mapper,
        )
        self.assertEqual(result, "done")
        self.assertEqual(self.ha.calls[0][2]["entity_id"], "light.lamp")
        self.assertIn("Lamp", speak)

    def test_roster_markdown_skips_junk(self) -> None:
        text = roster_markdown(STATES)
        self.assertIn("Living Room Main Light", text)
        self.assertIn("Lamp", text)
        self.assertNotIn("Do not disturb", text)
        self.assertIn("Living Room", text)


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
        self.assertEqual(
            classify("it is too bright in the living room jarvis").cap, HOME.cap
        )
        self.assertEqual(classify("dim the living room").cap, HOME.cap)
        self.assertEqual(classify("what lights are on").cap, HOME.cap)
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
