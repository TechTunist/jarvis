# Room node

Cloneable wireless house mic so Jarvis can hear voice commands from other rooms. Electronics on the millimetre bench.

- MCU: official ESP32-S3-DevKitC-1 (~63×25 mm, published drawing). Confirm if the board on the desk is a clone.
- Kit on file: DevKitC-1, MEMS capsule, 18650 cell, TP4056/BMS, USB-C, mute switch, status LED, simple enclosure.
- Power: reclaimed vape cells through a BMS; USB-C is charge. Mute kills the link; LED shows state.
- Host: MQTT or WebSocket back to the Talk machine.
- Wiring (feasibility, not a PCB): USB-C PSU → panel → BMS IN+; cell B+/B− on the BMS; BMS 5V/GND to the DevKit; MEMS I2S (3V3, GND, SCK, WS, SD) to the S3; mute and LED on GPIOs. Draw those leads on the bench with `wire_kit` when asked to show them.
- Bench snapshot: `electronics` under `~/.jarvis/bench/projects/`. Still millimetre boxes with kit colours, not STEP meshes.
- If they start electronics and have not named parts, ask what it is for and what they have. Do not write a PDF for “what’s on file.”
