#!/usr/bin/env bash
# Tables and figure inputs from all finished runs (no API needed):
#   reports/<split>/paper_results.{csv,md,tex}   Table "Main results" columns (TS0 TS RR RC AA HR VR PGP, failure modes)
#   reports/<split>/paper_by_family.csv          per-family breakdown (Figures RQ1, RQ2, Ablation c)
#   reports/<split>/paper_shapley.json           Shapley values per model and harness (Figure Ablation a)
#   reports/<split>/summary.json                 every metric of every configuration
source "$(dirname "$0")/_common.sh"

for split in sandbox real; do
  if [ -d "$RUNS_DIR/$split" ]; then
    log "== report $split"
    "$PY" -m agentheal report --runs "$RUNS_DIR/$split" --out "$ROOT/reports/$split" 2>&1 | tee -a "$LOG_FILE"
  else
    log "skip $split: $RUNS_DIR/$split does not exist yet"
  fi
done
[ -f "$ROOT/reports/sandbox/paper_results.md" ] && cat "$ROOT/reports/sandbox/paper_results.md"
[ -f "$ROOT/reports/real/paper_results.md" ] && cat "$ROOT/reports/real/paper_results.md"
log "done. Tables in $ROOT/reports/"
