#!/usr/bin/env bash
# scripts/preflight.sh — environment validation before running basicCtrl.
#
# Checks every dependency the overlay needs at boot. Distinguishes REQUIRED
# (block) from OPTIONAL (warn-only).
#
# Run before any e2e gate or `mcp-inspector` boot. The smoke + verify-everything
# scripts call this first.
#
# Exit codes:
#   0  — all REQUIRED green; OPTIONAL listed with status
#   2  — at least one REQUIRED check failed
#
# To launch MCP Inspector against the overlay (manual G1 boot proof):
#   npm install -g @modelcontextprotocol/inspector
#   mcp-inspector uv run python -m basicctrl.mcp_server
#
# Then in the browser: List Tools → expect 6 healing tools (click_with_healing,
# type_with_healing, scroll_with_healing, set_value_with_healing,
# send_destructive, key_combo_with_healing).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

red()    { printf "\033[31m%s\033[0m" "$*"; }
green()  { printf "\033[32m%s\033[0m" "$*"; }
yellow() { printf "\033[33m%s\033[0m" "$*"; }
hr()     { printf "\n%s\n" "------------------------------------------------------------------"; }

REQUIRED_FAILS=0

row() {
  local label="$1" status="$2" detail="${3:-}"
  case "$status" in
    OK)   printf "  [%s] %-28s %s\n" "$(green ✓)" "$label" "$detail" ;;
    WARN) printf "  [%s] %-28s %s\n" "$(yellow ⚠)" "$label" "$detail" ;;
    FAIL) printf "  [%s] %-28s %s\n" "$(red ✗)" "$label" "$detail"
          REQUIRED_FAILS=$((REQUIRED_FAILS + 1)) ;;
  esac
}

hr
echo "basicCtrl preflight"
echo "Repo: $REPO_ROOT"
hr

# ----------------------------------------------------------------------
# REQUIRED — must be green to ship
# ----------------------------------------------------------------------
echo
echo "REQUIRED"

# Python >=3.12 per pyproject.toml requires-python (project currently on 3.14)
PY_VER_TUPLE="$(uv run python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
PY_VER="$(uv run python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || echo "missing")"
PY_OK="$(uv run python -c 'import sys; print("yes" if sys.version_info >= (3, 12) else "no")' 2>/dev/null)"
if [[ "$PY_OK" == "yes" ]]; then
  row "Python >=3.12 (uv venv)" OK "$PY_VER"
else
  row "Python >=3.12 (uv venv)" FAIL "uv venv reports $PY_VER, need >=3.12 — run: uv sync"
fi

# uv installed
if command -v uv >/dev/null 2>&1; then
  row "uv installed" OK "$(uv --version)"
else
  row "uv installed" FAIL "install: brew install uv"
fi

# uv env intact + main module importable
if uv run python -c "from basicctrl.mcp_server.main import main" >/dev/null 2>&1; then
  row "main module imports" OK "basicctrl.mcp_server.main"
else
  row "main module imports" FAIL "uv sync failed or import error — run: uv sync"
fi

# cua-driver binary on PATH
if CUA_DRIVER_PATH="$(command -v cua-driver 2>/dev/null)"; then
  row "cua-driver on PATH" OK "$CUA_DRIVER_PATH"
else
  row "cua-driver on PATH" FAIL "build libs/cua-driver and symlink to ~/.local/bin"
fi

# Postgres reachable
if command -v psql >/dev/null 2>&1; then
  if psql -d "postgresql://localhost:5432/basicctrl" -c "SELECT 1" >/dev/null 2>&1; then
    row "Postgres :5432" OK "basicctrl database reachable"
  else
    row "Postgres :5432" FAIL "create db: ./scripts/init_postgres.sh"
  fi
else
  row "Postgres :5432" FAIL "psql not on PATH (brew install postgresql@16)"
fi

# mlx-vlm + uitag importable
if uv run python -c "import mlx_vlm" >/dev/null 2>&1; then
  MLX_VER="$(uv run python -c 'import mlx_vlm; print(mlx_vlm.__version__)' 2>/dev/null || echo unknown)"
  row "mlx-vlm importable" OK "$MLX_VER"
else
  row "mlx-vlm importable" FAIL "T5 grounder will fail — uv add mlx-vlm"
fi
if uv run python -c "import uitag" >/dev/null 2>&1; then
  UITAG_VER="$(uv run python -c "import uitag; print(getattr(uitag,'__version__','?'))" 2>/dev/null)"
  row "uitag importable" OK "$UITAG_VER"
else
  row "uitag importable" FAIL "T4 vision will fail — uv add uitag"
fi

# AX trust (TCC Accessibility)
AX_OUT="$(uv run python -c "
try:
    try:
        from HIServices import AXIsProcessTrusted
    except ImportError:
        from ApplicationServices import AXIsProcessTrusted
    print('TRUSTED' if AXIsProcessTrusted() else 'UNTRUSTED')
