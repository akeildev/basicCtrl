#!/usr/bin/env bash
# scripts/smoke.sh — single-command health check for basicCtrl v1.0.
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
echo "basicCtrl v1.0 smoke test"
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
# 3. Integration tests
# ----------------------------------------------------------------------
echo
echo "[3/4] Integration tests (tests/integration/)"
echo "  Hardware-gated tests (Chess, Pages, ES/DTrace) skip cleanly when"
echo "  their app/permission isn't set up — failures here ARE code regressions."
echo
INT_OUT=$(uv run pytest tests/integration/ -q --no-header -o addopts="" --tb=no 2>&1 | tail -3 || true)
echo "$INT_OUT"
if echo "$INT_OUT" | grep -qE "[0-9]+ failed"; then
  red "  ✗ Integration tests have failures — investigate"
  EXIT_CODE=1
elif echo "$INT_OUT" | grep -qE "[0-9]+ passed"; then
  green "  ✓ Integration tests pass (env-gated tests properly skipped)"
fi

# ----------------------------------------------------------------------
# 4. End-to-end Calculator demo (live, OPT-IN)
# ----------------------------------------------------------------------
echo
echo "[4/4] End-to-end Calculator demo: framework drives 5 + 3 = 8"
echo "  Set CUA_RUN_E2E_CALC=1 to run. Requires Accessibility grant."
if [[ "${CUA_RUN_E2E_CALC:-0}" == "1" ]]; then
  pkill -9 -x Calculator 2>/dev/null || true
  sleep 2
  E2E_OUT=$(CUA_RUN_E2E_CALC=1 uv run pytest \
      tests/integration/test_calculator_e2e_arithmetic.py \
      -q --no-header -o addopts="" --tb=short 2>&1 | tail -5 || true)
  echo "$E2E_OUT"
  if echo "$E2E_OUT" | grep -qE "1 passed"; then
    green "  ✓ Framework successfully drove Calculator to compute 5 + 3 = 8"
  else
    red "  ✗ End-to-end demo failed — investigate above"
    EXIT_CODE=1
  fi
else
  yellow "  ↷ Skipped (set CUA_RUN_E2E_CALC=1 to run live demo)"
fi

# ----------------------------------------------------------------------
# 4b. End-to-end Race Orchestrator demo (live, OPT-IN, same Calculator scenario)
# ----------------------------------------------------------------------
echo
echo "[4b/4] End-to-end Race Orchestrator on Calculator (full Phase 2 path)"
echo "  Set CUA_RUN_E2E_RACE=1 to run. Requires Accessibility grant."
if [[ "${CUA_RUN_E2E_RACE:-0}" == "1" ]]; then
  pkill -9 -x Calculator 2>/dev/null || true
  sleep 2
  RACE_OUT=$(CUA_RUN_E2E_RACE=1 uv run pytest \
      tests/integration/test_calculator_race_orchestrator_e2e.py \
      -q --no-header -o addopts="" --tb=short 2>&1 | tail -5 || true)
  echo "$RACE_OUT"
  if echo "$RACE_OUT" | grep -qE "1 passed"; then
    green "  ✓ RaceOrchestrator.execute drove Calculator (T1 wins, race telemetry written)"
  else
    red "  ✗ Race orchestrator e2e failed — investigate above"
    EXIT_CODE=1
  fi
else
  yellow "  ↷ Skipped (set CUA_RUN_E2E_RACE=1 to run live race demo)"
fi

# ----------------------------------------------------------------------
# 4c. End-to-end Recovery Orchestrator demo (live, OPT-IN)
# ----------------------------------------------------------------------
echo
echo "[4c/4] End-to-end Recovery Orchestrator on Calculator (B1-B5 dispatch)"
echo "  Set CUA_RUN_E2E_RECOVERY=1 to run. Requires Accessibility grant."
if [[ "${CUA_RUN_E2E_RECOVERY:-0}" == "1" ]]; then
  pkill -9 -x Calculator 2>/dev/null || true
  sleep 2
  REC_OUT=$(CUA_RUN_E2E_RECOVERY=1 uv run pytest \
      tests/integration/test_recovery_orchestrator_e2e.py \
      -q --no-header -o addopts="" --tb=short 2>&1 | tail -5 || true)
  echo "$REC_OUT"
  if echo "$REC_OUT" | grep -qE "1 passed"; then
    green "  ✓ RecoveryOrchestrator.attempt drove branches B1+B2+B4 on Calculator"
  else
    red "  ✗ Recovery orchestrator e2e failed — investigate above"
    EXIT_CODE=1
  fi
