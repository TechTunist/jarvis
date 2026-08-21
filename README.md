# Jarvis

A **Grok-native desktop receptionist**: hold a key, speak, get a fast British reply, with an Iron Man–style HUD. Built to stay snappy on small talk and to grow a **file-based memory** so it knows you better over time — without stuffing every conversation into every hello.

This is **not** the Grok iOS app and **not** a grok.com cloud agent. Talk launches a **local** `grok agent` process (Grok Build CLI) that uses your SuperGrok login. The model runs on xAI’s servers; the dock (mic, Whisper, HUD, personality files) runs on hardware you control.

## Existing features

- **Push-to-talk** — hold **Home**, speak, release. Mic is closed otherwise.
- **Local ears** — `faster-whisper` `tiny.en` on NVIDIA CUDA when available, CPU fallback.
- **Brain** — warm `grok agent` (default **grok-4.5**, low effort). Same SuperGrok account as Grok Build. Tools stripped on this session so the front desk answers instead of becoming a coding agent.
- **Mouth** — Microsoft Edge neural TTS (`en-GB-RyanNeural`), streamed to speakers with a short silence preroll so the first word is not clipped. Offline fallback: Windows SAPI.
- **HUD** — fullscreen J.A.R.V.I.S. rings in the browser (`http://127.0.0.1:8791/`). States: idle / listening / thinking / speaking. Press **F** for fullscreen.
- **Single instance** — starting Talk stops a previous Talk window so you do not get two voices.
- **No extra Grok Voice bill** — Whisper is local; Ryan is Edge TTS; Grok is SuperGrok.

### How a turn works

1. Home down → record locally.  
2. Home up → Whisper turns audio into text on this machine. Grok never hears the raw voice.  
3. Text is sent into the already-running `grok agent` process.  
4. First short sentence is spoken as soon as audio chunks exist.  
5. HUD follows the same states.

This window (Grok Build while developing) is a **separate** `grok.exe` from Jarvis. Close Talk and Jarvis’s agent dies; this chat does not.

## Quick start (Windows)

