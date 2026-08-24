# Handoff — 24 Aug 2026 (evening)

Where Jarvis is, what landed this stretch, what to do next. Private data lives in `~/.jarvis/` (not this git repo). Never commit `ha.token` or `forge.json`. Never paste them into chat.

**Restart Talk after pull.** Phone: close the Safari tab and open the `/phone` URL again so it is not a cached page.

## What this machine is

- **Laptop `xps`**, same LAN as Home Assistant (`homeassistant.local` → `192.168.0.113:8123`).
- Talk + host workshop + `shell` workshop run **here** (dev fallback). Product is still one always-on receptionist **at home**.
- SuperGrok / Grok Build CLI is the brain. Desk session has **no tools**.
- iPhone on **the same Wi‑Fi** is a remote mic + speaker. Use **`https://192.168.0.24:8791/phone`** (that is this laptop’s real address). Ignore `192.168.137.1` / `10.42.0.1` unless you actually start a hotspot.

## Just landed (this stretch)

- Semantic **router** (warm `grok agent`, JSON caps) after a regex fast path. Mixed imagine+docs jobs. Desk stays tool-free.
- Workshops: `search`, `vault-write`, `distill`, `home`, `imagine`, `docs`, **`forge`**, plus a **separate laptop `shell`** worker.
- Latest-wins mouth: only the last thing Matt said is acted on. New input **cuts** speech. Old workshop jobs **keep running** but stay silent unless he asked for status.
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
| Hello / banter | Tool-free warm desk. No self-advertising. |
| Lights / dark / Jak’s light | HA REST. Areas for living room. Unlock/garage/door wait for **yes**. |
| Weather / look up | Workshop web search. Weather cache `~/.jarvis/cache/weather.md`. |
| Remember / remind me at 8pm | Vault. Duplicates of the same daily reminder do not stack. |
| Draw / animate / PDF / spec | Ack, then files in Pictures / Videos / Documents. Assembly ≠ orbit of a sealed box. |
| Run the tests / patch this repo | `shell` worker. Branch `jarvis/workshop-*`. No merge, no push, no Talk restart. |
| Last workout / what did I lift / my weight | `forge` → Supabase (needs login in secrets). Read-only. |
| Stop talking | Hush. Cuts audio. Background jobs may finish silently. |
| New command while a job runs | Mouth follows you. Workshop job is **not** cancelled. Status questions still get the result spoken. |
| Phone hold-to-talk | Mic + speaker on the phone. Brain still this Talk process. |

If chat answers a house request, the router called it chat. If he says the workbench is not connected, no live worker has that cap. Logs: `~/.jarvis/logs/sessions/`, `~/.jarvis/jobs/`.

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

## Tomorrow — suggested order

1. **Finish Forge login.** Put BearJacked email/password in `forge.json`, chmod 600, restart Talk, ask “how was my last workout”. If RLS/login fails, the spoken line will say so — do not put the password in chat.
2. **Apple Watch (not started).** Watch → Health on the iPhone only. Jarvis cannot pair with the Watch. Shortest path: iPhone Shortcut (or Health Auto Export) POSTs HR/HRV/sleep into a Supabase table on the **same** BearJacked project; Jarvis reads it like `forge`. BearJacked is a **web** app — it cannot read HealthKit until there is a native/Capacitor shell. Do not try to Bluetooth the Watch from the XPS.
3. **Always-on Talk at home (Pi 5).** This laptop becomes HUD/mic + `shell`. HA token stays on the home LAN. Wake word later.
4. **Merge-on-yes** for `jarvis/workshop-*`. Still no auto-commit to `main`.
5. **Tailscale** so the phone works off this Wi‑Fi.

## Known nits

- Talk on this laptop is still the **dev fallback**, not the product host.
- SuperGrok **ZDR** blocks Imagine *video* until `/privacy` is off or S3 is set. Stills work.
- `talk.py` default `--model` is grok-4.6; launchers use 4.5.
- Wayland: Home PTT often needs Xorg; phone HUD otherwise.
- Thomas is a composed British male, not Paul Bettany.
- Two warm Grok processes (desk + router). Watch `[route] Nms`.
- Distill quality depends on Grok.
- Do not start a second Talk. Stills `~/Pictures/jarvis`, animations `~/Videos/jarvis`.
