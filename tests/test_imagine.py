"""Imagine helpers: slugs, albums, path scrape, settle outside the git checkout."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from memory.imagine import (
    album_dir,
    append_index,
    collect_new_images,
    files_from_stream,
    folder_phrase,
    imagine_subject,
    is_scratch,
    library_root,
    parse_imagine_request,
    resolve_image_path,
    settle_image,
    slug_title,
    speak_ready,
    stray_repo_blob,
    wants_animation,
    wants_assembly,
)


class ImagineHelperTests(unittest.TestCase):
    def test_subject_and_slug(self) -> None:
        self.assertEqual(imagine_subject("Imagine a golden sunset"), "a golden sunset")
        self.assertEqual(
            imagine_subject("Generate an image of a cat"),
            "a cat",
        )
        self.assertEqual(imagine_subject("Draw me a castle"), "castle")
        self.assertEqual(
            imagine_subject(
                "Generate a rotating image of the original iron man suit"
            ).lower(),
            "the original iron man suit",
        )
        self.assertEqual(slug_title("a golden sunset"), "golden-sunset")
        self.assertEqual(slug_title(""), "picture")

    def test_wants_animation(self) -> None:
        self.assertTrue(wants_animation("Generate a rotating image of the iron man suit"))
        self.assertTrue(wants_animation("make a video of a cat"))
        self.assertFalse(wants_animation("Imagine a golden sunset"))

    def test_wants_assembly(self) -> None:
        self.assertTrue(
            wants_assembly("animation of how the components go together")
        )
        self.assertFalse(wants_assembly("rotating image of the iron man suit"))

    def test_library_roots_respect_env(self) -> None:
        import os

        prev_p = os.environ.get("JARVIS_PICTURES")
        prev_v = os.environ.get("JARVIS_VIDEOS")
        os.environ["JARVIS_PICTURES"] = "/tmp/pics-jarvis"
        os.environ["JARVIS_VIDEOS"] = "/tmp/vids-jarvis"
        try:
            self.assertEqual(library_root("still"), Path("/tmp/pics-jarvis").resolve())
            self.assertEqual(library_root("video"), Path("/tmp/vids-jarvis").resolve())
        finally:
            if prev_p is None:
                os.environ.pop("JARVIS_PICTURES", None)
            else:
                os.environ["JARVIS_PICTURES"] = prev_p
            if prev_v is None:
                os.environ.pop("JARVIS_VIDEOS", None)
            else:
                os.environ["JARVIS_VIDEOS"] = prev_v

    def test_parse_default_has_no_album(self) -> None:
        subject, album = parse_imagine_request("Imagine a golden sunset")
        self.assertEqual(subject, "a golden sunset")
        self.assertIsNone(album)

    def test_parse_spoken_album(self) -> None:
        subject, album = parse_imagine_request(
            "Generate an image of a cat for the HUD project"
        )
        self.assertEqual(subject, "a cat")
        self.assertEqual(album, "hud")
        subject, album = parse_imagine_request(
            "Make a picture of a fox in the kitchen folder"
        )
        self.assertEqual(subject, "a fox")
        self.assertEqual(album, "kitchen")
        subject, album = parse_imagine_request(
            "Imagine a robot save it in the mood board"
        )
        self.assertEqual(subject, "a robot")
        self.assertEqual(album, "mood-board")

    def test_parse_does_not_steal_for_the_kids(self) -> None:
        subject, album = parse_imagine_request("Imagine a gift for the kids")
        self.assertIn("gift", subject.lower())
        self.assertIsNone(album)

    def test_reserved_and_traversal_fall_back(self) -> None:
        self.assertIsNone(parse_imagine_request("Imagine a cat save it in vault")[1])
        self.assertIsNone(parse_imagine_request("Imagine a cat save it in ../secrets")[1])
        self.assertIsNone(parse_imagine_request("Imagine a cat save it in 2026-08-23")[1])

    def test_album_dir_date_and_named(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "imagine"
        root.mkdir()
        day = date(2026, 8, 23)
        self.assertEqual(album_dir(root, None, today=day), (root / "2026-08-23").resolve())
        self.assertEqual(
            album_dir(root, "hud", today=day),
            (root / "albums" / "hud").resolve(),
        )

    def test_files_from_stream(self) -> None:
        stream = "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_call_update",
                        "toolName": "image_gen",
                        "rawOutput": {"path": "/tmp/imagine/images/1.jpg"},
                    }
                ),
                json.dumps({"type": "text", "data": "saved"}),
            ]
        )
        self.assertEqual(files_from_stream(stream), ["/tmp/imagine/images/1.jpg"])

    def test_settle_copies_out_of_repo_tree(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        repo = root / "checkout"
        dest = root / "jarvis" / "imagine" / "2026-08-23"
        repo.mkdir()
        dest.mkdir(parents=True)
        src = repo / "1.jpg"
        src.write_bytes(b"\xff\xd8\xff\xd9")
        self.assertTrue(stray_repo_blob(src, repo=repo))
        final = settle_image(src, dest, "sunset", repo=repo)
        self.assertTrue(final.is_file())
        self.assertEqual(final.parent, dest.resolve())
        self.assertIn("sunset", final.name)
        self.assertFalse(src.exists())
        grok_sess = root / ".grok-session" / "images"
        grok_sess.mkdir(parents=True)
        stray = grok_sess / "2.jpg"
        stray.write_bytes(b"\xff\xd8\xff\xd9")
        self.assertTrue(is_scratch(stray, repo=repo) or stray.parent.name == "images")

    def test_index_and_speak_folder(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        day = root / "2026-08-23"
        day.mkdir()
        hit = day / "085848-sunset.jpg"
        hit.write_bytes(b"\xff\xd8\xff\xd9")
        append_index(root, "2026-08-23/085848-sunset.jpg", "golden sunset")
        body = (root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("2026-08-23/085848-sunset.jpg", body)
        self.assertIn("golden sunset", body)
        self.assertEqual(
            folder_phrase(hit, root, today=date(2026, 8, 23)),
            "today's Pictures folder",
        )
        line = speak_ready(hit, "Golden sunset", root=root, today=date(2026, 8, 23))
        self.assertTrue(line.startswith("Ready, sir."))
        self.assertIn("today's Pictures folder", line)
        self.assertNotIn("085848", line)

    def test_collect_new_and_speak(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        images = root / "images"
        images.mkdir()
        now = time.time()
        hit = images / "1.jpg"
        hit.write_bytes(b"\xff\xd8\xff\xd9")
        found = collect_new_images(root, now - 1)
        self.assertEqual(found, [hit])
        self.assertEqual(
            resolve_image_path("images/1.jpg", root),
            hit.resolve(),
        )
        line = speak_ready(hit, "Orange cat")
        self.assertTrue(line.startswith("Ready, sir."))
        self.assertIn("Orange cat", line)


if __name__ == "__main__":
    unittest.main()
