"""Semantic router: Grok understands; regex is only the obvious fast path."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory.home import JarvisHome
from memory.intent import CHAT, CODE, HOME, IMAGINE, REMEMBER, SEARCH, classify, maybe_enqueue, resolve_intent
from memory.jobs import JobBoard
from memory.route import obvious_chat, semantic_route
from memory.workshops import WorkshopRegistry


def _run(cap: str | list[str]):
    def inner(prompt: str) -> str:
        inner.prompts.append(prompt)
        if isinstance(cap, list):
            return json.dumps({"caps": cap})
        return json.dumps({"cap": cap})

    inner.prompts = []
    return inner


class ObviousChatTests(unittest.TestCase):
    def test_hellos(self) -> None:
        for text in (
            "Hello Jarvis",
            "hi",
            "How are you?",
            "good morning",
            "thanks",
        ):
            with self.subTest(text=text):
                self.assertTrue(obvious_chat(text), text)

    def test_commands_are_not_obvious_chat(self) -> None:
        for text in (
            "it is a little dark in the living room",
            "turn on the charm",
            "how's the weather",
            "yes",
        ):
            with self.subTest(text=text):
                self.assertFalse(obvious_chat(text), text)


class SemanticRouteTests(unittest.TestCase):
    def test_routes_natural_commands(self) -> None:
        cases = (
            ("it is a little dark in the living room", "home", HOME.cap),
            ("kill the glow by the sofa", "home", HOME.cap),
            ("don't let me forget the bins", "vault-write", REMEMBER.cap),
            ("look up whether the trains are off", "search", SEARCH.cap),
            ("spin me an Iron Man hologram", "imagine", IMAGINE.cap),
            ("run the tests in this repo", "shell", CODE.cap),
        )
        caps = ("home", "search", "vault-write", "imagine", "shell")
        for said, cap, want in cases:
            with self.subTest(said=said):
                got = semantic_route(said, caps=caps, run=_run(cap))
                self.assertEqual(got[0].cap, want)

    def test_banter_stays_chat(self) -> None:
        caps = ("home", "search", "vault-write", "imagine")
        for said in (
            "turn on the charm",
            "I imagine so",
            "that's news to me",
        ):
            with self.subTest(said=said):
                got = semantic_route(said, caps=caps, run=_run("chat"))
                self.assertIsNone(got[0].cap)

    def test_timeout_and_junk_are_chat(self) -> None:
        def boom(_prompt: str) -> str:
            raise TimeoutError("nope")

        self.assertIsNone(semantic_route("gloomy in here", caps=("home",), run=boom)[0].cap)

        def junk(_prompt: str) -> str:
            return "not json at all"

        self.assertIsNone(semantic_route("gloomy in here", caps=("home",), run=junk)[0].cap)

    def test_unknown_cap_is_chat(self) -> None:
        got = semantic_route(
            "launch the spaceship",
            caps=("home",),
            run=_run("spaceship"),
        )
        self.assertIsNone(got[0].cap)

    def test_no_runner_is_chat(self) -> None:
        self.assertIsNone(semantic_route("gloomy in here", caps=("home",))[0].cap)

    def test_mixed_make_request_returns_imagine_and_docs(self) -> None:
        caps = ("home", "search", "vault-write", "imagine", "docs")
        said = (
            "create a parts list and animations of how the parts go together, "
            "then a pdf of the build instructions"
        )
        got = semantic_route(
            said,
            caps=caps,
            run=_run(["imagine", "docs"]),
        )
        self.assertEqual([i.cap for i in got], ["imagine", "docs"])
        from memory.intent import resolve_intents

        routed = resolve_intents(said, caps=caps)
        self.assertEqual({i.cap for i in routed}, {"imagine", "docs"})


class ResolveIntentTests(unittest.TestCase):
    def test_fast_path_skips_router(self) -> None:
        runner = _run("chat")
        intent = resolve_intent(
            "turn on the kitchen lights",
            caps=("home",),
            run=runner,
        )
        self.assertEqual(intent.cap, HOME.cap)
        self.assertEqual(runner.prompts, [])

    def test_obvious_hello_skips_router(self) -> None:
        runner = _run("home")
        intent = resolve_intent("Hello Jarvis", caps=("home",), run=runner)
        self.assertEqual(intent.kind, CHAT.kind)
        self.assertEqual(runner.prompts, [])

    def test_glow_is_home_without_router(self) -> None:
        runner = _run("chat")
        intent = resolve_intent(
            "kill the glow by the sofa",
            caps=("home",),
            run=runner,
        )
        self.assertEqual(intent.cap, HOME.cap)
        self.assertEqual(runner.prompts, [])

    def test_regex_chat_examples_stay_chat_without_runner(self) -> None:
        for text in (
            "Hello Jarvis",
            "How are you?",
            "Turn on the charm",
            "I imagine so",
            "Generate a report",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text).kind, CHAT.kind)
                self.assertEqual(resolve_intent(text).kind, CHAT.kind)


class EnqueueRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = JarvisHome(Path(self.tmp.name) / "jarvis")
        self.home.ensure()
        self.board = JobBoard(self.home)
        self.reg = WorkshopRegistry(self.home)

    def test_router_home_enqueues(self) -> None:
        self.reg.advertise("host", ["home"])
        hit = maybe_enqueue(
            "kill the glow by the sofa",
            self.board,
            self.reg,
            run=_run("home"),
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0].cap, "home")

    def test_router_cap_without_worker_is_none(self) -> None:
        self.reg.advertise("host", ["search"])
        self.assertIsNone(
            maybe_enqueue(
                "kill the glow by the sofa",
                self.board,
                self.reg,
                run=_run("home"),
            )
        )


if __name__ == "__main__":
    unittest.main()
