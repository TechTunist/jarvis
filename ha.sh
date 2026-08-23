#!/usr/bin/env bash
# HA check from anywhere. This is the git repo, not ~/.jarvis.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m memory.ha "$@"