else
  yellow "  ↷ Skipped (set CUA_RUN_E2E_RECOVERY=1 to run live recovery demo)"
fi

# ----------------------------------------------------------------------
# Post-v1.0 hardening gates (added 2026-05-02 per ULTRAPLAN Phase D)
# ----------------------------------------------------------------------
# Each gate runs the corresponding e2e test when its env var is set;
# otherwise skips cleanly. None affects EXIT_CODE unless explicitly opted in.

run_gate() {
  local name="$1" envvar="$2" testpath="$3" required_dep="$4"
  echo
  echo "[$name] $testpath"
  if [[ "${!envvar:-0}" != "1" ]]; then
    yellow "  ↷ Skipped (set $envvar=1 to run)"
    return
  fi
  if [[ -n "$required_dep" ]] && ! eval "$required_dep" >/dev/null 2>&1; then
    yellow "  ↷ Skipped (dependency missing: $required_dep)"
    return
  fi
  GATE_OUT=$(env "$envvar=1" uv run pytest "$testpath" -q --no-header -o addopts="" --tb=short 2>&1 | tail -6 || true)
  echo "$GATE_OUT"
  if echo "$GATE_OUT" | grep -qE "passed"; then
    green "  ✓ $name passed"
  elif echo "$GATE_OUT" | grep -qE "skipped" && ! echo "$GATE_OUT" | grep -qE "failed|error"; then
    yellow "  ↷ skipped (within-test gate)"
  else
    red "  ✗ $name failed"
    EXIT_CODE=1
  fi
}

run_gate "5/CDP-CHROMIUM" "CUA_RUN_E2E_CDP_CHROMIUM" "tests/integration/test_cdp_chromium_e2e.py" "command -v chromium || command -v Chromium"
run_gate "6/DURABILITY"   "CUA_RUN_E2E_DURABILITY"   "tests/integration/test_durability_sigkill_resume_e2e.py" "psql -d postgresql://localhost:5432/basicctrl -c 'SELECT 1'"
run_gate "7/VISUALIZER"   "CUA_RUN_E2E_VISUALIZER"   "tests/integration/test_visualizer_socket_e2e.py" "test -x libs/cua-driver/.build/arm64-apple-macosx/debug/cua-driver"
run_gate "8/MEMORY"       "CUA_RUN_E2E_MEMORY"       "tests/integration/test_memory_recall_e2e.py" ""
run_gate "9/RECOVERY-REAL" "CUA_RUN_E2E_RECOVERY_REAL" "tests/integration/test_recovery_b3_b4_e2e.py" "test -n \"\$ANTHROPIC_API_KEY\""
run_gate "10/CANARY"      "CUA_RUN_E2E_CANARY"       "tests/integration/test_canary_multi_app.py" ""

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
hr
if [[ $EXIT_CODE -eq 0 ]]; then
  green "SMOKE PASSED — Swift builds clean, unit + integration green."
  echo
  echo "Live demo: CUA_RUN_E2E_CALC=1 ./scripts/smoke.sh"
  echo "Other live targets:"
  echo "  • CUA_RUN_E2E_RACE=1            → RaceOrchestrator on Calculator"
  echo "  • CUA_RUN_E2E_RECOVERY=1        → B1-B5 dispatch on Calculator"
  echo "  • CUA_RUN_E2E_TEXTEDIT=1        → T3+C4 AppleScript on TextEdit"
  echo "  • CUA_RUN_E2E_CDP_CHROMIUM=1    → T2+C5 on chromium (post-v1.0)"
  echo "  • CUA_RUN_E2E_DURABILITY=1      → SIGKILL+resume (post-v1.0)"
  echo "  • CUA_RUN_E2E_VISUALIZER=1      → visualizer socket (post-v1.0)"
  echo "  • CUA_RUN_E2E_MEMORY=1          → FAISS recall (post-v1.0)"
  echo "  • CUA_RUN_E2E_RECOVERY_REAL=1   → B3/B4 real path (needs ANTHROPIC_API_KEY)"
  echo "  • CUA_RUN_E2E_CANARY=1          → 3+ apps in one MCP session (post-v1.0)"
  echo "  • CUA_RUN_CHESS=1               → T4/T5 grounding on Chess"
  echo "  • CUA_RUN_PAGES=1               → T3 AppleScript on Pages"
  echo "  • Run everything: ./scripts/verify-everything.sh"
else
  red "SMOKE FAILED — see output above."
fi
hr

exit $EXIT_CODE
