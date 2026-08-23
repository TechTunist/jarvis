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

## Hardware / STT (painful tonight)

Closed-lid XPS analog mic (ALC3271) is not good enough. Office Focusrite + condenser was fine.

Tonight’s software (does **not** replace a real mic):

- Default STT is **base.en** (talk.sh choice **3**). Choice **6** is tiny (faster, sloppier).
- Auto-prefer USB/Focusrite/Scarlett/Yeti. Pin: `~/.jarvis/mic.json` `{"device": "Focusrite"}` or `--mic Focusrite`.
- `./talk.sh` → **m** or `talk.py --list-mics`.
- Whisper `initial_prompt` / hotwords from vault + HA names (`~/.jarvis/cache/ha-names.txt` after the first house command).
- Too-quiet clips: “I didn’t catch that, sir.” instead of a hallucinated command.

**Use the iPhone HUD** when the lid is closed. Plug the Focusrite in at the desk.

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

1. **Mic that actually works at home** — USB/Focusrite on the XPS, or phone HUD as the daily path. Confirm `talk.py --list-mics` shows the interface, not only ALC analog.
2. **Prove STT on Jak’s light / lamp / living room** with that mic + **base** Whisper. If names still die, we still have a signal problem, not a classifier problem.
3. **Imagine + Grok Build workshops** — next software slice. New caps:
   - `imagine` on the **host** workshop (cloud Grok tools; no 3060 required).
   - `shell` on **this laptop’s** workshop (Grok Build in the repo checkout). Desk still has no tools; it only enqueues.
4. Later: Pi-side HA proxy (token never leaves home), always-on Talk at home, wake word.

Do not put the HA token in `/home/matt/jarvis`. Do not start a second Talk.

## Known nits

- README still says “there are no tests yet” in the self-maintenance section; `tests/` exists (unittest).
- Distill quality depends on Grok; recap is no longer dumped into boot.
- `talk.py` default `--model` is grok-4.6; launchers mostly use 4.5.
- Wayland: Home-key PTT often needs Xorg; phone HUD / typed mode otherwise.