except Exception as e:
    print('ERROR', e)
" 2>/dev/null)"
case "$AX_OUT" in
  TRUSTED)   row "TCC Accessibility" OK "AXIsProcessTrusted=True" ;;
  UNTRUSTED) row "TCC Accessibility" FAIL "grant Accessibility to your terminal/IDE in System Settings → Privacy" ;;
  *)         row "TCC Accessibility" FAIL "probe failed: $AX_OUT" ;;
esac

# ScreenCaptureKit available (Screen Recording perm tested at runtime)
if uv run python -c "import ScreenCaptureKit" >/dev/null 2>&1; then
  row "ScreenCaptureKit import" OK "Screen Recording grant tested at runtime"
else
  row "ScreenCaptureKit import" FAIL "pyobjc-framework-ScreenCaptureKit missing"
fi

# ----------------------------------------------------------------------
# OPTIONAL — graceful skip when missing
# ----------------------------------------------------------------------
echo
echo "OPTIONAL (graceful skip when missing)"

# API keys
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  row "ANTHROPIC_API_KEY"   OK "set (Planner + B3/B4 real path enabled)"
else
  row "ANTHROPIC_API_KEY"   WARN "unset → Planner disabled, B3/B4 fall back to stubs"
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  row "OPENAI_API_KEY"      OK "set (LLM verifier + ensemble vote enabled)"
else
  row "OPENAI_API_KEY"      WARN "unset → L3 verifier + ensemble disabled"
fi

# Chromium-flavored browser for CDP gate (Chromium, Chrome, Brave, Edge — all speak CDP)
CHROMIUM_FOUND=""
if command -v chromium >/dev/null 2>&1; then
  CHROMIUM_FOUND="chromium (CLI)"
elif [[ -d "/Applications/Chromium.app" ]]; then
  CHROMIUM_FOUND="Chromium.app"
elif [[ -d "/Applications/Google Chrome.app" ]]; then
  CHROMIUM_FOUND="Google Chrome.app"
elif [[ -d "/Applications/Brave Browser.app" ]]; then
  CHROMIUM_FOUND="Brave Browser.app"
elif [[ -d "/Applications/Microsoft Edge.app" ]]; then
  CHROMIUM_FOUND="Microsoft Edge.app"
fi
if [[ -n "$CHROMIUM_FOUND" ]]; then
  row "chromium-flavored browser" OK "$CHROMIUM_FOUND → CUA_RUN_E2E_CDP_CHROMIUM available"
else
  row "chromium-flavored browser" WARN "install Chrome/Chromium/Brave/Edge → unlocks CDP gate"
fi

# Calculator (already required by demo)
if [[ -d /System/Applications/Calculator.app ]]; then
  row "Calculator.app"       OK "/System/Applications/Calculator.app"
else
  row "Calculator.app"       WARN "missing — Phase 1 demo target unavailable"
fi

# Chess (Vision lane in canary)
if [[ -d /System/Applications/Chess.app ]] || [[ -d /Applications/Chess.app ]]; then
  row "Chess.app"            OK "vision-lane canary target"
else
  row "Chess.app"            WARN "missing → canary skips Vision lane"
fi

# SIP partial-off (DTrace + ES)
SIP_STATUS="$(csrutil status 2>/dev/null | head -1 || echo unknown)"
if echo "$SIP_STATUS" | grep -qi "disabled\|partial\|custom"; then
  row "SIP partial-off"      OK "$SIP_STATUS"
else
  row "SIP partial-off"      WARN "fully on → ES + DTrace tiers gracefully skipped"
fi

# Visualizer Swift sidecar built
VIZ_BIN="libs/cua-driver/.build/arm64-apple-macosx/debug/cua-driver"
if [[ -x "$VIZ_BIN" ]]; then
  row "Visualizer sidecar"   OK "$VIZ_BIN"
else
  row "Visualizer sidecar"   WARN "build: (cd libs/cua-driver && swift build) → unlocks visualizer gate"
fi

# MCP Inspector availability (manual G1 boot proof)
if command -v mcp-inspector >/dev/null 2>&1; then
  row "mcp-inspector CLI"    OK "$(command -v mcp-inspector)"
else
  row "mcp-inspector CLI"    WARN "install for G1 boot proof: npm i -g @modelcontextprotocol/inspector"
fi

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
hr
if [[ $REQUIRED_FAILS -eq 0 ]]; then
  green "preflight: REQUIRED green"
  echo
  echo
  echo "Manual G1 boot proof (one-time):"
  echo "  mcp-inspector uv run python -m basicctrl.mcp_server"
  echo "  → in browser, click List Tools → expect 6 healing tools"
  hr
  exit 0
else
  red "preflight: $REQUIRED_FAILS REQUIRED check(s) failed — fix before running"
  echo
  hr
  exit 2
fi
