#!/usr/bin/env bash
# AgentHeal setup for Linux (Ubuntu 22.04/24.04, Debian 12 or similar). Run from the repository root as a normal user:
#   bash setup.sh                    Python env, Playwright Chromium, dataset check, unit tests
#   bash setup.sh --with-deps        also install Chromium's system libraries (asks for sudo)
#   bash setup.sh --rebuild-dataset  regenerate dataset/ and dataset_real/ instead of only checking them
#   bash setup.sh --skip-tests       skip the unit tests
#   bash setup.sh --system-site-packages   let .venv see Python packages already installed system-wide
#                                    (for machines without PyPI access that already have playwright)
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
WITH_DEPS=0; REBUILD=0; TESTS=1; VENV_OPTS=""
for a in "$@"; do
  case "$a" in
    --with-deps) WITH_DEPS=1 ;;
    --rebuild-dataset) REBUILD=1 ;;
    --skip-tests) TESTS=0 ;;
    --system-site-packages) VENV_OPTS="--system-site-packages" ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done
step() { echo; echo "==> $*"; }

mkdir -p logs
step "1/5 Python"
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "python3 not found. Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"; exit 1; }
"$PYTHON" - <<'PY' || exit 1
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Python >= 3.10 is required, found {sys.version.split()[0]}")
print("Python", sys.version.split()[0])
PY
if ! "$PYTHON" -c "import venv, ensurepip" 2>/dev/null; then
  echo "The venv module is missing. Ubuntu/Debian: sudo apt install python3-venv"; exit 1
fi

step "2/5 virtual environment (.venv) and Python packages"
[ -x .venv/bin/python ] || "$PYTHON" -m venv $VENV_OPTS .venv
.venv/bin/python -m pip install --upgrade pip -q || echo "(pip upgrade skipped)"
if ! .venv/bin/python -m pip install -q "playwright>=1.40"; then
  echo "Could not install playwright. Check internet / PyPI access (a proxy needs HTTPS_PROXY),"
  echo "or install it system-wide and rerun with --system-site-packages."; exit 1
fi
.venv/bin/python -m pip install -q "numpy>=1.24" "pandas>=2.0" "statsmodels>=0.14" \
  || echo "(optional statistics packages numpy/pandas/statsmodels not installed; only mixed-effects models need them)"
.venv/bin/python -c "import playwright; print('playwright available')"

step "3/5 Playwright Chromium (browser and computer-use tools)"
if [ "$WITH_DEPS" = 1 ]; then
  sudo "$ROOT/.venv/bin/python" -m playwright install-deps chromium
fi
.venv/bin/python -m playwright install chromium || echo "(Chromium download failed; checking for an existing browser)"
if ! .venv/bin/python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); b.close()
print("headless Chromium starts")
PY
then
  echo "Chromium does not start: either the download failed (network) or its system libraries are missing."
  echo "Run: bash setup.sh --with-deps"; exit 1
fi

step "4/5 datasets"
if [ "$REBUILD" = 1 ] || [ ! -f dataset/manifest.json ]; then
  .venv/bin/python -m agentheal build-dataset --out dataset
else
  .venv/bin/python -m agentheal qc --dataset dataset | grep -E '"n_(episodes|failed)"' \
    || { echo "dataset/ fails quality checks; rebuild with: bash setup.sh --rebuild-dataset"; exit 1; }
fi
if [ "$REBUILD" = 1 ] || [ ! -d dataset_real/episodes ]; then
  .venv/bin/python -m agentheal build-real --out dataset_real | tail -n 6
fi
echo "sandbox episodes: $(ls dataset/episodes | wc -l)   real-web episodes: $(ls dataset_real/episodes | wc -l)"

step "5/5 unit tests"
if [ "$TESTS" = 1 ]; then
  .venv/bin/python -W ignore -m unittest discover -s tests > logs/setup_tests.log 2>&1 && T=0 || T=$?
  grep -E "^(Ran|OK|FAILED)" logs/setup_tests.log
  [ "$T" = 0 ] || { echo "unit tests failed; see logs/setup_tests.log"; exit 1; }
else
  echo "skipped"
fi

echo
echo "Setup finished. Next:"
echo "  1. bash scripts/01_validate_reference.sh      (no API key needed)"
echo "  2. export AGENTHEAL_API_URL and AGENTHEAL_API_KEY, set MODEL_NAME in scripts/00_smoke_test.sh, then run it"
echo "  3. bash scripts/02_main_react.sh, then bash scripts/07_report.sh   (see README.md)"
