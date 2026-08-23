#!/usr/bin/env bash
# Linux/macOS launcher (Windows: talk.cmd).
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Create the venv first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
echo "Jarvis receptionist"
echo "  1 typed, no voice"
echo "  2 typed + British neural voice"
echo "  3 hold Home (base whisper — more accurate) + British neural"
echo "  4 hold Home, grok-4.6 + base whisper"
echo "  5 hold Home + offline espeak"
echo "  6 hold Home, tiny whisper (faster, sloppier)"
echo "  m list microphones"
read -r -p "choice: " c
case "$c" in
  1) exec "$PY" talk.py --brain agent --model grok-4.5 --stt none --tts none ;;
  2) exec "$PY" talk.py --brain agent --model grok-4.5 --stt none --tts edge ;;
  3) exec "$PY" talk.py --brain agent --model grok-4.5 --stt base --tts edge ;;
  4) exec "$PY" talk.py --brain agent --model grok-4.6 --stt base --tts edge ;;
  5) exec "$PY" talk.py --brain agent --model grok-4.5 --stt base --tts sapi ;;
  6) exec "$PY" talk.py --brain agent --model grok-4.5 --stt tiny --tts edge ;;
  m|M) exec "$PY" talk.py --list-mics ;;
  *) echo "unknown choice"; exit 1 ;;
esac
