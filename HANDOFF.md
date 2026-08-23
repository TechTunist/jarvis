# Handoff — 23 Aug 2026 (going to bed)

Where Jarvis is, what landed tonight, what to do next. Private data lives in `~/.jarvis/` (not this git repo). The HA token is `~/.jarvis/secrets/ha.token` — never commit it, never paste it into chat.

## What this machine is

- **Laptop `xps`**, same LAN as Home Assistant (`homeassistant.local` → `192.168.0.113:8123`).
- Talk + host workshop run **here** (dev fallback). Product plan is still one always-on receptionist **at home**.
- SuperGrok / Grok Build CLI is the brain. Desk session has **no tools**.

## Working today (restart Talk after pull)

Host workshop caps: `search`, `vault-write`, `distill`, `home`.

| You say | What happens |
|---|---|
| Hello / banter | Tool-free `grok agent` (~2s path) |
| Weather / look up | Workshop `grok -p` with web search; weather cached in `~/.jarvis/cache/weather.md` |
| Remember / remind me at 8pm | Vault `people/` or `reminders.md`. Daily 20:00 reminder is already filed: check Jarvis codebase |
| Kitchen / lamp / entrance / living room lights | HA REST. `light.lamp` matches “the lamp” |
| Jack’s / Jak’s / Jacks light | Fuzzy match to `light.jaks_light` (“Jak’s Light”) |
| Unlock / garage / door | Spoken **yes** before it runs |
| Session close | Header-only daily stub + distill job (worker survives Ctrl-C; leftover jobs finish in-process) |

**Not wired:** Imagine, Grok Build / `shell` workshops, HA token proxy for off-LAN, wake word, always-on home host.

If the desk says “workbench is not connected”, that usually means the **intent gate missed the utterance** (STT garbage) and the tool-free receptionist answered. The workshop can still be up. Check `~/.jarvis/logs/sessions/` and `~/.jarvis/jobs/`.

## Hardware / STT

**Headphones with a mic vastly improved STT at home.** That path is good enough; do not spend tomorrow on mics.

Closed-lid XPS analog (ALC3271) is still poor. Office Focusrite + condenser remains the gold standard. Phone HUD is the no-headset option. `--list-mics`, `~/.jarvis/mic.json`, base.en, and Whisper name hints are already in.

## How to run

```bash
cd ~/jarvis
git pull
cd receptionist
./talk.sh          # 3 = base whisper + Edge TTS + HUD
# or: .venv/bin/python talk.py --brain agent --model grok-4.5 --stt base --tts edge
```

HA check (from **repo**, not from `~/.jarvis/secrets`):

```bash
cd ~/jarvis
./ha.sh --check
./ha.sh --entities
```

Tests (no Grok, no GPU, no token):

```bash
cd ~/jarvis
python3 -m unittest discover -s tests
```

## Layout

```
receptionist/talk.py     Desk: PTT, Whisper, HUD, intent gate, spawn worker
memory/worker.py         Host workshop (search, vault-write, distill, home)
memory/ha.py             HA REST; token only from ~/.jarvis/secrets
memory/ears.py           Mic pick, levels, Whisper vocab
memory/intent.py         Local classifier (no extra Grok call)
~/.jarvis/vault/         Markdown memory (private git intended)
~/.jarvis/secrets/       ha.token — chmod 600
```

## Tomorrow — suggested order

1. **Imagine on the host workshop.** New cap `imagine`. Desk stays tool-free: “generate / imagine / make an image of …” enqueues; the host worker runs cloud Grok Imagine (no 3060). Speak a short ack, then say when the file is ready (path under `~/.jarvis/` or a project folder — not in git). Confirm you are not putting generated blobs in this repo.
2. **Grok Build `shell` workshop on this laptop.** Separate worker that advertises `shell` (and maybe `repo`) for the checkout on disk. “Run the tests in this repo” / “patch X” enqueues here, not on the desk and not on a Pi with no files. Human gate before merge; Talk never rewrites the process that is speaking.
3. **Always-on receptionist at home (Pi 5).** One Talk next to HA. This laptop becomes a HUD/mic client + `shell` workshop. HA token stays on the home LAN (Pi-side proxy when the office needs it). Wake word still later.

Do not put the HA token in `/home/matt/jarvis`. Do not start a second Talk.

## Known nits

- README still says “there are no tests yet” in the self-maintenance section; `tests/` exists (unittest).
- Distill quality depends on Grok; recap is no longer dumped into boot.
- `talk.py` default `--model` is grok-4.6; launchers mostly use 4.5.
- Wayland: Home-key PTT often needs Xorg; phone HUD / typed mode otherwise.
