#!/usr/bin/env bash
# Smoke test: checks the API, then runs one goal per barrier family with ReAct.
# Results go to runs_smoke/ and do not mix with real runs.
#   export AGENTHEAL_API_URL=...
#   export AGENTHEAL_API_KEY=...
#   bash scripts/00_smoke_test.sh
# ============================== FILL IN ==============================
MODEL_NAME="${MODEL_NAME:-your-model-name}"
MODEL_TAG="${MODEL_TAG:-model}"
API_PROVIDER="${API_PROVIDER:-openai}"   # openai | anthropic
API_URL="${AGENTHEAL_API_URL:-}"
API_KEY="${AGENTHEAL_API_KEY:-}"
SPLITS="sandbox"
WORKERS=4
REPEATS=1
FRACTION=1.0
# =====================================================================
RUNS_DIR="$(cd "$(dirname "$0")/.." && pwd)/runs_smoke"
source "$(dirname "$0")/_common.sh"

check_api
run_cell react 0 --select one_goal_per_family
finish
