"""Environment doctor for cua-maximalist.

Prints OK / WARN / FAIL status for each dependency the overlay needs:

  * Python 3.12.x (FAIL otherwise — strictly pinned in pyproject.toml)
  * uv installed and on PATH
  * Postgres 16 listening on localhost:5432 / database "cua_maximalist"
    (WARN if not — Plan 07 wires this; not required for Plan 01-01 tests)
  * AXIsProcessTrusted() — TCC Accessibility grant for the Python interpreter
  * /System/Applications/Calculator.app exists (the Phase 1 demo target)

Exit codes:

  0 — no FAILs (WARNs allowed)
  1 — at least one FAIL: blocker, fix before running tests
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table


def _check_python() -> tuple[str, str]:
    v = sys.version_info
    if v.major == 3 and v.minor == 12:
        return "OK", f"Python {v.major}.{v.minor}.{v.micro}"
    return "FAIL", f"need Python 3.12.x, found {v.major}.{v.minor}.{v.micro}"


def _check_uv() -> tuple[str, str]:
    if shutil.which("uv") is None:
        return "FAIL", "uv not on PATH (install: brew install uv)"
    try:
        out = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, check=True, timeout=5
        )
        return "OK", out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return "FAIL", f"uv invocation failed: {exc}"


def _check_postgres() -> tuple[str, str]:
    if shutil.which("psql") is None:
        return "WARN", "psql not on PATH — Plan 07 (PERSIST-01) requires Postgres 16"
    try:
        out = subprocess.run(
            [
                "psql",
                "-d",
                "postgresql://localhost:5432/cua_maximalist",
                "-c",
                "SELECT 1",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.SubprocessError as exc:
        return "WARN", f"psql invocation failed: {exc}"
    if out.returncode == 0:
        return "OK", "postgres reachable on localhost:5432/cua_maximalist"
    return (
        "WARN",
        "postgres unreachable (run: brew services start postgresql@16 && createdb cua_maximalist)",
    )


def _check_ax_trust() -> tuple[str, str]:
    try:
        try:
            from HIServices import AXIsProcessTrusted  # type: ignore[attr-defined]
        except ImportError:
            from ApplicationServices import (  # type: ignore[attr-defined]
                AXIsProcessTrusted,
            )
    except ImportError:
        return "FAIL", "pyobjc not installed — run `make install` first"

    trusted = bool(AXIsProcessTrusted())
    if trusted:
        return "OK", "AXIsProcessTrusted=True"
    return (
        "WARN",
        "AXIsProcessTrusted=False — grant Accessibility to your Terminal/IDE in TCC",
    )


def _check_calculator() -> tuple[str, str]:
    p = Path("/System/Applications/Calculator.app")
    if p.is_dir():
        return "OK", str(p)
    return "FAIL", "Calculator.app missing — Phase 1 demo target"


def main() -> int:
    console = Console()
    table = Table(title="cua-maximalist doctor", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    checks = [
        ("Python 3.12.x", _check_python),
        ("uv installed", _check_uv),
        ("Postgres listening", _check_postgres),
        ("AXIsProcessTrusted", _check_ax_trust),
        ("Calculator.app", _check_calculator),
    ]

    style = {"OK": "green", "WARN": "yellow", "FAIL": "red"}
    fails = 0
    for name, fn in checks:
        status, detail = fn()
        if status == "FAIL":
            fails += 1
        table.add_row(name, f"[{style[status]}]{status}[/]", detail)

    console.print(table)
    if fails:
        console.print(f"[red]{fails} blocker(s) — fix before running tests[/]")
        return 1
    console.print("[green]doctor: all green (warns are OK for early phases)[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
