#!/usr/bin/env bash
# scripts/verify-everything.sh — full verification harness.
#
# Runs preflight, then every CUA_RUN_E2E_* gate that can be auto-enabled,
# then prints a status table. Exits non-zero if any required gate fails.
#
# Usage:
#   ./scripts/verify-everything.sh
#
# Honors existing CUA_RUN_E2E_* env vars; will auto-enable the gate when
# its dependency is detected (preflight tells us what's available).
#
# Time budget: <5min wall when all green (chromium boot is the slow path).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

red()    { printf "\033[31m%s\033[0m" "$*"; }
green()  { printf "\033[32m%s\033[0m" "$*"; }
yellow() { printf "\033[33m%s\033[0m" "$*"; }
hr()     { printf "\n%s\n" "------------------------------------------------------------------"; }

# Status table accumulator
declare -a RESULTS

record() {
  local name="$1" status="$2" detail="$3"
  RESULTS+=("$name|$status|$detail")
}

run_pytest_gate() {
  local name="$1" envvar="$2" testpath="$3" can_run="$4"
  if [[ "$can_run" != "yes" ]]; then
    record "$name" "SKIP" "dependency missing"
    return
  fi
  # F2 mitigation: kill apps between gates so Calculator/TextEdit state from
  # the previous gate doesn't poison the next gate's resolver lookups.
  # Calculator additionally persists RestoreInputValue/LastResultValue to
  # NSUserDefaults — wipe those so the next launch starts at "0".
  pkill -9 -x Calculator 2>/dev/null || true
  pkill -9 -x TextEdit   2>/dev/null || true
  defaults delete com.apple.calculator 2>/dev/null || true
  sleep 1
  local start=$(date +%s)
  local out
  out=$(env "$envvar=1" uv run pytest "$testpath" -q --no-header -o addopts="" --tb=line 2>&1 | tail -8 || true)
  local elapsed=$(($(date +%s) - start))
  if echo "$out" | grep -qE "[0-9]+ passed"; then
    record "$name" "PASS" "${elapsed}s"
  elif echo "$out" | grep -qE "[0-9]+ skipped" && ! echo "$out" | grep -qE "failed|error"; then
    record "$name" "SKIP" "test self-skipped"
  else
    record "$name" "FAIL" "${elapsed}s — see output"
    echo "  --- $name failed output ---"
    echo "$out" | sed 's/^/    /'
  fi
}

# ----------------------------------------------------------------------
# 1. Preflight (REQUIRED)
# ----------------------------------------------------------------------
hr
echo "verify-everything: preflight"
hr
if ! ./scripts/preflight.sh; then
  red "preflight FAILED — abort"
  exit 2
fi

# ----------------------------------------------------------------------
# 2. Detect what's available so we know which gates to auto-run
# ----------------------------------------------------------------------
hr
echo "verify-everything: capability detection"
hr

HAS_CHROMIUM=no
HAS_POSTGRES=no
HAS_VIZ_BIN=no
HAS_ANTHROPIC=no
HAS_CALCULATOR=no
HAS_CHESS=no
HAS_TEXTEDIT=yes  # always present on macOS

# Chromium-flavored: Chrome / Brave / Edge all speak CDP, so any of these unlocks the gate.
if command -v chromium >/dev/null 2>&1 \
   || [[ -d "/Applications/Chromium.app" ]] \
   || [[ -d "/Applications/Google Chrome.app" ]] \
   || [[ -d "/Applications/Brave Browser.app" ]] \
   || [[ -d "/Applications/Microsoft Edge.app" ]]; then
  HAS_CHROMIUM=yes
fi
psql -d "postgresql://localhost:5432/basicctrl" -c "SELECT 1" >/dev/null 2>&1 && HAS_POSTGRES=yes
[[ -x libs/cua-driver/.build/arm64-apple-macosx/debug/cua-driver ]] && HAS_VIZ_BIN=yes
[[ -n "${ANTHROPIC_API_KEY:-}" ]] && HAS_ANTHROPIC=yes
[[ -d /System/Applications/Calculator.app ]] && HAS_CALCULATOR=yes
[[ -d /System/Applications/Chess.app || -d /Applications/Chess.app ]] && HAS_CHESS=yes

echo "  chromium:           $HAS_CHROMIUM"
echo "  postgres:           $HAS_POSTGRES"
echo "  visualizer binary:  $HAS_VIZ_BIN"
echo "  ANTHROPIC_API_KEY:  $HAS_ANTHROPIC"
echo "  Calculator.app:     $HAS_CALCULATOR"
echo "  Chess.app:          $HAS_CHESS"

