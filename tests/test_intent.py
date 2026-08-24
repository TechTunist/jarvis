"""Local intent gate: false positives steal hellos."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.intent import (
    ANIMATE,
    CHAT,
    CODE,
    FORGE,
    HOME,
    HUSH,
    IMAGINE,
    REMEMBER,
    SEARCH,
    STATUS,
    classify,
    file_line,
    maybe_enqueue,
    remember_dest,
    resolve_intent,
)
from memory.jobs import JobBoard
from memory.workshops import WorkshopRegistry


class ClassifyTests(unittest.TestCase):
    def test_chat_is_the_default(self) -> None:
        for text in (
            "Hello Jarvis",
            "How are you?",
            "Remember me?",
            "Search your feelings",
            "Turn on the charm",
            "That's news to me",
            "I need to commit to this diet",
            "I imagine so",
            "Can you imagine",
            "Imagine that",
            "Generate a report",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).kind, CHAT.kind)

    def test_forge_training_log(self) -> None:
        self.assertEqual(classify("how was my last workout").cap, FORGE.cap)
        self.assertEqual(classify("did I train yesterday").cap, FORGE.cap)

    def test_search(self) -> None:
        for text in (
            "What's the weather in London?",
            "Look up the Premier League table",
            "Search for the nearest pharmacy",
            "What are the headlines?",
            "What's the stock price of Tesla?",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).cap, SEARCH.cap)

    def test_remember(self) -> None:
        self.assertEqual(classify("Remember I take tea at five.").cap, REMEMBER.cap)
        self.assertEqual(classify("Please remember that Matt hates beets.").kind, "remember")
        self.assertEqual(classify("Don't forget I work from home on Fridays.").kind, "remember")
        self.assertEqual(classify("Never do that again.").kind, "remember")
        self.assertEqual(remember_dest("Never do that again."), "never")
        self.assertEqual(remember_dest("Remember I take tea at five."), "household")
        self.assertEqual(
            classify("change the weather to Canterbury instead of London").cap,
            REMEMBER.cap,
        )
        self.assertEqual(
            classify("remove boy at the entrance that was a misunderstanding").cap,
            REMEMBER.cap,
        )
        self.assertEqual(classify("What's the weather tomorrow, Jarvis?").cap, SEARCH.cap)

    def test_remember_comma_and_timed_reminder(self) -> None:
        uttered = "remember, I need to check your codebase at 8pm every day"
        self.assertEqual(classify(uttered).cap, REMEMBER.cap)
        self.assertEqual(remember_dest(uttered), "reminders")
        self.assertEqual(classify("Remind me at 8pm to check the codebase").cap, REMEMBER.cap)
        self.assertEqual(classify("Set a reminder for 8pm").kind, "remember")
        self.assertEqual(remember_dest("Set a reminder for 8pm"), "reminders")

    def test_hush_is_not_the_house(self) -> None:
        for text in (
            "stop talking",
            "stop all talking",
            "be quiet",
            "shut up",
            "sotp talking",
            "you got it. microphones for voice commands . now stop all talking",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).kind, HUSH.kind)

    def test_home_needs_a_house_noun(self) -> None:
        self.assertEqual(classify("Turn on the kitchen lights").cap, HOME.cap)
        self.assertEqual(classify("turn the kitchen lights off").cap, HOME.cap)
        self.assertEqual(classify("Let me turn on the lamp, please.").cap, HOME.cap)
        self.assertEqual(classify("Is the garage closed?").cap, HOME.cap)
        self.assertEqual(classify("Unlock the door").cap, HOME.cap)
        self.assertEqual(classify("Turn on the radio").kind, CHAT.kind)
        self.assertEqual(
            classify("it is too bright in the living room jarvis").cap, HOME.cap
        )
        self.assertEqual(classify("the living room is too bright").cap, HOME.cap)
        self.assertEqual(classify("dim the living room").cap, HOME.cap)
        self.assertEqual(classify("what lights do we have").cap, HOME.cap)
        self.assertEqual(classify("that's too bright a future").kind, CHAT.kind)
        self.assertEqual(
            classify("it is a little dark in the living room").cap, HOME.cap
        )
        self.assertEqual(
            classify("it is still dark in the living room jarvis").cap, HOME.cap
        )

    def test_imagine(self) -> None:
        for text in (
            "Generate an image of a cat",
            "Make me a picture of a castle",
            "Imagine an image of a robot butler",
            "Imagine a golden sunset",
            "Draw me a picture of the kitchen",
            "Draw me a castle",
            "Create a photo of a fox",
            "Please generate an image of Mars",
            "Generate a rotating image of the original iron man suit",
            "generate a rotating model of the iron man suit from the original animated tv show please",
            "create a quick animation on imagine of an Arsenal FC badge",
            "create a cool Iron Man looking holographic animation that resembles a scene from the movie",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).cap, IMAGINE.cap)
        self.assertEqual(classify("Turn on the lamp").cap, HOME.cap)
        self.assertEqual(classify("how is progress on that animation").kind, STATUS.kind)
        self.assertEqual(classify("let me knoe when half done pleae").kind, STATUS.kind)
        self.assertEqual(classify("why didn't you tell me when it was complete").kind, STATUS.kind)
        self.assertEqual(classify("where's the video").kind, STATUS.kind)
        self.assertEqual(
            classify(
                "can you create a parts list and build instructions? "
                "maybe use images to create animations of how the parts "
                "go together, then a pdf document"
            ).cap,
            IMAGINE.cap,
        )
        self.assertEqual(
            classify("have you initiated the animation or the pdf instructions yet?").kind,
            STATUS.kind,
        )
        self.assertEqual(
            classify("so the workshop is busy creating the material?").kind,
            STATUS.kind,
        )
        self.assertEqual(classify("What's the weather in London?").kind, SEARCH.kind)
        rotating = classify("Generate a rotating image of the original iron man suit")
        self.assertEqual(rotating.ack, ANIMATE.ack)
        self.assertEqual(rotating.wait_s, 0.0)
        self.assertEqual(classify("Imagine a golden sunset").wait_s, 0.0)

    def test_code_is_conservative(self) -> None:
        self.assertEqual(classify("Run the tests in this repo").cap, CODE.cap)
        self.assertEqual(classify("Edit talk.py please").kind, CHAT.kind)
        self.assertEqual(classify("Edit talk.py in the repo").cap, CODE.cap)

    def test_file_line_strips_wrapper(self) -> None:
        self.assertEqual(file_line("Remember I take tea at five."), "I take tea at five")
        self.assertEqual(file_line("Please remember that Matt hates beets."), "Matt hates beets")
        self.assertTrue(
            file_line("remember, I need to check your codebase at 8pm every day")
            .lower()
            .startswith("i need")
        )

    def test_acks_rotate(self) -> None:
        from memory.intent import _ACKS, pick_ack, with_ack

        seen = {pick_ack(SEARCH) for _ in range(20)}
        self.assertTrue(seen <= set(_ACKS["search"]))
        self.assertGreater(len(seen), 1)
        a = with_ack(SEARCH)
        self.assertEqual(a.cap, SEARCH.cap)
        self.assertIn(a.ack, _ACKS["search"])


class EnqueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)
        self.reg = WorkshopRegistry(self.home)

    def test_chat_does_not_enqueue(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(maybe_enqueue("Hello Jarvis", self.board, self.reg))

    def test_search_without_worker_falls_through(self) -> None:
        self.assertIsNone(maybe_enqueue("What's the weather?", self.board, self.reg))
        self.assertEqual(self.board.job_ids(), [])

    def test_search_with_worker_enqueues(self) -> None:
        self.reg.advertise("host", ["search"])
        hit = maybe_enqueue("What's the weather in London?", self.board, self.reg)
        self.assertIsNotNone(hit)
        assert hit is not None
        intent, job_id = hit
        self.assertEqual(intent.cap, "search")
        self.assertEqual(self.board.latest_status(job_id), "enqueued")

    def test_imagine_enqueue_marks_video(self) -> None:
        self.reg.advertise("host", ["imagine"])
        hit = maybe_enqueue(
            "Generate a rotating image of the original iron man suit",
            self.board,
            self.reg,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        intent, job_id = hit
        self.assertEqual(intent.wait_s, 0.0)
        self.assertEqual(self.board.snapshot(job_id).get("media"), "video")

    def test_imagine_needs_cap(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(maybe_enqueue("Imagine a golden sunset", self.board, self.reg))
        self.reg.advertise("host", ["search", "imagine"])
        hit = maybe_enqueue("Imagine a golden sunset", self.board, self.reg)
        self.assertIsNotNone(hit)
        assert hit is not None
        intent, job_id = hit
        self.assertEqual(intent.cap, "imagine")
        self.assertEqual(self.board.latest_status(job_id), "enqueued")

    def test_remember_needs_vault_write_cap(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(maybe_enqueue("Remember I take tea at five.", self.board, self.reg))
        self.reg.advertise("host", ["search", "vault-write"])
        hit = maybe_enqueue("Remember I take tea at five.", self.board, self.reg)
        self.assertIsNotNone(hit)

    def test_shell_enqueues_when_advertised(self) -> None:
        self.reg.advertise("laptop", ["shell"], roots=["/tmp/src"])
        hit = maybe_enqueue("Run the tests in this repo", self.board, self.reg)
        self.assertIsNotNone(hit)
        assert hit is not None
        intent, job_id = hit
        self.assertEqual(intent.cap, "shell")
        self.assertEqual(self.board.snapshot(job_id).get("root"), "/tmp/src")

    def test_shell_needs_cap(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(maybe_enqueue("Run the tests in this repo", self.board, self.reg))


if __name__ == "__main__":
    unittest.main()
