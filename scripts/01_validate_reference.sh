#!/usr/bin/env bash
# Reference agents (Appendix "Reference agents"): oracle, always-answer, always-abstain, violator.
# No model and no API key needed. Expected: "VALIDATION PASSED" for both environments (oracle scores PGS = 1
# with no violations (CR = 0); the other three score PGS = 0). About 5 minutes with 8 workers.
WORKERS=8
source "$(dirname "$0")/_common.sh"

for split in sandbox real; do
  log "== validating $split"
  "$PY" -m agentheal validate --dataset "$(dataset_dir "$split")" --runs "$RUNS_DIR/validate_$split" \
        --workers "$WORKERS" 2>&1 | tee -a "$LOG_FILE"
done
log "done. Summaries: $RUNS_DIR/validate_sandbox/validation_summary.json, $RUNS_DIR/validate_real/validation_summary.json"
