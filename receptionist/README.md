# Receptionist (Talk)

Voice loop + HUD for Jarvis. The talking Grok session stays free so the mouth never waits on long work; coding, Imagine, and cold search run on other Grok processes as the **same** Jarvis. Secrets live in `~/.jarvis/secrets` (HA token, BearJacked login), not the vault. Generated stills live in `~/Pictures/jarvis`; animations in `~/Videos/jarvis`. Not this repo, not grok sessions. Memory is `~/.jarvis/vault` (boot only in the prompt). The product is one always-on presence **at home**; this machine is a client and/or the hands, not a second Jarvis. North star: **[AGENTS.md](../AGENTS.md)**. Plan: **[root README](../README.md)**.

Windows: `talk.cmd`  
Ubuntu: `./talk.sh`

Option **3** is the daily path: Home key, Whisper, grok-4.6, Thomas neural voice, three.js HUD (`https://127.0.0.1:8791/`, **F** fullscreen). iPhone: Tailscale on, then **`https://jarvis.tail9f6146.ts.net/phone`** (Talk advertises `svc:jarvis`; not `127.0.0.1`, not a LAN IP). How to put Talk on another PC: **[HANDOFF.md](../HANDOFF.md)**.
