#!/usr/bin/env bash
# ReAct on the counterfactual sandbox and the real-web barrier replay.
# One model. The endpoint and key are read from the environment and are not stored in this file.
#   export AGENTHEAL_API_URL=...
#   export AGENTHEAL_API_KEY=...
#   bash scripts/02_main_react.sh
# ============================== FILL IN ==============================
MODEL_NAME="${MODEL_NAME:-your-model-name}"
MODEL_TAG="${MODEL_TAG:-model}"
API_PROVIDER="${API_PROVIDER:-openai}"   # openai | anthropic
API_URL="${AGENTHEAL_API_URL:-}"
API_KEY="${AGENTHEAL_API_KEY:-}"
SPLITS="sandbox real"                   # sandbox = counterfactual sandbox (675), real = real-web replay (180)
WORKERS=4                               # parallel episodes (watch your API rate limit)
REPEATS=1                               # independent runs (seeds 0..REPEATS-1)
FRACTION=1.0                            # share of goals to run (e.g. 0.2 for a pilot)
# =====================================================================
source "$(dirname "$0")/_common.sh"

check_api
run_cell react 0
finish
