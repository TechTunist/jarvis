"""Fold several user lines into one desk turn. Never answer a backlog one-by-one."""
from __future__ import annotations

from memory.intent import classify

_PING = (
    r"hello",
    r"hi",
    r"hey",
    r"anyone there",
    r"you there",
    r"still there",
    r"are you there",
    r"you awake",
)


def is_ping(text: str) -> bool:
    raw = " ".join((text or "").split()).lower().strip(" ?!.")
    return raw in _PING or raw.rstrip("?") in _PING


def latest_wins(
    items: list[tuple[str, int | None]],
) -> list[tuple[str, int | None]]:
    """LIFO of one: only the last real command. Older queued lines are dropped.

    Quit still wins so the session can end. A quiet-clip with no later words stays.
    """
    if not items:
        return []
    quit_item = None
    quiet_item = None
    last = None
    for item in items:
        text = item[0]
        if text == "__quit__":
            quit_item = item
        elif text == "__quiet__":
            quiet_item = item
        else:
            last = item
    out: list[tuple[str, int | None]] = []
    if last is not None:
        out.append(last)
    elif quiet_item is not None:
        out.append(quiet_item)
    if quit_item is not None:
        out.append(quit_item)
    return out


def split_batch(
    texts: list[str],
    intents: list | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Job utterances, status/ping utterances, chat utterances — original order kept inside each."""
    jobs: list[str] = []
    status: list[str] = []
    chat: list[str] = []
    for i, text in enumerate(texts):
        if intents is not None:
            kind = getattr(intents[i], "kind", None) or classify(text).kind
        else:
            kind = classify(text).kind
        if kind == "status":
            status.append(text)
        elif kind == "chat":
            chat.append(text)
        else:
            jobs.append(text)
    return jobs, status, chat


def coalesce_chat(texts: list[str], *, occupied: bool = False) -> str:
    cleaned = [" ".join((t or "").split()) for t in texts if " ".join((t or "").split())]
    if not cleaned:
        return ""
    if len(cleaned) == 1 and not occupied:
        return cleaned[0]
    body = "\n".join(f"- {t}" for t in cleaned)
    if occupied:
        lead = (
            "Matt spoke while you were occupied with a workshop job and did not "
            "get an answer at the time. Give ONE short reply that covers all of "
            "it. First sentence at most six words. Acknowledge you were busy; "
            "do not answer each line separately; no list.\n\n"
        )
    else:
        lead = (
            "Matt said several things in a row before you answered. Give ONE "
            "short reply that covers all of it. First sentence at most six words. "
            "Do not answer each line separately; no list.\n\n"
        )
    return lead + "He said:\n" + body
