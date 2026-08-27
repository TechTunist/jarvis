# Jarvis

A **movie-shaped Jarvis** on SuperGrok: hold a key, speak, get a short British reply, with an Iron Man–style HUD. You talk to one presence; long work runs on another thread so the mouth never goes dead; a file-based memory means he knows the household without stuffing every conversation into every hello.

**Before any work:** does this move us toward JARVIS from the movies? See `AGENTS.md`.

This is **not** the Grok iOS app, **not** grok.com, and **not** Cursor. Talk is a local loop around Grok Build CLI (same SuperGrok Heavy login). The model runs on xAI’s servers; the dock (mic, Whisper, HUD, personality files) and the hands (terminal, files, Imagine) run on hardware you control.

## Existing features

- **Push-to-talk** — hold **Home**, speak, release. Mic is closed otherwise.
- **Local ears** — `faster-whisper` **base.en** by default (tiny is a speed option). CUDA when available. Whisper is primed with household names (Jak/Jack, lamp, rooms). USB/Focusrite is preferred over the laptop mic.
- **Brain** — warm `grok agent` (default **grok-4.6**, low effort). Same SuperGrok account as Grok Build. Tools stripped on this session so the front desk answers instead of becoming a coding agent.
- **Mouth** — Microsoft Edge neural TTS (`en-GB-ThomasNeural`, slightly lowered rate / raised pitch — closest legal British male to MCU JARVIS, not a celebrity clone). Streamed with a short silence preroll so the first word is not clipped. Offline fallback: Windows SAPI.
- **HUD** — fullscreen three.js J.A.R.V.I.S. in the browser (`https://127.0.0.1:8791/`). States: idle / listening / thinking / speaking. Press **F** for fullscreen.
- **Intent gate** — high-precision local keywords for obvious commands and hellos. Everything else is a short tool-free Grok JSON **router** (`home` / `search` / `vault-write` / `imagine` / `docs` / `shell` / `forge` / chat). When unsure, chat. The desk never pretends to have switched a light.
- **Host workshop** — Talk spawns a worker that advertises `search`, `vault-write`, `distill`, `home`, `imagine`, `docs`, `forge`. A Grok **router** reads between the lines for anything that is not an obvious hello or a regex-fast house/search/remember. Mixed “draw this and write a PDF” can enqueue **two** jobs. Search uses `grok -p` with web tools. Imagine uses `image_gen` / `image_to_video`. Docs writes a markdown guide plus a PDF in `~/Documents/jarvis/YYYY-MM-DD/`. Stills land in `~/Pictures/jarvis/`; animations in `~/Videos/jarvis/`. Never this git repo, never `~/.grok/sessions`. The desk acks immediately and speaks again when a file is ready. The desk never gets those tools. House commands use the Home Assistant REST API on the LAN; the token stays in `~/.jarvis/secrets`. Unlocks, garage, and doors wait for a spoken **yes**. `forge` is a **read-only** look at the BearJacked Supabase training log (login in `~/.jarvis/secrets/forge.json`).
- **Laptop `shell` workshop** — a **separate** worker on the machine that has this checkout. “Run the tests” runs `unittest` here. “Patch X” uses Grok Build tools on a `jarvis/workshop-*` branch. No merge, no push, no Talk restart — you gate that. The host workshop (HA token, Imagine) does not advertise `shell`.
- **Latest line wins** — queued utterances are not answered FIFO. New speech **interrupts** the mouth. A workshop job already running is **not** cancelled; he just stops reading old answers aloud. “Stop talking” is hush, not a house command.
- **iPhone** — Tailscale on, then Safari / Home Screen `https://jarvis.<tailnet>.ts.net/phone` (this house: `https://jarvis.tail9f6146.ts.net/phone`). Hold the gold button. Whisper and Grok stay on the Talk host; the phone is mic + speaker. Same icon if Talk moves to another tagged PC. Phone turns do not use the laptop speakers.
- **Single instance** — starting Talk stops a previous Talk window so you do not get two voices.
- **No extra Grok Voice bill** — Whisper is local; Thomas is Edge TTS; Grok is SuperGrok.

