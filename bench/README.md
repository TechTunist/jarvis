# Bench

A millimetre timber model Jarvis can drive. You can still orbit it in a browser.

Not Fusion. Boards as boxes, for now. Bolts later.

```bash
python3 bench/bench.py          # http://127.0.0.1:8770/
```

Talk: “create a 3d model of a bit of wood 1600 by 70 by 15 millimetres.” Mouth acks; hands POST the board; the page shows it.

API: `GET /api/scene`, `POST /api/parts` `{"kind":"board","length_mm":1600,"width_mm":70,"thickness_mm":15}`, `POST /api/clear`.