You need: [Grok Build CLI](https://x.ai/build) (`grok login`), Python 3.12, a mic and speakers. An NVIDIA GPU is optional but faster for Whisper.

```bat
cd receptionist
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
talk.cmd
```

Choose **3** for hold-Home + British neural + HUD.

| Choice | What it does |
|---|---|
| 1 | Typed only |
| 2 | Typed + British neural |
| 3 | Home key + Whisper + British neural + HUD |
| 4 | Same as 3 with **grok-4.6** |
| 5 | Home key + old Windows SAPI (offline mouth) |

Useful flags:

```bat
.venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt tiny --tts edge
.venv\Scripts\python talk.py --no-hud
.venv\Scripts\python talk.py --voice en-GB-ThomasNeural
```

First hello after launch is slower; the brain warms during “Jarvis online.” Simple chat should land near **~2s to first word** after you release Home (hold time is not wait time). Asking the desk to search or read files is **not** this spike — those jobs belong on a workshop process later.

## Repository layout

```
receptionist/
  talk.py          Voice loop, PTT, Grok ACP client, TTS
  hud_server.py    Local HUD HTTP server
  hud/index.html   Iron Man–style visualisation
  JARVIS.md        Short personality (boot notes)
  talk.cmd         Windows menu
  requirements.txt
```

Runtime junk (`talk.pid`, `agent.stderr.log`, `.venv`) is gitignored.

## Cost

Talking like a receptionist uses **the SuperGrok allowance you already pay for**, plus free Edge TTS and local Whisper. There is no Grok Voice API meter. A few minutes of hello is negligible next to a Grok Build coding session. A hours-long Talk window is like leaving a Grok chat open: usage grows with **conversation history**, not with “having a GPU.”

Do **not** paste the entire memory vault into every hello. That would both cost more and make the desk slow.

## Memory and persistence (today vs intended)

**Today:** personality is a short system prompt plus `JARVIS.md`. The live Grok process forgets when Talk closes. That is intentional for speed.

**Intended:** memory is **markdown on disk**, not an infinite chat.

- A small **boot file** (who Jarvis is, how to talk to you, path to the vault).
- A **vault** of notes: you, projects, decisions, daily logs, “never do X.”
- Each hello loads only the boot file (and maybe yesterday’s line). Extra notes are read **on demand**.
- After a session, Jarvis **writes** what changed. The pile grows; tokens per hello stay roughly flat.

Closing Talk must not delete the vault. The window is the phone call; the folder is the filing cabinet.

## Persistence across PC, Pi, Jetson, and iPhone

You do **not** need a mystery “cloud brain.” You need **one copy of the files** every host can read, and **one live Talk process** (or a clearly primary one) so two desks do not edit the vault at once.

Recommended source of truth:

1. **This GitHub repo** for code + `JARVIS.md` / personality templates.  
2. **A private GitHub repo (or a private folder in this repo later)** for the vault: profile, projects, daily notes, interaction logs. Plain markdown; no secrets in git (passwords stay in a password manager).  
3. **One always-on host** (home PC or Pi 5 / Orin) runs Talk and `grok agent`.  
4. **Other devices are clients or clones**, not a second independent Jarvis.

| Device | Role | What syncs |
|---|---|---|
| Windows PC | Workshop + optional Talk | Git pull/push vault; local `grok` |
| Pi 5 / Orin Nano | Always-on receptionist | Same git vault; local `grok` CLI (Linux ARM) |
| iPhone | Eyes / ears / mouth | No vault clone required; talks **to the host** over the LAN or Tailscale |

**Do not sync** `~/.grok/sessions/` between machines (session logs, machine-specific). **Do sync** vault markdown and `JARVIS.md`.

If two hosts are up, pick a **primary** (the Pi at home). The PC is for Grok Build work and, when you are at the desk, Talk can run there instead — not both writing memory at once.

iCloud/Dropbox on the vault folder can work for a single writer. Git is better: history, conflict visibility, and the same “notes as memory” model on every OS. Tailscale (or similar) is how the phone reaches the host without opening router ports.

Phone STT (Apple speech) can replace CUDA Whisper when you are mobile; Grok still runs on the host. The HUD is already a webpage — open it on the iPhone when the host is reachable.

## Mobile (iPhone)

The iPhone **cannot** run `grok.exe` or CUDA Whisper. “Jarvis in my pocket” means:

1. **Remote to the home host (the unique product)** — HUD in Safari, hold-to-talk, audio back. Host must be on. Tailscale for away-from-home. Same SuperGrok, same vault.  
2. **Official Grok iOS app** — not this Jarvis (no HUD, no vault, no front-desk/workshop split).  
3. **Native app + xAI Voice API** — possible later, extra bill, still not Grok Build-on-disk unless workers stay at home.

### iPhone on the PC Wi‑Fi hotspot (works now)

The PC can stay on **ethernet**. Turn on **Windows Mobile Hotspot**, join it from the iPhone, then in Safari open the `https://192.168.137.1:8791/phone` URL Talk prints (the hotspot address is often `192.168.137.1`).

Safari will warn about the self-signed certificate: **Advanced → Visit this website**. Allow the microphone. Hold the gold button, speak, release. Audio comes back on the phone; the HUD follows listening / thinking / speaking.

The PC must be running Talk. Whisper and Grok still run on the PC; the phone is only mic, speaker, and face.

## Single-board computers

Grok (the model) is in the cloud. The GPU on the 3060 is mainly for **Whisper**. Edge TTS is also cloud. A small always-on box can host Talk if it can run the **Grok Build CLI** (Linux ARM is published for Grok Build) and Python.

| Board | Verdict |
|---|---|
| **Pi 5 (8GB)** | Best cheap always-on host. CPU Whisper *tiny* may add ~0.5–1.5s; use **phone STT** to stay near 2–3s hellos. |
| **Jetson Orin Nano** | Fine if you want local NVIDIA Whisper in a small chassis. Overkill if the phone does STT. |
| **Jetson Nano (2019)** | Do not use. 4GB, old stack; it would fight you. |
| **Pi 4** | Too tight; hellos would feel like the slow spike days. |

Prove iPhone → this PC first, then move Talk to a Pi 5 / Orin left on at home. Keep the Windows PC as the **workshop** (Grok Build, Imagine, heavy files).

## Future features

- **Markdown memory vault** — profile, projects, daily notes, jobs; boot small, fetch on demand.  
- **Workshop process** — Grok Build / grok-4.6 / Imagine in the **background**; receptionist only starts/checks jobs. “Make an animation” while you still chat. Artifacts land in a local `out/` folder.  
- **Job board** — `jobs/<id>.jsonl` so “what’s happening?” is a file read, including a short view of worker reasoning.  
- **Home Assistant** — lights/scenes as a **fast** desk tool, not a coding agent turn. Confirm unlocks/garage out loud.  
- **iPhone client** — PTT + HUD over LAN/Tailscale.  
- **Always-on host** — Pi 5 or Orin Nano running Talk; PC for heavy work.  
- **Synced vault** — private git (or one-writer Tailscale folder) so personality and projects follow you across devices.  
- **Richer HUD** — optional custom face, waveform from live TTS PCM.  
- **Kokoro or other local TTS** — offline mouth if Edge is unavailable.

## What this is not

- Not Claude Code / fullstack-agent (that stack needs Claude).  
- Not Hermes / OpenClaw as a harness in the middle.  
- Not an always-listening wake-word bug.  
- Not a grok.com-hosted agent you instantiate in the website UI.

## License

Personal project. Add a license file when you want to share or restrict use. Do not commit API keys, Home Assistant tokens, or vault notes that contain secrets.