# ----------------------------------------------------------------------
# 3. Unit tests (always run)
# ----------------------------------------------------------------------
hr
echo "verify-everything: unit tests"
hr
START=$(date +%s)
UNIT_OUT=$(uv run pytest tests/unit/ -q --no-header -o addopts="" 2>&1 | tail -3)
ELAPSED=$(($(date +%s) - START))
echo "$UNIT_OUT"
if echo "$UNIT_OUT" | grep -qE "[0-9]+ failed"; then
  record "unit-tests" "FAIL" "${ELAPSED}s"
elif echo "$UNIT_OUT" | grep -qE "[0-9]+ passed"; then
  record "unit-tests" "PASS" "${ELAPSED}s"
else
  record "unit-tests" "FAIL" "no test outcome — bad invocation"
fi

# ----------------------------------------------------------------------
# 4. E2E gates (auto-enabled when dependency present)
# ----------------------------------------------------------------------
hr
echo "verify-everything: e2e gates"
hr

run_pytest_gate "calc"           "CUA_RUN_E2E_CALC"        "tests/integration/test_calculator_e2e_arithmetic.py"   "$HAS_CALCULATOR"
run_pytest_gate "race"           "CUA_RUN_E2E_RACE"        "tests/integration/test_calculator_race_orchestrator_e2e.py" "$HAS_CALCULATOR"
run_pytest_gate "recovery"       "CUA_RUN_E2E_RECOVERY"    "tests/integration/test_recovery_orchestrator_e2e.py"   "$HAS_CALCULATOR"
run_pytest_gate "textedit"       "CUA_RUN_E2E_TEXTEDIT"    "tests/integration/test_textedit_e2e_typing.py"         "$HAS_TEXTEDIT"
run_pytest_gate "cdp-chromium"   "CUA_RUN_E2E_CDP_CHROMIUM" "tests/integration/test_cdp_chromium_e2e.py"           "$HAS_CHROMIUM"
run_pytest_gate "durability"     "CUA_RUN_E2E_DURABILITY"  "tests/integration/test_durability_sigkill_resume_e2e.py" "$HAS_POSTGRES"
run_pytest_gate "visualizer"     "CUA_RUN_E2E_VISUALIZER"  "tests/integration/test_visualizer_socket_e2e.py"       "$HAS_VIZ_BIN"
run_pytest_gate "memory"         "CUA_RUN_E2E_MEMORY"      "tests/integration/test_memory_recall_e2e.py"           "yes"
# recovery-real: J1 turned this gate into always-runnable. The sampling-path
# tests (TestB3SamplingPath / TestB4SamplingPath) exercise the no-API-key
# path via MCPSamplingPlanner + a mocked FastMCP Context; the legacy
# api-key-gated tests (TestB3RealPath / TestB4RealPath) skip cleanly when
# ANTHROPIC_API_KEY is unset. Either path proving the wire-up is enough.
run_pytest_gate "recovery-real"  "CUA_RUN_E2E_RECOVERY_REAL" "tests/integration/test_recovery_b3_b4_e2e.py"        "yes"
run_pytest_gate "canary"         "CUA_RUN_E2E_CANARY"      "tests/integration/test_canary_multi_app.py"            "$HAS_CALCULATOR"
# J3 cross-app: Calculator + TextEdit produce ~/math.txt. TextEdit is always
# present so the precondition is just Calculator.
run_pytest_gate "cross-app"      "CUA_RUN_E2E_CROSS_APP"   "tests/integration/test_cross_app_demo.py"              "$HAS_CALCULATOR"

# ----------------------------------------------------------------------
# 5. Status table
# ----------------------------------------------------------------------
hr
echo "verify-everything: SUMMARY"
hr
EXIT_CODE=0
printf "%-18s  %-6s  %s\n" "GATE" "STATUS" "DETAIL"
printf "%-18s  %-6s  %s\n" "------------------" "------" "----------------------------"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r name status detail <<< "$row"
  case "$status" in
    PASS) printf "%-18s  $(green PASS)    %s\n" "$name" "$detail" ;;
    SKIP) printf "%-18s  $(yellow SKIP)    %s\n" "$name" "$detail" ;;
    FAIL) printf "%-18s  $(red FAIL)    %s\n" "$name" "$detail"
          EXIT_CODE=1 ;;
  esac
done

hr
if [[ $EXIT_CODE -eq 0 ]]; then
  green "verify-everything: ALL ENABLED GATES PASSED"
else
  red "verify-everything: $EXIT_CODE failure(s)"
fi
hr

exit $EXIT_CODE