### How a turn works

1. Home down → record locally.  
2. Home up → Whisper turns audio into text on this machine. Grok never hears the raw voice.  
3. An intent gate (regex fast path, then a Grok router for the rest) either sends chat to the warm `grok agent`, or enqueues a workshop job and speaks a short ack.  
4. For search, Talk waits for the workshop and speaks the answer. Remember files a vault bullet. Imagine speaks a short ack immediately, keeps the desk free, then which folder when the file is ready (`~/Pictures/jarvis` or `~/Videos/jarvis`).  
5. HUD follows the same states.

This window (Grok Build while developing) is a **separate** `grok.exe` from Jarvis. Close Talk and Jarvis’s agent dies; this chat does not.

## Quick start (Windows)

You need: [Grok Build CLI](https://x.ai/build) (`grok login`), Python 3.12, a mic and speakers. An NVIDIA GPU is optional but faster for Whisper.

```bat
cd receptionist
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -r requirements-cuda.txt
talk.cmd
```

CUDA wheels are optional. Skip `requirements-cuda.txt` on a machine without NVIDIA (Whisper then uses CPU).

## Quick start (Ubuntu)

Same Python tree as Windows. Differences are **local**: the Grok binary is `~/.grok/bin/grok` (not `grok.exe`), ffmpeg/ffplay come from apt, and CUDA pip packages are skipped if there is no GPU.

```bash
sudo apt install python3-venv python3-pip ffmpeg libportaudio2 espeak-ng
cd receptionist
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# only if nvidia-smi works:
# .venv/bin/pip install -r requirements-cuda.txt
chmod +x talk.sh
./talk.sh
```

Push-to-talk uses **Home** via `pynput`. On Ubuntu 24.04 Wayland that often needs an **Xorg** session, or you can type (`choice 2`) / use the phone HUD. Windows SAPI is Windows-only; on Linux `--tts sapi` is espeak. Edge neural TTS is the same on both.

Do not commit `.venv`, `talk.pid`, or `certs/`. Keep using one git repo on both PCs.

Choose **3** for hold-Home + British neural + HUD.

| Choice | What it does |
|---|---|
| 1 | Typed only |
| 2 | Typed + British neural |
| 3 | Home key + **base** Whisper + British neural + HUD (recommended) |
| 4 | Same as 3 with **grok-4.6** |
| 5 | Home key + offline TTS |
| 6 | Home key + **tiny** Whisper (faster, sloppier) |
| m | List microphones |

Useful flags:

```bat
.venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt base --tts edge
.venv\Scripts\python talk.py --mic Focusrite
.venv\Scripts\python talk.py --list-mics
.venv\Scripts\python talk.py --no-hud
.venv\Scripts\python talk.py --no-workshop
.venv\Scripts\python talk.py --voice en-GB-RyanNeural
```

First hello after launch is slower; the brain warms during “Jarvis online.” Simple chat should land near **~2s to first word** after you release Home (hold time is not wait time). Asking the desk to search or read files is **not** this spike — Talk enqueues that work and a **workshop** process runs it in the background (see [The plan](#the-plan)).

## Repository layout

```
receptionist/          Voice loop, HUD, TTS (tool-free)
  hud/                 Desktop three.js face + iPhone hold-to-talk
memory/                Vault, job board, intent gate, workshops
  worker.py            Host caps: search, vault-write, distill, home, imagine, docs, forge
  shell.py             Laptop checkout only (tests / patch on a branch)
  forge.py             Read-only BearJacked / Supabase
  route.py             Grok JSON router (warm agent at runtime)
tests/                 unittest (no Grok, no GPU)
```

Talk runtime (`talk.pid`, `agent.stderr.log`, `.venv`, `certs/`) is gitignored.

Filing cabinet (not this git repo): **`~/.jarvis/`** or `$JARVIS_HOME` / `--data-dir`.

```
~/.jarvis/
  vault/               Private git: BOOT.md, people/, daily/, projects/, never.md, reminders.md
  jobs/                jobs/<id>.jsonl
  workshops/           heartbeat JSON
  logs/sessions/       jsonl of every turn (latency + text)
  cache/               weather.md, ha-roster.md, ha-names.txt

Written guides: **`~/Documents/jarvis/`**.
  writer.lease         one Talk at a time
```

Generated stills: **`~/Pictures/jarvis/`**. Animations: **`~/Videos/jarvis/`**. Not the vault, not `~/.grok/sessions`.

## Cost

Talking like a receptionist uses **the SuperGrok allowance you already pay for**, plus free Edge TTS and local Whisper. There is no Grok Voice API meter. A few minutes of hello is negligible next to a Grok Build coding session. A hours-long Talk window is like leaving a Grok chat open: usage grows with **conversation history**, not with “having a GPU.”

Do **not** paste the entire memory vault into every hello. That would both cost more and make the desk slow.

## Ears (mic + STT)

Closed-lid laptop mics are not good enough for names like *Jak’s light*. Office Focusrite/condenser worked because the signal was clean. That is the product bar.

| Source | Use |
|---|---|
| **USB / Focusrite / Scarlett** | Best at the desk. Talk auto-picks names matching Focusrite, Scarlett, Yeti, Rode, … Pin with `~/.jarvis/mic.json` `{"device": "Focusrite"}` or `--mic Focusrite`. |
| **iPhone HUD** | Best “around the house” mic you already have. Safari hold-to-talk; Whisper still runs on the PC. |
| **Laptop analog (ALC…)** | Last resort. Lid closed = muffled, Whisper invents *Job is*, *jack knife*, *Jack’s night*. |

Software side (does not replace a real mic):

- Default STT is **base.en**, not tiny (choice 6 if you need speed).
- Whisper gets an `initial_prompt` / hotwords from the vault and HA entity names (`Jak`, `Jack`, `Lamp`, …).
- Too-quiet clips are rejected: “I didn’t catch that, sir.” instead of a hallucinated command.
- `vad_filter` on, no stitching onto the previous (wrong) sentence.

List devices: `./talk.sh` choice **m**, or `.venv/bin/python talk.py --list-mics`.

## Memory and persistence (today vs intended)

**Today:** Talk seeds `~/.jarvis/vault` on first run. The receptionist **loads only a small boot bundle** (`BOOT.md`, household, cached weather, house roster, reminders, today/yesterday stubs, never — capped at 4000 characters) into the system prompt. It still has **no tools**. A local intent gate enqueues search / remember / distill / house / imagine / docs / shell / forge; the host workshop is a **separate** grok process with web tools and Imagine, and a laptop worker has `shell` for this checkout. “Remember I…” files `people/_household.md`. “Remind me at 8pm…” files `vault/reminders.md`; if Talk is still running at that time, he will mention it. Each turn is appended to `logs/sessions/YYYY-MM-DD.jsonl`. On close, a **header-only** daily stub is written (no transcript dump) and a distill job files durable facts. Closing Talk does **not** delete the vault. The live Grok chat still dies with the process — that is intentional for speed.

**Intended:** extra notes read **on demand** (not stuffed into every hello). Laptop/office workshops for CAD. A Pi-side HA proxy so the office never holds the house token. The vault should get a **private git remote**. Apple Watch / HealthKit only via the iPhone writing samples into Supabase (or a Shortcut) — Jarvis cannot pair with the Watch.

## Home Assistant (same LAN)

The Pi is `http://homeassistant.local:8123`. That is enough from this laptop. There is **no** outside-network API key yet; you do not need one until Talk moves off this LAN. You **do** need a **long-lived access token** (HA local auth):

1. Open HA → profile (bottom left) → **Security** → **Long-lived access tokens** → Create Token (`jarvis`).
2. Save it as one line in `~/.jarvis/secrets/ha.token` (never the vault, never git).
3. Check from the **git repo** (not from `~/.jarvis`):

```bash
cd ~/jarvis    # or wherever you cloned this project
./ha.sh --check
./ha.sh --entities
```

Lights run immediately. Unlocks, garage, and doors: Jarvis asks, you say **yes**. Token is read only by the host workshop, never injected into the desk prompt.

Jarvis pulls the HA entity list (and room **areas**) so he does not need the exact `entity_id`. “Too bright in the living room” dims every light HA has in that room (here: Living Room Main Light **and** Lamp). On/off-only bulbs (garden) are switched off instead. “What lights do we have” lists them. A short roster is cached in `~/.jarvis/cache/ha-roster.md` so the desk knows the names; it still cannot flip switches. If the wording is too vague for the local parser, the workshop maps it against that roster with a short Grok call — still no token in the prompt.

Edit `~/.jarvis/vault/BOOT.md` (keep it small). Speech rules and “no tools” stay in code so a vault edit cannot give the desk a shell. One Talk at a time: `writer.lease` warns if another host already holds it.

```bash
python -m unittest discover -s tests
```

## The plan

**Decision: Iron Man-shaped Jarvis.** One presence you talk to — at home and later at the office — that runs the house, remembers the household in markdown, and uses this PC the way a skilled human would (Grok Build, Imagine, terminal, files). Not a receptionist who dispatches a mute labourer. Not a new Talk process on whatever laptop is open. Not a brain in another town.

**The movie line:** you never talk to a receptionist, and you never wait while he thinks in another room. You talk to Jarvis; some of him is busy; he can still answer. A single `grok agent` cannot chat and code at once, so the mouth is one process and the hands are others, with one persona and a shared brief. SuperGrok Heavy, Grok Build, and Imagine are in; wrapping Cursor or grok.com as a nested bot is out.

Standing test for every change: **does this move us toward a JARVIS-like system from the movies?** Accessories (Watch, Pi, extra caps) wait until that line is true. The phone already reaches Talk over Tailscale (`svc:jarvis`); that is one presence, not a second brain.

Tony’s JARVIS is one process with many endpoints (suit, phone, lab, house). That *is* doable. The dumb version was parking that process on the **office** Jetson while Home Assistant, the family, and the future room mics are at **home**. Always-on lives **at home**, next to the house.

### How close to the movie

| Movie JARVIS | This project | Honest limit |
|---|---|---|
| One presence, everywhere | **One Talk process** + many clients (phone, laptop HUD, office HUD, later room mics) | Not a new instance per machine. Live chat is one session. |
| Always on | Always-on **home** host (Pi 5 or Orin moved home) | If that box or home internet is down, Jarvis is down. |
| Talk in the workshop *and* at home | Tailscale: office/phone are mics + speakers + HUD | ~2s hellos, not overlapping banter while he is mid-sentence. Push-to-talk until wake word exists. |
| Runs the house | Home Assistant via a **local proxy** (token never in Jarvis) | Confirm unlocks/garage out loud. Not cinematic whole-house AI — scenes and entities you actually expose. |
| Knows the people | Markdown **vault** + later **speaker ID** → per-person vault | Saves *relevant* facts, not a transcript of every hour. A cold or two voices at once will fool ID. |
| Learns continuously | After turns, a worker **distills** into the vault (decisions, preferences, “never do X”). Boot file stays small | Will miss things nobody wrote down. Will not become omniscient. |
| Ceiling mics + “Jarvis, …” | **Later.** Local wake word on the home box, then the usual Whisper path | Far-field audio is the hard hardware problem. TV and kids will false-trigger. V1 stays hold-to-talk / phone HUD. |
| Suit, holograms, perfect hearing | HUD in a browser; speakers you already own | No suit. No AR table. Tiny.en will mangle names. Edge TTS will not sing. |
| Diagnoses and upgrades himself | **Self-maintenance job**: read this repo + logs + vault, propose a patch, run tests, ask you | Not unbounded recursive self-improvement. Talk does not edit the process that is speaking. You merge. |

That is about as close as SuperGrok + files + HA gets without pretending. The snappy mouth is the movie “yes, sir.” The vault is the movie “I remember.” The always-on home box is the movie “I’m here.” Background Grok Build / Imagine threads are the movie lab — same Jarvis, not a second staff.

### One brain, many faces

| Place | Machine | Role |
|---|---|---|
| **Home** | Always-on host (Pi 5, or **move the Orin here**) | **The** receptionist + host workshop + vault writer + HA client + future wake/mics |
| **Home** | Home Assistant | House. Token stays here. Same LAN as Talk. |
| **Home** | Laptop | Client (HUD/mic) + **workshop** for repos on that disk |
| **Office** | Windows PC | Client over Tailscale + **workshop** (Grok Build, Ableton, Fusion) |
| **Office** | Jetson, if it stays there | **Not** the receptionist. Spare Whisper/workshop only — or bring it home. |
| Pocket | Phone | Client: mic, speaker, HUD |

One live Talk. Starting Talk on a laptop because it is convenient is a **dev fallback**, not the product. Two Talks = two Jarvises.

### Always-on, house, memory

- The talking session stays **free** (~2s). Search, Imagine, vault writes, HA, Grok Build are **the other thread** — same Jarvis, shared brief.
- The live `grok agent` can stay warm (movie continuity). It must **not** grow forever: distill into markdown, keep the boot file tiny, or cost and latency explode. Closing Talk still must not delete the vault.
- HA is always reachable because Talk is in the **same house**. From the office you still talk to home Jarvis; lights still work. Confirm dangerous actions out loud.
- Speaker ID (later) loads that person’s vault. Family context is files, not “the model just knows.”
- Prefetch (weather, calendar, headlines) into a small cache so common facts need no job.

### Hands stay on the machine that has the files

Talking to Jarvis is not “run Grok Build on the always-on box.” Laptop/PC workshops **dial in**, advertise caps, pull jobs, run tools **locally**.

Jobs name a capability, not a machine. Dispatcher on the home host picks a live worker. Cloud tools (search, Imagine) run on the home host. Coding/CAD run only where advertised. Presence (which HUD you spoke from) is the default for coding. If nobody is signed in, say so — do not edit files on the Pi.

### Self-maintenance (not recursive god-mode)

Jarvis can work on **this repo** the same way he works on any other project: a workshop Grok Build job on the machine that has the checkout (usually the laptop). The receptionist never rewrites the Python that is currently talking.

What is actually useful (Iron Man “I’ve run a diagnostic”):

1. **Telemetry in the vault / logs** — latency per stage (already in Talk), failed STT, jobs that hung, “you asked for X and I could not.” Distill that the same way as household facts.
2. **He talks to you first** — “Whisper is slow on the laptop; we could try phone STT. Or I can add a test for the HUD phone path. Shall I?”
3. **Workshop patches on a branch**, runs tests, reports.
4. **You say yes.** Merge, then restart Talk. No auto-commit to `main`, no restarting the live desk from under itself.

What is **not** the plan: a loop that edits himself all night, measures, edits again, unsupervised. A small unittest suite already exists (`python3 -m unittest discover -s tests`). Without a human gate he will still break the 2s loop and burn SuperGrok. “Improve the codebase from how he is used” is **ops notes → proposal → patch → test → you.** Same Grok Build you already use; the receptionist is just how you ask.

Laptop `shell` workers exist: ask Talk to run the tests or patch this repo, then **you** merge and restart Talk. Until merge-on-yes exists, that human gate is the whole loop.

### Wake word and house mics (not v1)

V1 is push-to-talk and the phone HUD. Always-listening is a *later house feature*: wake phrase detected **locally** on the home box, then record and transcribe as today. Grok still never gets raw audio. This stays off until PTT, HA, and the vault work. It is not a forever ban; it is not day one.

### Build order

1. Keep the **mouth** free and snappy (no long tools on the talking session). Hands are other Grok processes with the full suite. One persona, shared brief.
2. Markdown vault + git + **distill** — boot bundle, session jsonl, daily stub, job board, host workshop (search / vault-write / distill / home / imagine / docs / forge) and laptop `shell` worker are in. On-demand vault reads are next.
3. Phone HUD: Tailscale Serve `svc:jarvis` (stable `https://jarvis.<tailnet>.ts.net/phone`). LAN IP is fallback only.
4. **HA on the LAN** — host workshop `home` cap talks to `homeassistant.local:8123`. Token in `~/.jarvis/secrets/ha.token`. Confirm unlocks/garage/doors out loud. A Pi-side proxy (token never leaves home) is what the office needs later; not required on this laptop.
5. **Always-on Talk at home** (Pi 5, or move the Orin). Host workshop already runs next to Talk; keep it there.
6. Workshop agents: home laptop, then office PC.
7. Speaker ID + per-person vaults.
8. House mics + local wake word.
9. Small **test suite** (bench, HUD smoke), then self-maintenance jobs on this repo (propose → test → you merge).
10. Emotion as a prompt hint. Per-app runners (Ableton, Fusion) last.

## Mobile (iPhone)

The iPhone **cannot** run `grok.exe` or CUDA Whisper. “Jarvis in my pocket” means:

1. **Remote to the home Talk host (the unique product)** — HUD in Safari, hold-to-talk, audio back. Always-on box must be up. Tailscale from the office or the road. Same SuperGrok, same vault.  
2. **Official Grok iOS app** — not this Jarvis (no HUD, no vault, no front-desk/workshop split).  
3. **Native app + xAI Voice API** — possible later, extra bill, still not Grok Build-on-disk unless a workshop is signed in on the machine that has the files.

### iPhone over Tailscale (the door)

One icon, any network the phone can reach Tailscale on (home Wi‑Fi, cellular, office). Not a LAN IP. Not Funnel (not on the public internet). Personal plan is free. Voice is device-to-device; Tailscale’s cloud is only how the phone finds the Talk host.

**Phone, once:** Tailscale app, same account as the Talk PC, VPN left on. Safari **`https://jarvis.tail9f6146.ts.net/phone`** → allow mic → Add to Home Screen. After that, tap the icon. Hold the gold button until **Release to send**. Reply plays on the phone.

**PC that runs Talk:** see `HANDOFF.md` (install Tailscale, tag `tag:jarvis`, one Talk, Approve the service host if asked). Talk advertises `svc:jarvis` while it is up. Stop Talk on the previous host first.

`127.0.0.1:8791` is the PC browser only. Same-LAN `https://<ip>:8791/phone` still works if Tailscale is down (Safari cert warning). The Home Screen icon is the `jarvis.…ts.net` URL.

## Single-board computers

Grok (the model) is in the cloud. The GPU on the 3060 is mainly for **Whisper**. Edge TTS is also cloud. A small always-on box can host Talk if it can run the **Grok Build CLI** (Linux ARM is published for Grok Build) and Python.

| Board | Verdict |
|---|---|
| **Pi 5 (8GB)** | Best cheap always-on host. CPU Whisper *tiny* may add ~0.5–1.5s; use **phone STT** to stay near 2–3s hellos. |
| **Jetson Orin Nano** | Fine if you want local NVIDIA Whisper in a small chassis. Overkill if the phone does STT. |
| **Jetson Nano (2019)** | Do not use. 4GB, old stack; it would fight you. |
| **Pi 4** | Too tight; hellos would feel like the slow spike days. |

Prove iPhone → this PC first, then move **Talk + host workshop** to an **always-on box at home** (Pi 5, or bring the Orin home). The office PC and the home laptop are **hands** (workshop agents) and HUD clients, not extra receptionists. The office Jetson is the wrong place for the house brain. Imagine and web search are cloud Grok tools; they do not need the 3060.

## Later extras

Roadmap is [The plan](#the-plan). Cosmetic after that:

- **Richer HUD** — optional custom face, waveform from live TTS PCM.
- **Kokoro or other local TTS** — offline mouth if Edge is unavailable.

## What this is not

- Not Claude Code / fullstack-agent (that stack needs Claude).
- Not Hermes / OpenClaw as a harness in the middle.
- Not a grok.com-hosted agent you instantiate in the website UI.
- Not a new receptionist on every laptop (that is a different Jarvis each time).
- Not always-listening **in v1** — hold-to-talk / phone until the house wake-word path exists.
- Not movie omniscience, a suit, or holographic CAD.
- Not unsupervised recursive self-improvement. He may propose patches to this repo; he may not merge them unattended.

## License

Personal project. Add a license file when you want to share or restrict use. Do not commit API keys, Home Assistant tokens, or vault notes that contain secrets.
