"""Drive Chess.app via basicCtrl's MCP server (J2).

MODE A (default, no LLM): python-chess generates random legal moves; the
autoplayer drives Chess.app by clicking source square then destination
square via `click_with_healing`. On verifier failure the recovery branches
fire automatically.

Usage:
    python scripts/chess_autoplayer.py --moves 10
    python scripts/chess_autoplayer.py --moves 5 --inject-failure-every 4

Pre-conditions:
    - Chess.app launched with a FRESH game (Game → New Game). If you don't
      do this the AX labels will not match the starting position because
      Chess.app restores the previous game on launch.
    - TCC permissions: Accessibility + Screen Recording for whichever
      process runs this script.
    - cua-driver Swift binary on PATH (or CUA_DRIVER_BIN env var pointing
      at the absolute path).

Episode log lands in `~/.cua/sessions/<pid>/chess_episode.jsonl` (one JSON
line per move attempt).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import chess
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from basicctrl.agents.chess_player import ChessAgent

CHESS_BUNDLE_ID = "com.apple.Chess"


@dataclass
class MoveOutcome:
    """One driven move attempt — both clicks + verification metadata."""

    move_uci: str
    src_label: str
    dst_label: str
    src_verified: bool
    dst_verified: bool
    src_recovery_ran: bool
    dst_recovery_ran: bool
    elapsed_ms: float
    raw_src: dict[str, Any] = field(default_factory=dict)
    raw_dst: dict[str, Any] = field(default_factory=dict)

    @property
    def fully_verified(self) -> bool:
        return self.src_verified and self.dst_verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "move": self.move_uci,
            "src_label": self.src_label,
            "dst_label": self.dst_label,
            "src_verified": self.src_verified,
            "dst_verified": self.dst_verified,
            "src_recovery_ran": self.src_recovery_ran,
            "dst_recovery_ran": self.dst_recovery_ran,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "fully_verified": self.fully_verified,
        }


@dataclass
class AutoplayResult:
    moves: list[MoveOutcome] = field(default_factory=list)
    episode_path: Optional[Path] = None
    final_fen: str = ""
    game_over: bool = False
    aborted_reason: Optional[str] = None

    @property
    def fully_verified_count(self) -> int:
        return sum(1 for m in self.moves if m.fully_verified)

    @property
    def recovery_triggered_count(self) -> int:
        return sum(
            1 for m in self.moves if m.src_recovery_ran or m.dst_recovery_ran
        )


def _resolve_chess_pid() -> int:
    """Return the PID of the running Chess.app, or 0 if not running."""
    try:
        out = subprocess.check_output(["pgrep", "-x", "Chess"], text=True)
    except subprocess.CalledProcessError:
        return 0
    pids = [int(p) for p in out.split() if p.strip().isdigit()]
    return pids[0] if pids else 0


def _episode_dir() -> Path:
    base = Path.home() / ".cua" / "sessions"
    sid = os.environ.get("CUA_SESSION_ID", str(os.getpid()))
    p = base / f"chess-{sid}"
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _click(
    session: ClientSession,
    pid: int,
    label: str,
) -> dict[str, Any]:
    """Call click_with_healing on a label. We use label-based matching so T1
    walks the AX tree, which is the whole point of the demo."""
    result = await session.call_tool(
        "click_with_healing",
        arguments={
            "x": 0,
            "y": 0,
            "bundle_id": CHESS_BUNDLE_ID,
            "pid": pid,
            "label": label,
        },
    )
    # FastMCP returns CallToolResult; structuredContent / content[0].text both
    # work but structuredContent is the typed payload.
    if getattr(result, "structuredContent", None) is not None:
        return dict(result.structuredContent)
    # Fallback: parse the first TextContent block.
    for block in result.content or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return {}


async def play_one_move(
    session: ClientSession,
    agent: ChessAgent,
    pid: int,
    move: chess.Move,
    inter_click_delay_s: float = 0.5,
) -> MoveOutcome:
    src_label, dst_label = agent.move_to_labels(move)
    t0 = time.monotonic()

    src_resp = await _click(session, pid, src_label)
    await asyncio.sleep(inter_click_delay_s)
    dst_resp = await _click(session, pid, dst_label)

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    return MoveOutcome(
        move_uci=move.uci(),
        src_label=src_label,
        dst_label=dst_label,
        src_verified=bool(src_resp.get("verified")),
        dst_verified=bool(dst_resp.get("verified")),
        src_recovery_ran=bool(src_resp.get("recovery", {}).get("ran")),
        dst_recovery_ran=bool(dst_resp.get("recovery", {}).get("ran")),
        elapsed_ms=elapsed_ms,
        raw_src=src_resp,
        raw_dst=dst_resp,
    )


async def run_autoplayer(
    num_moves: int = 10,
    mode: str = "random_legal",
    inject_failure_every: Optional[int] = None,
    inter_click_delay_s: float = 0.5,
    inter_move_delay_s: float = 0.4,
) -> AutoplayResult:
    """Drive Chess.app for `num_moves` plies. Spawns basicCtrl MCP
    over stdio and calls click_with_healing twice per move."""
    result = AutoplayResult()

    pid = _resolve_chess_pid()
    if pid == 0:
        result.aborted_reason = "Chess.app not running — `open -a Chess` first"
        return result

    agent = ChessAgent(mode=mode)
    episode_dir = _episode_dir()
    log_path = episode_dir / "chess_episode.jsonl"
    result.episode_path = log_path

    cua_driver_bin = os.environ.get("CUA_DRIVER_BIN")
    env_for_subprocess = dict(os.environ)
    if cua_driver_bin and "CUA_DRIVER_BIN" not in env_for_subprocess:
        env_for_subprocess["CUA_DRIVER_BIN"] = cua_driver_bin

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "basicctrl.mcp_server"],
        env=env_for_subprocess,
    )

    with log_path.open("a", encoding="utf-8") as log_fp:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for ply in range(num_moves):
                    move = agent.pick_move()
                    if move is None:
                        result.game_over = agent.is_game_over
                        break

                    # Synthetic failure injection: clobber the source label
                    # so T1 fails to resolve it. Recovery branches should
                    # then fire (B5 AppleScript in particular).
                    inject = (
                        inject_failure_every
                        and (ply + 1) % inject_failure_every == 0
                    )
                    real_src, _ = agent.move_to_labels(move)
                    if inject:
                        # Mutate the agent's view temporarily — we want the
                        # bogus label to flow through but the move logic to
                        # remain consistent. Clean way: fire the bogus click
                        # explicitly here, then proceed with the real click.
                        bogus_resp = await _click(session, pid, "!@#nonexistent")
                        log_fp.write(
                            json.dumps(
                                {
                                    "kind": "failure_injection",
                                    "ply": ply,
                                    "bogus_label": "!@#nonexistent",
                                    "verified": bool(bogus_resp.get("verified")),
                                    "recovery_ran": bool(
                                        bogus_resp.get("recovery", {}).get("ran")
                                    ),
                                }
                            )
                            + "\n"
                        )
                        log_fp.flush()
                        await asyncio.sleep(inter_click_delay_s)

                    outcome = await play_one_move(
                        session,
                        agent,
                        pid,
                        move,
                        inter_click_delay_s=inter_click_delay_s,
                    )
                    agent.commit(move)

                    log_fp.write(
                        json.dumps({"kind": "move", "ply": ply, **outcome.to_dict()})
                        + "\n"
                    )
                    log_fp.flush()
                    result.moves.append(outcome)

                    print(
                        f"[ply {ply + 1:>2}] {move.uci():>5}  "
                        f"src={'✓' if outcome.src_verified else '✗'} "
                        f"dst={'✓' if outcome.dst_verified else '✗'}  "
                        f"({outcome.elapsed_ms:.0f}ms)",
                        flush=True,
                    )

                    if inter_move_delay_s > 0:
                        await asyncio.sleep(inter_move_delay_s)

    result.final_fen = agent.fen
    result.game_over = agent.is_game_over

    # Summary line at end of file.
    with log_path.open("a", encoding="utf-8") as log_fp:
        log_fp.write(
            json.dumps(
                {
                    "kind": "summary",
                    "moves_played": len(result.moves),
                    "fully_verified": result.fully_verified_count,
                    "recovery_triggered": result.recovery_triggered_count,
                    "final_fen": result.final_fen,
                    "game_over": result.game_over,
                }
            )
            + "\n"
        )
    return result


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chess.app autoplayer (J2)")
    p.add_argument("--moves", type=int, default=10, help="Number of plies")
    p.add_argument(
        "--mode",
        choices=["random_legal", "first_legal"],
        default="random_legal",
    )
    p.add_argument(
        "--inject-failure-every",
        type=int,
        default=None,
        help="Fire a bogus click every Nth move to exercise recovery",
    )
    p.add_argument(
        "--inter-click-delay",
        type=float,
        default=0.5,
        help="Seconds between source-click and dest-click",
    )
    p.add_argument(
        "--inter-move-delay",
        type=float,
        default=0.4,
        help="Seconds between moves",
    )
    return p.parse_args()


async def _amain() -> int:
    args = _parse_args()
    if shutil.which("cua-driver") is None and not os.environ.get("CUA_DRIVER_BIN"):
        print(
            "ERROR: cua-driver binary not found. Build "
            "`cd libs/cua-driver && swift build -c release`, then add the "
            "binary directory to PATH or set CUA_DRIVER_BIN.",
            file=sys.stderr,
        )
        return 2

    result = await run_autoplayer(
        num_moves=args.moves,
        mode=args.mode,
        inject_failure_every=args.inject_failure_every,
        inter_click_delay_s=args.inter_click_delay,
        inter_move_delay_s=args.inter_move_delay,
    )

    if result.aborted_reason:
        print(f"ABORTED: {result.aborted_reason}", file=sys.stderr)
        return 3

    print()
    print(f"  moves played       : {len(result.moves)}")
    print(f"  fully verified     : {result.fully_verified_count}")
    print(f"  recovery triggered : {result.recovery_triggered_count}")
    print(f"  final fen          : {result.final_fen}")
    print(f"  game over          : {result.game_over}")
    print(f"  episode log        : {result.episode_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_amain()))
