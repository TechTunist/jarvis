"""Millimetre timber bench: parse, HTTP, not Imagine."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bench.bench import Handler, add_board, delete_part, find_part, set_upright
from memory.bench import apply, parse_board, wants_delete, wants_orient
from memory.home import JarvisHome

ROOT = Path(__file__).resolve().parent.parent


class ParseBoardTests(unittest.TestCase):
    def test_axes_are_labelled(self) -> None:
        js = (ROOT / "bench" / "bench.js").read_text(encoding="utf-8")
        html = (ROOT / "bench" / "index.html").read_text(encoding="utf-8")
        self.assertIn('axisLabel("X"', js)
        self.assertIn('axisLabel("Y"', js)
        self.assertIn('axisLabel("Z"', js)
        self.assertIn("Z up", html)

    def test_x_and_by(self) -> None:
        self.assertEqual(parse_board("1600x70x15mm"), (1600.0, 70.0, 15.0))
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


if __name__ == "__main__":
    unittest.main()
