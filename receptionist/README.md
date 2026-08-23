# Receptionist (Talk)

Voice loop + HUD for Jarvis. Tool-free on purpose (~2s). A local intent gate sends search/remember/house commands to a host workshop; the desk never gets tools. HA token lives in `~/.jarvis/secrets`, not the vault. Memory is `~/.jarvis/vault` (boot only in the prompt). The product is one always-on receptionist **at home**; this machine is a client and/or workshop, not a second Jarvis. See the **[root README](../README.md)** (The plan).

Windows: `talk.cmd`  
Ubuntu: `./talk.sh`

Option **3** is the daily path: Home key, Whisper, grok-4.5, British neural voice, Iron Man HUD.
