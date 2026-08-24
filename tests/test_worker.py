"""Host workshop with a fake grok runner — no network, no GPU."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.jobs import JobBoard
from memory.session import SessionLog
from memory.grokrun import extract_json, text_from_stream
from memory.worker import HostWorker, append_bullet, dest_path, extract_place
from memory.workshops import WorkshopRegistry


def fake_complete(prompt: str, **kwargs) -> str:
    tools = str(kwargs.get("tools") or "")
    if "image_to_video" in tools:
        cwd = Path(str(kwargs.get("cwd") or "."))
        cwd.mkdir(parents=True, exist_ok=True)
        dest = cwd / "spin.mp4"
        dest.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return json.dumps({"path": str(dest), "title": "Iron Man", "kind": "video"})
    if "image_gen" in tools:
        cwd = Path(str(kwargs.get("cwd") or "."))
        cwd.mkdir(parents=True, exist_ok=True)
        dest = cwd / "cat.jpg"
        dest.write_bytes(b"\xff\xd8\xff\xd9")
        return json.dumps({"path": str(dest), "title": "Orange cat"})
    if "Write the markdown guide" in prompt or "markdown document Jarvis will save" in str(
        kwargs.get("system") or ""
    ):
        return (
            "# Wireless room microphone\n\n"
            "## Parts\n- ESP32-S3\n- MEMS microphone capsule\n"
            "- BMS with USB-C charge port\n- Reclaimed vape cells\n"
            "- Mute switch and status LED\n- Shelf enclosure\n\n"
            "## Power\nOne matched pack per node through the BMS. USB-C is charge only.\n\n"
            "## Assembly\n1. Mount the capsule at the enclosure face.\n"
            "2. Wire mic data to the S3.\n3. Fit the pack and BMS.\n"
            "4. Bring out mute and LED.\n\n"
            "## Flash\nSame firmware image on every unit. MQTT or WebSocket to host-xps.\n\n"
            "## Test\nMute kills the link LED. Desk hears a clap from that room.\n"
        )
    if kwargs.get("web"):
        return "Rain later, sir. Take a coat."
    if "Transcript:" in prompt:
        return json.dumps(
            {"facts": [{"dest": "household", "bullet": "Prefers tea at five."}]}
        )
    return json.dumps({"bullet": "Tea at five."})


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.pictures = Path(self.tmp.name) / "Pictures" / "jarvis"
        self.videos = Path(self.tmp.name) / "Videos" / "jarvis"
        self.pictures.mkdir(parents=True)
        self.videos.mkdir(parents=True)
        prev_p = os.environ.get("JARVIS_PICTURES")
        prev_v = os.environ.get("JARVIS_VIDEOS")
        os.environ["JARVIS_PICTURES"] = str(self.pictures)
        os.environ["JARVIS_VIDEOS"] = str(self.videos)

        def restore_media_env() -> None:
            if prev_p is None:
                os.environ.pop("JARVIS_PICTURES", None)
            else:
                os.environ["JARVIS_PICTURES"] = prev_p
            if prev_v is None:
                os.environ.pop("JARVIS_VIDEOS", None)
            else:
                os.environ["JARVIS_VIDEOS"] = prev_v

        self.addCleanup(restore_media_env)
        self.board = JobBoard(self.home)
        self.worker = HostWorker(
            self.home,
            worker_id="host-test",
            complete=fake_complete,
            heartbeat_s=0.01,
        )

    def test_search_and_weather_cache(self) -> None:
        jid = self.board.enqueue("search", "What's the weather in London?")
        self.worker.advertise()
        self.assertTrue(self.worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        self.assertIn("Rain later", snap["speak"])
        weather = (self.home.cache / "weather.md").read_text(encoding="utf-8")
        self.assertIn("Rain later", weather)

    def test_remember_appends_household(self) -> None:
        jid = self.board.enqueue(
            "vault-write",
            "Remember I take tea at five.",
            extra={"dest": "household"},
        )
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.board.latest_status(jid), "done")
        body = (self.home.vault / "people" / "_household.md").read_text(encoding="utf-8")
        self.assertIn("Tea at five", body)
        self.assertTrue(self.worker.tick() is False)

    def test_remember_without_grok_still_files(self) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("no grok")

        worker = HostWorker(self.home, worker_id="host-offline", complete=boom)
        jid = self.board.enqueue("vault-write", "Remember I take tea at five.")
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "done")
        body = (self.home.vault / "people" / "_household.md").read_text(encoding="utf-8")
        self.assertIn("I take tea at five", body)

    def test_vault_place_and_forget(self) -> None:
        path = dest_path(self.home, "household")
        assert path is not None
        append_bullet(path, "Home weather location is London")
        append_bullet(path, "Boy is at the entrance")
        jid = self.board.enqueue(
            "vault-write",
            "change the weather to Canterbury, Kent UK",
            extra={"dest": "household", "action": "place"},
        )
        self.assertTrue(self.worker.tick())
        body = path.read_text(encoding="utf-8")
        self.assertIn("Canterbury", body)
        self.assertNotIn("London", body)
        self.assertIn("Canterbury", self.board.snapshot(jid).get("speak") or "")
        jid2 = self.board.enqueue(
            "vault-write",
            "remove boy at the entrance that was a misunderstanding",
            extra={"dest": "household", "action": "forget"},
        )
        self.assertTrue(self.worker.tick())
        self.assertNotIn("Boy", path.read_text(encoding="utf-8"))
        self.assertIn("Removed", self.board.snapshot(jid2).get("speak") or "")
        self.assertIn("Canterbury", extract_place("The weather should use Canterbury, Kent UK"))

    def test_distill_files_facts(self) -> None:
        log = SessionLog.start(self.home)
        log.record("Remember I take tea at five.", "Noted, sir.")
        log.close()
        jid = self.board.enqueue(
            "distill",
            "file facts",
            path=str(log.path),
        )
        self.assertTrue(self.worker.tick())
        self.assertEqual(self.board.latest_status(jid), "done")
        household = (self.home.vault / "people" / "_household.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Prefers tea at five", household)

    def test_heartbeat_has_caps(self) -> None:
        self.worker.advertise()
        reg = WorkshopRegistry(self.home)
        self.assertTrue(reg.has_cap("search"))
        self.assertTrue(reg.has_cap("vault-write"))
        self.assertTrue(reg.has_cap("distill"))
        self.assertTrue(reg.has_cap("home"))
        self.assertTrue(reg.has_cap("imagine"))
        self.assertTrue(reg.has_cap("docs"))
        self.assertTrue(reg.has_cap("forge"))
        self.assertFalse(reg.has_cap("shell"))

    def test_docs_writes_pdf_under_documents(self) -> None:
        docs = Path(self.tmp.name) / "Documents" / "jarvis"
        docs.mkdir(parents=True)
        prev = os.environ.get("JARVIS_DOCUMENTS")
        os.environ["JARVIS_DOCUMENTS"] = str(docs)
        self.addCleanup(
            lambda: os.environ.pop("JARVIS_DOCUMENTS", None)
            if prev is None
            else os.environ.__setitem__("JARVIS_DOCUMENTS", prev)
        )
        jid = self.board.enqueue(
            "docs",
            "parts list and PDF build instructions for the wireless room mics",
        )
        self.assertTrue(self.worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        pdf = Path(str(snap.get("result") or ""))
        self.assertTrue(pdf.is_file(), snap)
        self.assertEqual(pdf.suffix, ".pdf")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertIn("Documents", snap.get("speak") or "")

    def test_docs_rejects_workspace_stall(self) -> None:
        def stall(prompt: str, **kwargs) -> str:
            return (
                "I need the hardware details Matt already described so the "
                "guide freezes one repeatable recipe. Searching the workspace "
                "for that context."
            )

        worker = HostWorker(
            self.home, worker_id="host-docs-stall", complete=stall, heartbeat_s=0.01
        )
        jid = self.board.enqueue("docs", "pdf of the mic build")
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "error")
        self.assertIn("real guide", self.board.snapshot(jid).get("error") or "")

    def test_imagine_saves_under_home_not_repo(self) -> None:
        from datetime import date

        from memory.imagine import REPO_ROOT

        jid = self.board.enqueue("imagine", "Imagine a golden sunset")
        self.assertTrue(self.worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        dest = Path(str(snap.get("result") or ""))
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.parent, (self.pictures / date.today().isoformat()).resolve())
        self.assertTrue(dest.name.endswith(".jpg"))
        self.assertIn("Ready, sir.", snap["speak"])
        self.assertIn("today's Pictures folder", snap["speak"])
        index = (self.pictures / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn(dest.name, index)
        try:
            dest.resolve().relative_to(REPO_ROOT.resolve())
            self.fail("generated image landed in the git checkout")
        except ValueError:
            pass

    def test_imagine_spoken_album(self) -> None:
        jid = self.board.enqueue(
            "imagine",
            "Generate an image of a cat for the HUD project",
        )
        self.assertTrue(self.worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        dest = Path(str(snap.get("result") or ""))
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.parent, (self.pictures / "albums" / "hud").resolve())
        self.assertIn("hud folder", snap["speak"])
        index = (self.pictures / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("albums/hud/", index.replace("\\", "/"))

    def test_imagine_animation_goes_to_videos(self) -> None:
        from datetime import date

        jid = self.board.enqueue(
            "imagine",
            "Generate a rotating image of the original iron man suit",
            extra={"media": "video"},
        )
        self.assertTrue(self.worker.tick())
        snap = self.board.snapshot(jid)
        self.assertEqual(snap["event"], "done")
        dest = Path(str(snap.get("result") or ""))
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.suffix.lower(), ".mp4")
        self.assertEqual(dest.parent, (self.videos / date.today().isoformat()).resolve())
        self.assertIn("Videos folder", snap["speak"])
        try:
            dest.resolve().relative_to(Path.home() / ".grok" / "sessions")
            self.fail("video landed in grok sessions")
        except ValueError:
            pass

    def test_imagine_fails_without_file(self) -> None:
        def silent(*_a, **_k):
            return json.dumps({"path": "", "title": "Nothing"})

        worker = HostWorker(self.home, worker_id="host-empty", complete=silent)
        jid = self.board.enqueue("imagine", "Generate an image of a cat")
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "error")

    def test_unsupported_cap_fails_job(self) -> None:
        jid = self.board.enqueue("spaceship", "launch")
        worker = HostWorker(
            self.home,
            worker_id="host-test",
            complete=fake_complete,
            caps=("spaceship",),
        )
        self.assertTrue(worker.tick())
        self.assertEqual(self.board.latest_status(jid), "error")

    def test_append_bullet_dedupes(self) -> None:
        path = dest_path(self.home, "household")
        assert path is not None
        self.assertTrue(append_bullet(path, "Tea at five."))
        self.assertFalse(append_bullet(path, "Tea at five."))
        self.assertEqual((self.home.vault / "people" / "_household.md").read_text(encoding="utf-8").count("Tea at five."), 1)

    def test_parent_gone(self) -> None:
        from memory.worker import _parent_gone

        self.assertTrue(_parent_gone(999_999_999))
        self.assertFalse(_parent_gone(os.getpid()))


class GrokrunParseTests(unittest.TestCase):
    def test_extract_json_and_stream_text(self) -> None:
        self.assertEqual(extract_json('{"bullet": "Tea at five."}')["bullet"], "Tea at five.")
        wrapped = 'Sure.\n{"facts": []}\n'
        self.assertEqual(extract_json(wrapped), {"facts": []})
        stream = '{"type":"text","data":"Rain "}\n{"type":"text","data":"later."}\n{"type":"end"}\n'
        self.assertEqual(text_from_stream(stream), "Rain later.")

    def test_prompt_argv_imagine_allowlists_image_gen(self) -> None:
        from memory.grokrun import prompt_argv

        argv = prompt_argv(
            "draw a cat",
            grok=Path("/tmp/grok"),
            model="grok-4.5",
            system="sys",
            web=False,
            tools="image_gen",
            cwd=Path("/tmp/imagine"),
        )
        self.assertIn("--tools", argv)
        self.assertIn("image_gen", argv)
        self.assertIn("--cwd", argv)
        self.assertEqual(argv[argv.index("--cwd") + 1], "/tmp/imagine")
        self.assertNotIn("--disallowed-tools", argv)
        self.assertIn("--disable-web-search", argv)
        self.assertIn("--no-leader", argv)

    def test_prompt_argv_search_keeps_web_not_shell(self) -> None:
        from memory.grokrun import prompt_argv

        argv = prompt_argv(
            "weather",
            grok=Path("/tmp/grok"),
            model="grok-4.5",
            system="sys",
            web=True,
        )
        self.assertIn("--disallowed-tools", argv)
        denied = argv[argv.index("--disallowed-tools") + 1]
        self.assertIn("run_terminal_cmd", denied)
        self.assertIn("image_gen", denied)
        self.assertNotIn("web_search", denied)
        self.assertNotIn("--disable-web-search", argv)

    def test_desk_no_tools_includes_imagine(self) -> None:
        from memory.grokrun import NO_TOOLS

        self.assertIn("image_gen", NO_TOOLS)
        self.assertIn("image_to_video", NO_TOOLS)

    def test_prompt_argv_shell_allowlists_repo_tools(self) -> None:
        from memory.grokrun import prompt_argv
        from memory.shell import SHELL_TOOLS

        argv = prompt_argv(
            "run tests",
            grok=Path("/tmp/grok"),
            model="grok-4.5",
            system="sys",
            web=False,
            tools=SHELL_TOOLS,
            cwd=Path("/tmp/jarvis"),
        )
        self.assertIn("--tools", argv)
        tools = argv[argv.index("--tools") + 1]
        self.assertIn("run_terminal_cmd", tools)
        self.assertIn("search_replace", tools)
        self.assertNotIn("--disallowed-tools", argv)
        self.assertIn("--cwd", argv)


if __name__ == "__main__":
    unittest.main()
