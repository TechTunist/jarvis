# Handoff — 24 Aug 2026

Private data lives in `~/.jarvis/` (not this git repo). Never commit `ha.token` or `forge.json`. Never paste them into chat.

**North star (every session):** read `AGENTS.md`. Before any work: does this move us toward movie JARVIS? You talk to Jarvis; some of him is busy; he can still answer. Mouth never waits on hands. Same persona. Full SuperGrok on the hands. Do not nest Cursor or grok.com.

**Restart Talk after pull.** Phone: close the Safari tab and open the `/phone` URL again so it is not a cached page.

## What this machine is

- **Laptop `xps`**, same LAN as Home Assistant (`homeassistant.local` → `192.168.0.113:8123`).
- Talk + workers run **here** (dev fallback). Product is still one always-on Jarvis **at home**.
- SuperGrok Heavy / Grok Build CLI / Imagine is the brain. The **talking** session stays free (no long tools). Hands are **other** `grok` processes with the full suite. One persona. No Grok router process.
- iPhone on **the same Wi‑Fi** is a remote mic + speaker. Use **`https://192.168.0.24:8791/phone`** (that is this laptop’s real address). Ignore `192.168.137.1` / `10.42.0.1` unless you actually start a hotspot.

## Just landed (this stretch)

- Mouth is grok-4.6 (medium). It reasons, then may emit `[hands:cap] task`. No Watcher/Brave/listings phrase router. `try_local` is gone.
- Regex left for house, hush, remember, and the older search/imagine/forge/code/docs fast paths that already worked.
- Hands Grok gets desktop env (snap PATH, DISPLAY) and must not claim unverified success.
- Intros only match household names. Restart Talk.

- **One persona.** Mouth and hands share Jarvis. No Grok router process. Unsure is conversation.
- Hands jobs write a `[hands]` brief. “How is it going?” is the mouth, in character.
- Fresh weather cache stays on the mouth. Cold search / Imagine / code still enqueue.
- Coding hands: full Grok Build minus Imagine, `grok-4.6` high effort, subagents on. Still no merge/push/Talk restart.
- Latest-wins mouth: only the last thing Matt said is acted on. New input **cuts** speech. Old jobs **keep running**.
- “Stop talking / be quiet / shut up” is **hush**, not the house.
- Reminders: near-duplicate 20:00 bullets collapse; one spoken line. Live vault already has a single “Check Jarvis codebase”.
- Phone HUD actually works: HTTPS, hold-to-talk, reply **on the phone**, laptop speakers **off** for that turn. Safari autoplay: silent loop from finger-down. ffmpeg `-nostdin` so PTT stdin swallow does not break decode.
- Desktop HUD is local **three.js** (`receptionist/hud/`, vendored). **F** fullscreen.
- House job results spoken **once** (wait vs drain used to double).
- Home key no longer dumps escape junk into the Talk TTY.
- Voice default **en-GB-ThomasNeural** (`-2%` / `+4Hz`). Not a celebrity clone.
- Desk prompt: answer what he said. No “desk is awake / at your service”.
- BearJacked read-only path is **code-complete**. Login is not: add `email` + `password` to `~/.jarvis/secrets/forge.json` (url/anon already there, chmod 600).

## Working today

Host caps: `search`, `vault-write`, `distill`, `home`, `imagine`, `docs`, `forge`. Laptop cap: `shell`.

| You say | What happens |
|---|---|
| Hello / banter / engineering talk | Mouth. grok-4.6, no long tools. No self-advertising. |
| Lights / dark / glow / gloomy | HA REST. Unlock/garage/door wait for **yes**. |
| Weather (cache under 6h) | Mouth from `~/.jarvis/cache/weather.md`. |
| Look up / cold weather | Hands web search, then he speaks the answer. |
| Remember / remind me at 8pm | Vault. Duplicates of the same daily reminder do not stack. |
| Draw / animate / PDF / spec | Ack, then files in Pictures / Videos / Documents. |
| Run the tests / patch / implement | Hands, full Grok Build. Branch `jarvis/workshop-*`. No merge, no push, no Talk restart. |
| How is the work going? | Mouth reads the `[hands]` brief. |
| Last workout / what did I lift / my weight | `forge` → Supabase (needs login in secrets). Read-only. |
| Stop talking | Hush. Cuts audio. Background jobs may finish silently. |
| New command while a job runs | Mouth follows you. Job is **not** cancelled. |
| Phone hold-to-talk | Mic + speaker on the phone. Brain still this Talk process. |

If he says he hasn't got hands for that, no live worker has that cap. Logs: `~/.jarvis/logs/sessions/`, `~/.jarvis/jobs/`.

## How to run

```bash
cd ~/jarvis
git pull
cd receptionist
./talk.sh          # 3 = Home + base.en + Thomas + HUD
```

HA: `./ha.sh --check` from the **repo**. Tests: `python3 -m unittest discover -s tests` (no Grok, no GPU, no token).

Phone: same Wi‑Fi as the XPS → Safari `https://192.168.0.24:8791/phone` → Advanced → Visit → allow mic → hold until **Release to send**.

## Secrets (never git)

| File | What |
|---|---|
| `~/.jarvis/secrets/ha.token` | HA long-lived token |
| `~/.jarvis/secrets/forge.json` | `url`, `anon_key`, **`email`, `password` still needed** |

## Next — movie test first

Mouth and hands are one Jarvis in code. Restart Talk to pick it up. Do not add Forge/Watch/Pi/Tailscale until you have used this for a real conversation + a long job.

1. **Restart Talk** (`./talk.sh` choice 3 = grok-4.6). Close the Safari `/phone` tab if you use it.
2. Try: hello → a long job (draw / tests) → “how is it going?” / weather / a joke while it runs. Mouth should stay free. Same voice. No “workshop.”
3. **Forge login** in `forge.json` when you want the training log. Watch / Pi / Tailscale still later.

**Later (still movie):** Apple Watch via iPhone → same Supabase (Jarvis cannot pair with the Watch), always-on home host (Pi 5), merge-on-yes, Tailscale, calendar file.

## Known nits

- Talk on this laptop is still the **dev fallback**, not the product host.
- SuperGrok **ZDR** blocks Imagine *video* until `/privacy` is off or S3 is set. Stills work.
- Choice 3 is grok-4.6 (mouth low effort; hands high on coding jobs).
- Wayland: Home PTT often needs Xorg; phone HUD otherwise.
- Thomas is a composed British male, not Paul Bettany.
- Two warm Grok processes (desk + router). Watch `[route] Nms`.
- Distill quality depends on Grok.
- Do not start a second Talk. Stills `~/Pictures/jarvis`, animations `~/Videos/jarvis`.
