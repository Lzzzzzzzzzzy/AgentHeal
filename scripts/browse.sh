#!/usr/bin/env bash
# Browse the sandbox web by hand: starts the gym for one episode and opens a Chromium window through it.
# Needs a graphical desktop session (or X forwarding). Run as a normal user:
#   bash scripts/browse.sh                       random episode
#   bash scripts/browse.sh F1-ACA-024-W1a        a specific episode
#   bash scripts/browse.sh --family F4 --world W2 --show-answer
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
exec "$PY" -m agentheal browse "$@"
