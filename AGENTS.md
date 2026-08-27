# Jarvis

Before any work, including this session: **does this move us toward a JARVIS-like system from the movies?**

If the answer is no — accessory, second personality, extra cap, nested chatbot — do not do it. House, Watch, Tailscale, Pi, Forge polish wait until the mind is one person.

## The movie line

You never talk to a receptionist, and you never wait while he thinks in another room. You talk to Jarvis; some of him is busy; he can still answer.

- **One presence.** Same persona on the mouth and the hands. Never “the workshop.” Never a dispatcher.
- **Mouth never waits on hands.** A single `grok agent` process cannot chat and run a long job. Two (or more) Grok processes plus a shared brief is one brain. Immediate short ack, then the mouth is free.
- **Easy questions stay on the mouth.** How is the work going, weather, calendar, lights, hush — from local notes/cache/job brief, in character. Not a canned status line. Not a second Grok hop to classify banter.
- **Hard work is the other thread.** Coding, Imagine, cold web search, long docs. Full Grok Build tools. Progress written into a brief the mouth can read.

Default to conversation. Unsure is talk. Only enqueue work that would steal the mouth.

## This PC, full SuperGrok

Jarvis should drive as much of this machine as a skilled human at the keyboard, using the SuperGrok stack already paid for — not a toy subset.

| You have | Jarvis uses it as |
|---|---|
| SuperGrok Heavy | `grok-4.6`. Hands: high/`xhigh` for real work. Mouth: faster effort so talk stays snappy. |
| Grok Build CLI | The hands. Same tools as an interactive `grok` session: terminal, files, grep, web, Imagine, subagents, MCP. Working directory is the machine (repos, home files), not only this checkout. |
| Grok Imagine | Hands thread. Stills and video. Never on the talking session. |
| Cursor | Sibling harness, same disk. Do not nest Cursor or drive its GUI. Jarvis edits files and runs the terminal himself. |
| Grok app / grok.com / Grok on X | Same account, not a tool. Do not wrap another chatbot. This Talk process is the assistant. |

`run_terminal_cmd` is how a human’s PC tools show up: git, tests, apt, ffmpeg, later Ableton/Fusion/browser CLIs. Per-app GUI puppets are later, and only if they pass the movie test.

Do **not** put Bash/Write/Imagine on the talking Grok session. That is dead air and a coding agent with a mic.

## Safety that is still movie-correct

- Secrets stay in `~/.jarvis/secrets`. Never git, never chat, never the desk prompt.
- Unlocks, garage, doors wait for a spoken **yes**.
- This live Talk process is not rewritten or restarted from under itself. Hands may patch `jarvis/workshop-*`. Merge to `main` stays a human gate until merge-on-yes exists.
- Latest-wins mouth: new speech cuts TTS. Hands keep working unless he told them to stop the job.

## Now vs later

**Now:** one persona, live job brief on the mouth, default-to-talk, hands = full Grok Build, easy facts from cache.

**Later (still movie, not first):** always-on home host, wake word, speaker ID, house mics, calendar file, Forge/Watch as “knows my body.” Phone already finds Talk over Tailscale (`svc:jarvis`); that is not a second brain.

Read `HANDOFF.md` for machine-specific state. Do not treat the old receptionist/router/caps design as the product.
