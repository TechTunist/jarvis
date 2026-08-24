# Receptionist (Talk)

Voice loop + HUD for Jarvis. Tool-free on purpose (~2s). A local intent gate sends search/remember/house/imagine/docs/shell/forge commands to workshops; the desk never gets tools. Secrets live in `~/.jarvis/secrets` (HA token, BearJacked login), not the vault. Generated stills live in `~/Pictures/jarvis`; animations in `~/Videos/jarvis`. Not this repo, not grok sessions. Memory is `~/.jarvis/vault` (boot only in the prompt). The product is one always-on receptionist **at home**; this machine is a client and/or workshop, not a second Jarvis. See the **[root README](../README.md)** (The plan).

Windows: `talk.cmd`  
Ubuntu: `./talk.sh`

Option **3** is the daily path: Home key, Whisper, grok-4.5, Thomas neural voice, three.js HUD (`https://127.0.0.1:8791/`, **F** fullscreen). iPhone: the **LAN** `https://…:8791/phone` URL Talk prints (not `127.0.0.1`).
