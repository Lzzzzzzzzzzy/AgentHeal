# Shared helpers for the experiment scripts. Sourced by scripts/NN_*.sh; do not run directly.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found. Run 'bash setup.sh' first." >&2
  exit 1
fi
RUNS_DIR="${RUNS_DIR:-$ROOT/runs}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR" "$RUNS_DIR"
SCRIPT_NAME="$(basename "$0" .sh)"
LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_$(date +%Y%m%d_%H%M%S).log"
export AGENTHEAL_LLM_TIMEOUT="${LLM_TIMEOUT:-120}"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

dataset_dir() {
  case "$1" in
    sandbox) echo "$ROOT/dataset" ;;
    real)    echo "$ROOT/dataset_real" ;;
    *) echo "ERROR: unknown split '$1' (use sandbox and/or real)" >&2; exit 1 ;;
  esac
}

check_model_fields() {
  local missing=0
  for v in MODEL_NAME MODEL_TAG API_PROVIDER API_URL API_KEY; do
    if [ -z "${!v:-}" ]; then echo "ERROR: $v is empty. Export AGENTHEAL_API_URL and AGENTHEAL_API_KEY, and set MODEL_NAME in $0" >&2; missing=1; fi
  done
  case "${API_PROVIDER:-}" in openai|anthropic) ;; *) echo "ERROR: API_PROVIDER must be openai or anthropic" >&2; missing=1 ;; esac
  [ "$missing" = 0 ] || exit 1
}

check_harness() {
  case "$1" in
    react) ;;
    *) echo "ERROR: this release only runs the ReAct agent" >&2; exit 1 ;;
  esac
}

# run_cell HARNESS CU [EXTRA_ARGS...]
#   HARNESS: react     CU: 0 | 1
run_cell() {
  local harness="$1" cu="$2"; shift 2
  check_harness "$harness"
  export AGENTHEAL_API_KEY="$API_KEY"
  export AGENTHEAL_API_URL="$API_URL"
  local split args
  for split in ${SPLITS}; do
    args=(--model-name "$MODEL_NAME" --tag "$MODEL_TAG" --provider "$API_PROVIDER"
          --harness "$harness" --dataset "$(dataset_dir "$split")" --runs "$RUNS_DIR/$split"
          --workers "${WORKERS:-4}" --repeats "${REPEATS:-1}" --fraction "${FRACTION:-1.0}")
    [ "$cu" = 1 ] && args+=(--cu)
    [ -n "${TASK_TYPE:-}" ] && args+=(--task-type "$TASK_TYPE")
    [ "${RERUN:-0}" = 1 ] && args+=(--rerun)
    [ -n "${FAMILY:-}" ] && args+=(--family "$FAMILY")
    log "== $split | harness=$harness computer_use=$cu | model=$MODEL_NAME"
    "$PY" -m agentheal run "${args[@]}" "$@" 2>&1 | tee -a "$LOG_FILE"
  done
}

# check_api: one short request to the model API before a long run (set SKIP_PING=1 to skip)
check_api() {
  check_model_fields
  [ "${SKIP_PING:-0}" = 1 ] && return 0
  log "checking API: provider=$API_PROVIDER model=$MODEL_NAME"
  export AGENTHEAL_API_KEY="$API_KEY"
  export AGENTHEAL_API_URL="$API_URL"
  if ! "$PY" -m agentheal ping --model-name "$MODEL_NAME" --provider "$API_PROVIDER" \
        2>&1 | tee -a "$LOG_FILE"; then
    echo "ERROR: the API check failed. Set MODEL_NAME in $0 and export AGENTHEAL_API_URL / AGENTHEAL_API_KEY (or SKIP_PING=1)" >&2
    exit 1
  fi
}

finish() { log "done. Results: $RUNS_DIR/<split>/<config>/ ; tables: bash scripts/07_report.sh ; log: $LOG_FILE"; }
