#!/usr/bin/env bash
# scripts/smoke.sh — single-command health check for cua-maximalist v1.0.
#
# Verifies:
#   1. Swift sidecar build is clean (libs/cua-driver/)
#   2. All unit tests pass (525 across phases 1-6 — must be green)
#   3. Integration test status is reported (skips/fails are informational —
#      most need Calculator/Slack running + Accessibility + Screen Recording
#      grants, and SIP partial-off for ES/DTrace)
#
# Exit code: 0 = unit tests + Swift build clean. Non-zero otherwise.
# Integration test failures do NOT fail the smoke script — they're env-gated.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
hr()     { printf "\n%s\n" "------------------------------------------------------------------"; }

EXIT_CODE=0

hr
echo "cua-maximalist v1.0 smoke test"
echo "Repo: $REPO_ROOT"
hr

# ----------------------------------------------------------------------
# 1. Swift sidecar build
# ----------------------------------------------------------------------
echo
echo "[1/3] Swift sidecar build (libs/cua-driver/)"
if (cd libs/cua-driver && swift build 2>&1) | tail -3; then
  green "  ✓ Swift build clean"
else
  red   "  ✗ Swift build FAILED"
  EXIT_CODE=1
fi

# ----------------------------------------------------------------------
# 2. Unit tests (must be 100% green)
# ----------------------------------------------------------------------
echo
echo "[2/3] Unit tests (tests/unit/)"
UNIT_OUT=$(uv run pytest tests/unit/ -q --no-header -o addopts="" 2>&1 | tail -3 || true)
echo "$UNIT_OUT"
if echo "$UNIT_OUT" | grep -qE "[0-9]+ failed"; then
  red "  ✗ Unit tests have failures — code regression"
  EXIT_CODE=1
elif echo "$UNIT_OUT" | grep -qE "[0-9]+ passed"; then
  green "  ✓ Unit tests pass"
else
  yellow "  ? Unit test status unclear — inspect output above"
  EXIT_CODE=1
fi

# ----------------------------------------------------------------------
# 3. Integration tests (informational)
# ----------------------------------------------------------------------
echo
echo "[3/3] Integration tests (tests/integration/) — informational"
echo "  Note: most need real apps running + macOS permissions."
echo "  Failures here usually mean an app/permission isn't set up,"
echo "  not that the framework code is broken."
echo
INT_OUT=$(uv run pytest tests/integration/ -q --no-header -o addopts="" --tb=no 2>&1 | tail -3 || true)
echo "$INT_OUT"

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
hr
if [[ $EXIT_CODE -eq 0 ]]; then
  green "SMOKE PASSED — Swift builds clean, unit tests green."
  echo
  echo "Optional next steps for full live validation (~10 min total):"
  echo "  • Open Calculator.app → re-run integration tests for AX path"
  echo "  • Grant Screen Recording to Terminal/Python → SC#3 (overlay exclusion)"
  echo "  • Live DYLD inject smoke: see PHASE-6-DEMO.md \"Manual Smoke Checks\""
  echo "  • SIP partial-off (csrutil enable --without dtrace,fs) → unlocks ES + DTrace tests"
else
  red "SMOKE FAILED — see output above."
fi
hr

exit $EXIT_CODE
