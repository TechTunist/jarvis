"""Millimetre timber bench: parse, HTTP, not Imagine."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from memory.bench import parse_board
from memory.home import JarvisHome


class ParseBoardTests(unittest.TestCase):
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
        self.assertIsNone(parse_board("draw me a cat"))


class BenchHttpTests(unittest.TestCase):
    def test_post_board_then_scene(self) -> None:
        from bench.bench import Handler, add_board, load_scene, save_scene, scene_path
        from http.server import ThreadingHTTPServer
        import json
        import urllib.request

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = JarvisHome(Path(tmp.name) / "jarvis")
        home.ensure()
        dest = scene_path(home.root)
        scene = {"units": "mm", "parts": []}
        add_board(scene, 1600, 70, 15, "rail")
        save_scene(dest, scene)
        loaded = load_scene(dest)
        self.assertEqual(len(loaded["parts"]), 1)
        self.assertEqual(loaded["parts"][0]["length_mm"], 1600)

        Handler.data_dir = home.root
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/scene") as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(data["parts"][0]["width_mm"], 70)


if __name__ == "__main__":
    unittest.main()
