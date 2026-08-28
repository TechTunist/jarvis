# Bench

A millimetre timber model Jarvis can drive. You can still orbit it in a browser.

Not Fusion. Boards as boxes, for now. Bolts later.

```bash
python3 bench/bench.py          # http://127.0.0.1:8770/
```

Talk: “create a 3d model of a bit of wood 1600 by 70 by 15 millimetres.” Mouth acks; hands POST the board; the page shows it.

Ops: add, duplicate, move, rotate/stand, resize, delete, clear.

`POST /api/ops` `{"ops":[{"op":"duplicate","n":1,"dy_mm":900}]}`  
Also `POST /api/parts`, `/orient`, `/delete`, `/move`, `/resize`, `/duplicate`, `/clear`.

x along, z up, y across. Jarvis should not open a new tab on every command.
