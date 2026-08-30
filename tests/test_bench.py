"""Millimetre timber bench: parse, HTTP, not Imagine."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bench.bench import Handler, add_board, delete_part, find_part, set_upright
from bench.design import aabb, is_design_request, layout, parse_brief
from memory.bench import (
    apply,
    parse_board,
    parse_length,
    parse_ops,
    parse_project_ops,
    wants_close,
    wants_delete,
    wants_open,
    wants_orient,
)
from memory.home import JarvisHome

PERGOLA = (
    "Here is the thing, I have some pine i recovered from a pallet that is about "
    "as good condition as possible from a pallet. the pieces are in millimeteres: "
    "10 lengths of 1600x70x15, 3 lengths of 1300x90x20, 3 lengths of 1600x90x20. "
    "Outside my back door there is a garden wall that is 2m high, and the main house "
    "2 storey extension on the other side about 1560mm away, creating a kind of short "
    "alley leading into the garden. I want to create a kind of pergola outside the "
    "back door that is about 1 metre long (along the length of the alley). Please "
    "create the structure in Bench that uses the available timbers. you don't have "
    "to use all of them, but we need to have 2m headroom in the middle of the alley "
    "\x1b[D\x1b[D\x1b[D\x1b[D\x1bminimum"
)

ROOT = Path(__file__).resolve().parent.parent


class ParseBoardTests(unittest.TestCase):
    def test_axes_are_labelled(self) -> None:
        js = (ROOT / "bench" / "bench.js").read_text(encoding="utf-8")
        html = (ROOT / "bench" / "index.html").read_text(encoding="utf-8")
        self.assertIn('axisLabel("X"', js)
        self.assertIn('axisLabel("Y"', js)
        self.assertIn('axisLabel("Z"', js)
        self.assertIn("Z up", html)
        self.assertIn('id="world"', html)
        self.assertIn("Grid square", html)
        self.assertIn("GRID_CELL_MM", js)
        self.assertIn('id="inspect"', html)
        self.assertIn('id="inspect-name"', html)
        self.assertIn('id="inspect-name-input"', html)
        self.assertIn("commitNameEdit", js)
        self.assertIn("worldPerPix * 90", js)
        self.assertIn('id="inspect-dim"', html)
        self.assertIn("Raycaster", js)
        self.assertIn("partLine", js)
        self.assertIn("WOOD_HOVER", js)
        self.assertIn("pickAt", js)
        self.assertIn("panView", js)
        self.assertIn("wantsPan", js)
        self.assertIn('id="look-at"', html)
        self.assertIn("Shift-drag pan", html)
        self.assertNotIn("target.x = maxL / 2", js)
        self.assertIn("dblclick", js)
        self.assertIn("addFaceHandles", js)
        self.assertIn("applyFaceDrag", js)
        self.assertIn("inspect-hint", html)
        self.assertIn("push/pull", html)
        self.assertIn("inspect-loc", html)
        self.assertIn("inspect-rot", html)
        self.assertIn("function undo", js)
        self.assertIn("function redo", js)
        self.assertIn("rotateMode", js)
        self.assertIn("showProtractor", js)
        self.assertIn("pickGizmoAt", js)
        self.assertIn("SNAP_DEG", js)
        self.assertIn("CylinderGeometry", js)
        self.assertIn("depthTest: false", js)
        self.assertIn("clearDepth", js)
        self.assertIn("const overlay", js)
        self.assertIn("autoClear = false", js)
        self.assertIn("screenAlongAxis", js)
        self.assertIn("dragDeltaWorld", js)
        self.assertIn("[1, -1]", js)
        self.assertIn('id="actions"', html)
        self.assertIn('data-act="delete"', html)
        self.assertIn('data-act="cut"', html)
        self.assertIn('data-act="copy"', html)
        self.assertIn('data-act="paste"', html)
        self.assertIn("function deleteSelected", js)
        self.assertIn("function cutSelected", js)
        self.assertIn("function copySelected", js)
        self.assertIn("function pasteClipboard", js)
        self.assertIn("selectedIds", js)
        self.assertIn("function selectedIndices", js)
        self.assertIn("function toggleSelect", js)
        self.assertIn("Shift-click", html)
        self.assertIn("beginMoveDrag", js)
        self.assertIn('id="project-name"', html)
        self.assertIn('id="act-save"', html)
        self.assertIn('id="act-new"', html)
        self.assertIn('id="act-load"', html)
        self.assertIn("Saved — click to load", html)
        self.assertIn("function saveProject", js)
        self.assertIn("function loadProject", js)
        self.assertIn('op: "save"', js)
        self.assertIn('op: "new"', js)
        self.assertIn('op: "load"', js)
        self.assertIn("function partColor", js)
        self.assertIn("FINISH", js)
        self.assertIn("function rebuildWires", js)
        self.assertIn('id="wires-block"', html)

    def test_x_and_by(self) -> None:
        self.assertEqual(parse_board("1600x70x15mm"), (1600.0, 70.0, 15.0))
        self.assertEqual(parse_board("1600x70x15"), (1600.0, 70.0, 15.0))
        self.assertEqual(
            parse_board("a bit of wood 1600 x 70 x 15 mm"),
            (1600.0, 70.0, 15.0),
        )
        self.assertEqual(
            parse_board("1600mm by 70mm by 15mm"),
            (1600.0, 70.0, 15.0),
        )
        self.assertEqual(
            parse_board("1600 x 70 x 15 millimeters"),
            (1600.0, 70.0, 15.0),
        )
        self.assertIsNone(parse_board("draw me a cat"))
        self.assertTrue(wants_orient("lets stand it up so it is vertical"))
        self.assertTrue(wants_delete("delete board 2 and make board 1 vertical"))
        self.assertFalse(wants_delete("Never do that again"))
        self.assertTrue(wants_open("can you open the bench please"))
        self.assertTrue(wants_open("lets work on bench"))
        self.assertTrue(wants_open("there is no browser tab open for the bench"))
        self.assertFalse(wants_open("duplicate board 1 offset 900mm"))
        self.assertFalse(wants_open("do we have an open project on bench"))
        self.assertTrue(wants_close("close the bench please"))
        self.assertTrue(wants_close("lets stop the bench right now. I want to do something else"))
        self.assertFalse(wants_close("open the bench"))
        self.assertEqual(
            parse_project_ops("save this as the pergola"),
            [{"op": "save", "as": "pergola"}],
        )
        self.assertEqual(
            parse_project_ops("save this so I can work on a new one"),
            [{"op": "save"}, {"op": "new"}],
        )
        self.assertEqual(
            parse_project_ops(
                "save this as the pergola so I can work on a new one"
            ),
            [{"op": "save", "as": "pergola"}, {"op": "new"}],
        )
        self.assertEqual(parse_project_ops("start a new project"), [{"op": "new"}])
        self.assertEqual(
            parse_project_ops(
                'lets work on a new project called "circuit example" on the bench'
            ),
            [{"op": "new", "as": "circuit example"}],
        )
        self.assertEqual(
            parse_project_ops("go back to the first one"),
            [{"op": "load", "name": "first"}],
        )
        self.assertEqual(
            parse_project_ops("go back to the pergola"),
            [{"op": "load", "name": "pergola"}],
        )
        self.assertEqual(parse_project_ops("list projects"), [{"op": "list_projects"}])
        self.assertEqual(parse_project_ops("open the bench"), [])
        self.assertEqual(parse_ops("open the bench", {"parts": []}), [])
        self.assertEqual(
            parse_ops("save this as the pergola", {"parts": []})[0]["op"],
            "save",
        )

    def test_script_starts_when_talk_sets_pythonpath(self) -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = os.environ.copy()
        extra = str(ROOT)
        env["PYTHONPATH"] = extra + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "bench" / "bench.py"),
                "--data-dir",
                tmp.name,
                "--port",
                str(port),
            ],
            cwd=str(ROOT / "receptionist"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        def _stop() -> None:
            try:
                os.killpg(proc.pid, 15)
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, 9)
                except OSError:
                    pass
            if proc.stderr:
                proc.stderr.close()

        self.addCleanup(_stop)
        health = f"http://127.0.0.1:{port}/api/health"
        data = None
        for _ in range(60):
            time.sleep(0.05)
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                self.fail(f"bench.py exited {proc.returncode}: {err}")
            try:
                with urllib.request.urlopen(health, timeout=0.3) as resp:
                    data = json.loads(resp.read().decode())
                break
            except (OSError, TimeoutError, json.JSONDecodeError):
                continue
        self.assertTrue(data, "bench.py did not serve /api/health")
        self.assertTrue(data.get("ok"))
        self.assertGreaterEqual(int(data.get("api") or 0), 4)


class BenchHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        Handler.data_dir = self.home.root
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/"

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path) as resp:
            return json.loads(resp.read().decode())

    def test_add_stand_delete(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        scene = self._get("api/scene")
        self.assertEqual(len(scene["parts"]), 2)
        self.assertFalse(scene["parts"][0].get("upright"))
        self._post("api/delete", {"n": 2})
        self._post("api/orient", {"n": 1, "upright": True})
        scene = self._get("api/scene")
        self.assertEqual(len(scene["parts"]), 1)
        self.assertTrue(scene["parts"][0]["upright"])
        self.assertEqual(scene["parts"][0]["name"], "board 1")

    def test_camera_pan_look_at_and_frame(self) -> None:
        self._post(
            "api/parts",
            {
                "kind": "board",
                "length_mm": 1600,
                "width_mm": 70,
                "thickness_mm": 15,
                "upright": True,
            },
        )
        framed = self._post("api/ops", {"ops": [{"op": "frame"}]})
        cam = framed["scene"]["camera"]
        self.assertIn("look_x_mm", cam)
        self.assertIn("look_y_mm", cam)
        self.assertIn("look_z_mm", cam)
        self.assertGreater(cam["dist_mm"], 200)
        before = cam["look_x_mm"]
        panned = self._post("api/ops", {"ops": [{"op": "pan", "dx_mm": 250}]})
        self.assertAlmostEqual(panned["scene"]["camera"]["look_x_mm"], before + 250, delta=0.5)
        looked = self._post("api/ops", {"ops": [{"op": "look_at", "n": 1}]})
        self.assertIn("looking at", " ".join(looked.get("notes") or []).lower())
        direct = self._post(
            "api/camera",
            {"look_x_mm": 400, "look_y_mm": 100, "look_z_mm": 50, "dist_mm": 1800},
        )
        self.assertAlmostEqual(direct["camera"]["look_x_mm"], 400)
        self.assertAlmostEqual(direct["camera"]["look_y_mm"], 100)
        self.assertAlmostEqual(direct["camera"]["look_z_mm"], 50)
        health = self._get("api/health")
        self.assertGreaterEqual(int(health.get("api") or 0), 5)

    def test_rename_part(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        scene = self._get("api/scene")
        pid = scene["parts"][0]["id"]
        renamed = self._post(
            "api/ops", {"ops": [{"op": "rename", "id": pid, "to": "rafter A"}]}
        )
        self.assertIn("named rafter a", " ".join(renamed.get("notes") or []).lower())
        self.assertEqual(self._get("api/scene")["parts"][0]["name"], "rafter A")
        direct = self._post("api/rename", {"id": pid, "to": "ledger"})
        self.assertEqual(direct["scene"]["parts"][0]["name"], "ledger")

    def test_add_pastes_named_copy_offset(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        src = self._get("api/scene")["parts"][0]
        self._post(
            "api/ops",
            {
                "ops": [
                    {
                        "op": "add",
                        "length_mm": src["length_mm"],
                        "width_mm": src["width_mm"],
                        "thickness_mm": src["thickness_mm"],
                        "name": src["name"],
                        "upright": src.get("upright"),
                        "x_mm": src["x_mm"],
                        "y_mm": src["y_mm"] + 100,
                        "z_mm": src["z_mm"],
                    }
                ]
            },
        )
        parts = self._get("api/scene")["parts"]
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[1]["name"], src["name"])
        self.assertAlmostEqual(parts[1]["y_mm"], src["y_mm"] + 100)

    def test_set_parts_restores_a_snapshot(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        scene = self._get("api/scene")
        snapshot = list(scene["parts"])
        self._post("api/ops", {"ops": [{"op": "resize", "n": 1, "length_mm": 800}]})
        self.assertEqual(self._get("api/scene")["parts"][0]["length_mm"], 800)
        self._post("api/ops", {"ops": [{"op": "set_parts", "parts": snapshot}]})
        self.assertEqual(self._get("api/scene")["parts"][0]["length_mm"], 1600)

    def test_save_new_and_load_project(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        saved = self._post("api/ops", {"ops": [{"op": "save", "as": "pergola"}]})
        self.assertIn("pergola", " ".join(saved.get("notes") or []).lower())
        scene = self._get("api/scene")
        self.assertEqual(scene["project"]["name"], "pergola")
        self.assertEqual(len(scene["parts"]), 1)
        self.assertGreaterEqual(int(self._get("api/health").get("api") or 0), 7)
        listed = self._get("api/projects")
        self.assertEqual(listed["current"], "pergola")
        self.assertTrue(any(p.get("id") == "pergola" for p in listed["projects"]))
        emptied = self._post("api/ops", {"ops": [{"op": "new"}]})
        self.assertIn("on file", " ".join(emptied.get("notes") or []).lower())
        empty = self._get("api/scene")
        self.assertEqual(empty.get("parts") or [], [])
        self.assertEqual((empty.get("project") or {}).get("id") or "", "")
        loaded = self._post("api/ops", {"ops": [{"op": "load", "name": "first"}]})
        self.assertIn("pergola", " ".join(loaded.get("notes") or []).lower())
        back = self._get("api/scene")
        self.assertEqual(len(back["parts"]), 1)
        self.assertEqual(back["parts"][0]["length_mm"], 1600)
        self.assertEqual(back["project"]["name"], "pergola")

    def test_new_auto_saves_untitled_work(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 800, "width_mm": 70, "thickness_mm": 15},
        )
        self._post("api/ops", {"ops": [{"op": "new"}]})
        self.assertEqual(self._get("api/scene").get("parts") or [], [])
        idx = self._get("api/projects")
        self.assertTrue(idx["projects"])
        self._post("api/ops", {"ops": [{"op": "load", "name": "previous"}]})
        parts = self._get("api/scene")["parts"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["length_mm"], 800)

    def test_load_missing_project_is_an_error(self) -> None:
        req = urllib.request.Request(
            self.base + "api/ops",
            data=json.dumps({"ops": [{"op": "load", "name": "nope"}]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 400)

    def test_apply_save_as_pergola_does_not_redesign(self) -> None:
        import memory.bench as mb

        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(
                self.home, "save this as the pergola so I can work on a new one"
            )
        self.assertEqual(result, "ok")
        self.assertIn("pergola", speak.lower())
        self.assertEqual(self._get("api/scene").get("parts") or [], [])
        idx = self._get("api/projects")
        self.assertEqual(idx["previous"], "pergola")
        self._post("api/ops", {"ops": [{"op": "load", "name": "pergola"}]})
        self.assertEqual(len(self._get("api/scene")["parts"]), 1)

    def test_wire_kit_connects_room_node_roles(self) -> None:
        for spec in (
            {"length_mm": 48, "width_mm": 25, "thickness_mm": 12, "role": "mcu", "name": "ESP32-S3-DevKitC-1"},
            {"length_mm": 65, "width_mm": 18, "thickness_mm": 18, "role": "cell", "name": "18650"},
            {"length_mm": 26, "width_mm": 17, "thickness_mm": 4, "role": "bms", "name": "TP4056"},
            {"length_mm": 5, "width_mm": 4, "thickness_mm": 1, "role": "mic", "name": "INMP441"},
            {"length_mm": 12, "width_mm": 6, "thickness_mm": 8, "role": "mute", "name": "mute"},
            {"length_mm": 5, "width_mm": 5, "thickness_mm": 8, "role": "led", "name": "LED"},
            {"length_mm": 14, "width_mm": 9, "thickness_mm": 7, "role": "usb", "name": "USB-C"},
            {"length_mm": 50, "width_mm": 30, "thickness_mm": 22, "role": "psu", "name": "PSU"},
        ):
            self._post("api/ops", {"ops": [{"op": "add", **spec}]})
        out = self._post("api/ops", {"ops": [{"op": "wire_kit"}]})
        self.assertIn("wired", " ".join(out.get("notes") or []).lower())
        scene = self._get("api/scene")
        nets = {str(w.get("net")) for w in scene.get("wires") or []}
        self.assertIn("I2S_SCK", nets)
        self.assertIn("VBAT", nets)
        self.assertGreaterEqual(len(scene["wires"]), 8)
        import memory.bench as mb
        from memory.bench import parse_ops

        ops = parse_ops("show how the components are wired together", scene)
        self.assertEqual(ops[0]["op"], "wire_kit")
        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(self.home, "wire the room node on the bench")
        self.assertEqual(result, "ok")
        self.assertIn("wired", speak.lower())

    def test_apply_stand_does_not_add_a_second_board(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=True),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(
                self.home, "stand the 1600 x 70 x 15 mm plate vertical on port 8770"
            )
        self.assertEqual(result, "ok")
        self.assertTrue("vertical" in speak.lower() or "standing" in speak.lower())
        scene = self._get("api/scene")
        self.assertEqual(len(scene["parts"]), 1)
        self.assertTrue(scene["parts"][0]["upright"])

    def test_apply_delete_two_and_stand_one(self) -> None:
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=True),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(
                self.home,
                "delete board 2 and make board 1 vertical",
            )
        self.assertEqual(result, "ok")
        scene = self._get("api/scene")
        self.assertEqual(len(scene["parts"]), 1)
        self.assertTrue(scene["parts"][0]["upright"])
        self.assertIn("removed", speak.lower())

    def test_find_part_helpers(self) -> None:
        scene = {"parts": []}
        add_board(scene, 100, 20, 10, "board 1")
        add_board(scene, 100, 20, 10, "board 2")
        p2 = find_part(scene, n=2)
        assert p2 is not None
        self.assertEqual(p2["name"], "board 2")
        set_upright(p2, True)
        self.assertTrue(p2["upright"])
        delete_part(scene, p2)
        self.assertEqual(len(scene["parts"]), 1)

    def test_duplicate_offset_and_length_on_top(self) -> None:
        import memory.bench as mb
        from memory.bench import parse_ops

        self._post(
            "api/parts",
            {
                "kind": "board",
                "length_mm": 1600,
                "width_mm": 70,
                "thickness_mm": 15,
                "upright": True,
            },
        )
        scene = self._get("api/scene")
        ops = parse_ops("duplicate board 1 offset 900mm centres from the first board", scene)
        self.assertEqual(ops[0]["op"], "duplicate")
        self.assertEqual(ops[0]["dy_mm"], 900.0)
        ops = parse_ops(
            "add a second board 1300mm long, horizontal, starting at the top of board 1",
            scene,
        )
        self.assertEqual(ops[0]["op"], "add")
        self.assertEqual(ops[0]["length_mm"], 1300.0)
        self.assertEqual(ops[0]["z_mm"], 1600.0)
        self.assertFalse(ops[0]["upright"])
        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui") as opened,
        ):
            speak, result = apply(
                self.home, "add board 2, same dimensions as board 1, offset 900mm"
            )
        self.assertEqual(result, "ok")
        opened.assert_not_called()
        scene = self._get("api/scene")
        self.assertEqual(len(scene["parts"]), 2)
        self.assertEqual(scene["parts"][1]["y_mm"], 900.0)
        self.assertIn("duplicated", speak.lower())

    def test_open_bench_opens_a_tab_without_reading_the_roster(self) -> None:
        import memory.bench as mb

        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui") as opened,
        ):
            speak, result = apply(self.home, "can you open the bench please")
        self.assertEqual(result, "ok")
        opened.assert_called()
        self.assertIn("open", speak.lower())
        self.assertNotIn("board 1", speak.lower())

    def test_missing_tab_opens_ui(self) -> None:
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui") as opened,
        ):
            speak, result = apply(
                self.home, "there is no browser tab open for the bench"
            )
        self.assertEqual(result, "ok")
        opened.assert_called()
        self.assertIn("open", speak.lower())

    def test_close_bench_does_not_read_the_roster(self) -> None:
        import memory.bench as mb

        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server") as started,
            patch.object(mb, "close_server", return_value=True) as closed,
            patch.object(mb, "open_ui") as opened,
        ):
            speak, result = apply(self.home, "close the bench please")
        self.assertEqual(result, "closed")
        self.assertIn("closed", speak.lower())
        self.assertNotIn("board", speak.lower())
        closed.assert_called()
        started.assert_not_called()
        opened.assert_not_called()

    def test_hands_reason_when_he_asks_to_close(self) -> None:
        import memory.bench as mb

        self._post(
            "api/parts",
            {"kind": "board", "length_mm": 1600, "width_mm": 70, "thickness_mm": 15},
        )
        seen: dict = {}

        def complete(prompt: str, **kw) -> str:
            seen["prompt"] = prompt
            seen["kw"] = kw
            return json.dumps({"speak": "The bench is closed, sir.", "ok": True})

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server") as started,
            patch.object(mb, "close_server") as closed,
            patch.object(mb, "open_ui") as opened,
        ):
            speak, result = apply(
                self.home, "close the bench please", complete=complete
            )
        self.assertIn("closed", speak.lower())
        self.assertNotIn("board 1", speak.lower())
        started.assert_not_called()
        closed.assert_not_called()
        opened.assert_not_called()
        self.assertIn("Matt asked", seen.get("prompt") or "")
        self.assertIn("close the bench", (seen.get("prompt") or "").lower())
        kw = seen.get("kw") or {}
        self.assertNotEqual(kw.get("tools"), "")
        self.assertNotIn("run_terminal_cmd", str(kw.get("disallowed") or ""))
        self.assertEqual(kw.get("effort"), "high")
        self.assertTrue(kw.get("subagents"))
        self.assertGreaterEqual(int(kw.get("max_turns") or 0), 12)

    def test_stop_the_bench_closes(self) -> None:
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server") as started,
            patch.object(mb, "close_server", return_value=True),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(
                self.home, "lets stop the bench right now. I want to do something else"
            )
        self.assertEqual(result, "closed")
        self.assertIn("closed", speak.lower())
        started.assert_not_called()

    def test_pergola_brief_builds_inside_the_alley(self) -> None:
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(self.home, PERGOLA)
        self.assertEqual(result, "ok")
        scene = self._get("api/scene")
        parts = scene["parts"]
        self.assertGreaterEqual(len(parts), 8)
        check = scene["check"]
        self.assertTrue(check["span_ok"], check)
        self.assertTrue(check["length_ok"], check)
        self.assertTrue(check["headroom_ok"], check)
        self.assertGreaterEqual(check["mid_underside_mm"], 2000)
        self.assertLessEqual(check["span_mm"], 1560.5)
        self.assertLessEqual(check["length_mm"], 1000.5)
        for p in parts:
            xmin, ymin, zmin, xmax, ymax, zmax = aabb(p)
            self.assertGreaterEqual(xmin, -0.5)
            self.assertGreaterEqual(ymin, -0.5)
            self.assertLessEqual(xmax, 1000.5)
            self.assertLessEqual(ymax, 1560.5)
        posts = [p for p in parts if str(p.get("name") or "").startswith("post ")]
        self.assertEqual(len(posts), 3)
        self.assertIn("midpoint", speak.lower())
        left = scene.get("stock") or []
        self.assertTrue(any(int(s.get("qty") or 0) > 0 for s in left))

    def test_second_turn_rebuilds_from_the_pile(self) -> None:
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(self.home, PERGOLA)
            self.assertEqual(result, "ok")
            speak, result = apply(
                self.home,
                "just design and create the entire structure please. "
                "lets have 3 upright boards at 333mm centres",
            )
        self.assertEqual(result, "ok")
        scene = self._get("api/scene")
        posts = [p for p in scene["parts"] if str(p.get("name") or "").startswith("post ")]
        xs = sorted(float(p["x_mm"]) for p in posts)
        self.assertEqual(len(xs), 3)
        self.assertAlmostEqual(xs[1] - xs[0], 333.0, delta=1)
        self.assertTrue(scene["check"]["headroom_ok"])
        self.assertTrue(scene["check"]["span_ok"])
        self.assertTrue(scene["check"]["length_ok"])
        self.assertIn("splice", speak.lower())

    def test_inventory_only_does_not_place_boards(self) -> None:
        import memory.bench as mb

        with (
            patch.object(mb, "URL", self.base),
            patch.object(mb, "ensure_server", return_value=False),
            patch.object(mb, "open_ui"),
        ):
            speak, result = apply(
                self.home,
                "I have 10 lengths of 1600x70x15 and 3 lengths of 1300x90x20 recovered pine",
            )
        self.assertEqual(result, "stock")
        scene = self._get("api/scene")
        self.assertEqual(scene.get("parts") or [], [])
        qty = sum(int(s.get("qty") or 0) for s in scene.get("stock") or [])
        self.assertEqual(qty, 13)
        self.assertIn("stock on file", speak.lower())


class DesignParseTests(unittest.TestCase):
    def test_session_brief_is_stock_and_site_not_a_ten_mm_board(self) -> None:
        self.assertTrue(is_design_request(PERGOLA))
        self.assertEqual(parse_ops(PERGOLA, {"parts": []}), [])
        self.assertIsNone(parse_length(PERGOLA))
        brief = parse_brief(PERGOLA)
        self.assertEqual(
            {(s.qty, s.length_mm, s.width_mm, s.thickness_mm) for s in brief.stock},
            {
                (10, 1600.0, 70.0, 15.0),
                (3, 1300.0, 90.0, 20.0),
                (3, 1600.0, 90.0, 20.0),
            },
        )
        self.assertEqual(brief.site.width_mm, 1560.0)
        self.assertEqual(brief.site.length_mm, 1000.0)
        self.assertEqual(brief.site.min_headroom_mm, 2000.0)
        self.assertEqual(brief.site.wall_height_mm, 2000.0)
        self.assertTrue(brief.wants_design)

    def test_upright_centres_hint(self) -> None:
        brief = parse_brief(
            "just design and create the entire structure please. "
            "lets have 3 upright boards at 333mm centres, then reason about "
            "how to create the rafter structure, keeping the requisite height",
            {
                "stock": [
                    {
                        "length_mm": 1600,
                        "width_mm": 70,
                        "thickness_mm": 15,
                        "qty": 10,
                    }
                ],
                "site": {
                    "width_mm": 1560,
                    "length_mm": 1000,
                    "min_headroom_mm": 2000,
                    "wall_height_mm": 2000,
                },
            },
        )
        self.assertTrue(brief.wants_design)
        self.assertEqual(brief.hints.uprights, 3)
        self.assertEqual(brief.hints.centres_mm, 333.0)

    def test_layout_meets_headroom_and_alley(self) -> None:
        brief = parse_brief(PERGOLA + " lets have 3 upright boards at 333mm centres")
        parts, remaining, check, notes = layout(brief)
        self.assertTrue(check.span_ok, check)
        self.assertTrue(check.length_ok, check)
        self.assertTrue(check.headroom_ok, check)
        self.assertGreaterEqual(check.mid_underside_mm, 2000)
        self.assertLessEqual(check.span_mm, 1560.5)
        self.assertLessEqual(check.length_mm, 1000.5)
        self.assertGreaterEqual(len(parts), 8)
        used = sum(s.qty for s in brief.stock) - sum(s.qty for s in remaining if s.qty > 0)
        self.assertGreater(used, 0)
        self.assertGreater(sum(s.qty for s in remaining if s.qty > 0), 0)
        posts = [p for p in parts if str(p.get("name") or "").startswith("post ")]
        xs = sorted(float(p["x_mm"]) for p in posts)
        self.assertEqual(len(xs), 3)
        self.assertAlmostEqual(xs[1] - xs[0], 333.0, delta=1)
        self.assertAlmostEqual(xs[2] - xs[1], 333.0, delta=1)

    def test_aabb_flat_and_upright_and_rafter(self) -> None:
        flat = {
            "length_mm": 100,
            "width_mm": 20,
            "thickness_mm": 10,
            "x_mm": 0,
            "y_mm": 0,
            "z_mm": 0,
            "rx_deg": 0,
            "ry_deg": 0,
            "rz_deg": 0,
            "upright": False,
        }
        xmin, ymin, zmin, xmax, ymax, zmax = aabb(flat)
        self.assertAlmostEqual(xmin, 0)
        self.assertAlmostEqual(xmax, 100)
        self.assertAlmostEqual(ymin, 0)
        self.assertAlmostEqual(ymax, 20)
        self.assertAlmostEqual(zmin, 0)
        self.assertAlmostEqual(zmax, 10)
        up = dict(flat, upright=True)
        xmin, ymin, zmin, xmax, ymax, zmax = aabb(up)
        self.assertAlmostEqual(xmax, 10)
        self.assertAlmostEqual(ymax, 20)
        self.assertAlmostEqual(zmax, 100)
        rafter = dict(flat, ry_deg=-90, x_mm=20)
        xmin, ymin, zmin, xmax, ymax, zmax = aabb(rafter)
        self.assertAlmostEqual(xmin, 0, delta=0.01)
        self.assertAlmostEqual(xmax, 20, delta=0.01)
        self.assertAlmostEqual(ymin, 0, delta=0.01)
        self.assertAlmostEqual(ymax, 100, delta=0.01)
        self.assertAlmostEqual(zmax, 10, delta=0.01)

    def test_panel_has_stock_and_alley(self) -> None:
        html = (ROOT / "bench" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "bench" / "bench.js").read_text(encoding="utf-8")
        self.assertIn('id="stock-block"', html)
        self.assertIn('id="alley-span"', html)
        self.assertIn("rebuildSite", js)


if __name__ == "__main__":
    unittest.main()
