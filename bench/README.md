# Bench

A millimetre timber model Jarvis can drive. You can still orbit, pan, and zoom it in a browser.

Not Fusion. Boards as boxes, for now. Bolts later.

```bash
python3 bench/bench.py          # http://127.0.0.1:8770/
```

Talk: “create a 3d model of a bit of wood 1600 by 70 by 15 millimetres.” Mouth acks; hands POST the board; the page shows it.

A pile plus a site is a layout, not a single add. Give the stock (e.g. ten 1600×70×15), the alley width, the length along the alley, and the midpoint headroom. Bench consumes the pile, splices posts if they are short, cuts rafters so they stay inside the alley, and records whether the midpoint underside and the span pass.

Ops: add, duplicate, move, rotate/stand, resize, delete, clear, set_stock, set_site, set_hints, design, camera/look_at, pan, frame, save, new, load, list_projects, set_look, wire, unwire, set_wires, clear_wires.

Kit look: `{"op":"set_look","n":3,"finish":"devkit"}` (abs, lid, devkit, pcb, bms, cell, mems, switch, led, usb, brick). Colour optional `#1a1a1e`. Role still implies a finish if none is set. Timber stays wood.

Wires: `{"op":"wire","from":"p3","to":"p6","net":"I2S SCK","from_pin":"GPIO5","to_pin":"SCK"}`. `from`/`to` are part id, name, or n. Colour optional. `unwire` `{n:1}` or `{id:"w1"}`. `clear_wires`. Jumpers on the millimetre bench, not copper traces.

Projects: the live scene is one job. `{"op":"save","as":"pergola"}` writes it aside; `{"op":"new"}` starts empty (and saves the current one first if it has work); `{"op":"load","name":"pergola"}` or `"previous"` / `"first"` brings it back. GET `/api/projects`. Say “save this as the pergola and start a new project”, then “go back to the pergola”.

`POST /api/ops` `{"ops":[{"op":"duplicate","n":1,"dy_mm":900}]}`  
Also `POST /api/parts`, `/orient`, `/delete`, `/move`, `/resize`, `/duplicate`, `/clear`, `/camera`.

View: left-drag orbit, right-drag or Shift-drag pan, scroll zoom. Look-at is millimetres (x along, y across, z up) on GET `/api/scene` as `camera`. Jarvis: `{"op":"pan","dx_mm":200}` or `{"op":"look_at","n":3}` or `{"op":"frame"}`.

x along, z up, y across. Jarvis should not open a new tab on every command.
