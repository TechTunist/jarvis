# Secrets (not the vault)

This folder is **not** git. Never copy it into `vault/` or this repo.

## Home Assistant (LAN)

Talk on this laptop can reach `http://homeassistant.local:8123` on the same network.
The REST API still needs a **long-lived access token** (that is not an
outside-network API key; it is local auth).

1. Open Home Assistant in a browser.
2. Bottom-left **profile** (your user) → **Security**.
3. **Long-lived access tokens** → Create Token. Name it `jarvis`.
4. Copy the token **once** (HA will not show it again).
5. Save it as a single line:

```
~/.jarvis/secrets/ha.token
```

Optional URL override (default is `http://homeassistant.local:8123`):

```
~/.jarvis/secrets/ha.json
{"url": "http://homeassistant.local:8123"}
```

Or env: `JARVIS_HA_TOKEN`, `JARVIS_HA_URL`.

Check from the **git repo** (`~/jarvis`), not from this secrets folder (`memory` is not installed globally):

```
cd ~/jarvis
./ha.sh --check
./ha.sh --entities
```

Unlocks, garage, and doors require a spoken **yes** before they run. Lights do not.

A later Pi-side proxy is how the office talks to the house without this token
leaving home. Same LAN does not need that yet.
