"""Stockfish-driven autoplayer vs Chess.app's built-in engine.

We play White. After every White move we:
  1. Push the move to our internal chess.Board.
  2. Wait for Chess.app's engine to respond.
  3. Snapshot the AX tree, parse square labels, find the legal Black move
     whose result matches the observed placement, push that to our board.
  4. Repeat.

The framework gets to do its job — `click_with_healing` finds the right
AXButton via T1; recovery branches handle drift. We supply the *intent*
(stockfish picks the move); the framework supplies the *control plane*.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import chess
import chess.engine
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cua_overlay.agents.chess_player import ChessAgent

CHESS_BUNDLE = "com.apple.Chess"


def _resolve_pid() -> int:
    try:
        out = subprocess.check_output(["pgrep", "-x", "Chess"], text=True)
    except subprocess.CalledProcessError:
        return 0
    return int(out.split()[0]) if out.strip() else 0


def _resolve_main_window_id(pid: int) -> int:
    """Pick the most-recent (highest window_id) titled Chess game window."""
    out = subprocess.check_output(["cua-driver", "call", "list_windows"], text=True)
    payload = json.loads(out)
    games = [
        w
        for w in payload["windows"]
        if w["pid"] == pid and "Akeil Smith - Computer" in (w.get("title") or "")
    ]
    if not games:
        return 0
    games.sort(key=lambda w: w["window_id"], reverse=True)
    return int(games[0]["window_id"])


_LABEL_RE = re.compile(
    r"AXButton\s+\"(?P<lbl>[^\"]+)\""
)
_INDEXED_BTN_RE = re.compile(
    r"\[(?P<idx>\d+)\]\s*AXButton\s+\"(?P<lbl>[^\"]+)\""
)


def parse_board_from_markdown(markdown: str) -> chess.Board:
    """Reconstruct a chess.Board (piece placement only) from the
    `tree_markdown` field returned by cua-driver get_window_state."""
    board = chess.Board.empty()
    for m in _LABEL_RE.finditer(markdown):
        parsed = ChessAgent.parse_label(m.group("lbl"))
        if parsed is None:
            continue
        piece, sq = parsed
        if piece is not None:
            board.set_piece_at(sq, piece)
    return board


def parse_label_to_index(markdown: str) -> dict[str, int]:
    """Map AXButton label → element_index from get_window_state markdown.
    The element_index is what cua-driver's `click` tool uses to target a
    specific element within a (pid, window_id) snapshot."""
    out: dict[str, int] = {}
    for m in _INDEXED_BTN_RE.finditer(markdown):
        out[m.group("lbl")] = int(m.group("idx"))
    return out


async def snapshot(pid: int, window_id: int) -> tuple[chess.Board, dict[str, int]]:
    """Call cua-driver get_window_state. Returns (board, label→element_index)."""
    proc = await asyncio.create_subprocess_exec(
        "cua-driver",
        "call",
        "get_window_state",
        json.dumps({"pid": pid, "window_id": window_id}),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    payload = json.loads(stdout)
    md = payload.get("tree_markdown", "")
    return parse_board_from_markdown(md), parse_label_to_index(md)


async def snapshot_board(pid: int, window_id: int) -> chess.Board:
    board, _ = await snapshot(pid, window_id)
    return board


async def wait_for_opponent_move(
    agent: ChessAgent,
    pid: int,
    window_id: int,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.4,
) -> chess.Move | None:
    """Poll AX until a placement is observed that matches a legal Black
    move played on top of `agent.board` (which already has our move pushed)."""
    deadline = time.monotonic() + timeout_s
    last_observed: chess.Board | None = None
    while time.monotonic() < deadline:
        observed = await snapshot_board(pid, window_id)
        last_observed = observed
        move = agent.find_opponent_move(observed)
        if move is not None:
            return move
        await asyncio.sleep(poll_interval_s)
    if last_observed is not None:
        # Diagnostic: dump observed FEN so we can see why no legal move matched.
        print(
            f"  [debug] no opponent move found within {timeout_s}s. "
            f"expected_after_us={agent.board.fen()!r}  "
            f"observed_placement={last_observed.fen()!r}",
            file=sys.stderr,
        )
    return None


async def click_element(
    session: ClientSession,  # kept for signature parity but unused — see note
    pid: int,
    window_id: int,
    element_index: int,
) -> dict:
    """Click a Chess.app square via cua-driver subprocess.

    Why not via the proxied MCP session: cua_overlay.mcp_server.proxy wraps
    every action-class tool with `_wrapped(**kwargs)`, and FastMCP infers
    a Pydantic schema that rejects natural argument shapes from clients.
    This is a framework bug — file under "TODO: proxy schema". For now we
    talk to cua-driver directly. The autoplayer still keeps a live MCP
    session open so click_with_healing / register_task_complete remain
    callable for verification + memory wiring on other paths.
    """
    proc = await asyncio.create_subprocess_exec(
        "cua-driver",
        "call",
        "click",
        json.dumps({
            "pid": pid,
            "window_id": window_id,
            "element_index": element_index,
        }),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    text = stdout.decode("utf-8", errors="replace")
    return {"raw": text.strip()[:200], "ok": "Performed AXPress" in text}


async def play_loop(
    plies: int,
    think_time_s: float,
    inter_click_s: float,
    inter_move_s: float,
):
    pid = _resolve_pid()
    if pid == 0:
        print("ERROR: Chess.app not running", file=sys.stderr)
        return 2
    window_id = _resolve_main_window_id(pid)
    if window_id == 0:
        print("ERROR: no titled Chess game window found", file=sys.stderr)
        return 2

    stockfish_path = shutil.which("stockfish") or "/opt/homebrew/bin/stockfish"
    if not Path(stockfish_path).exists():
        print(f"ERROR: stockfish not found at {stockfish_path}", file=sys.stderr)
        return 2

    print(f"  pid={pid}  window_id={window_id}  stockfish={stockfish_path}")

    agent = ChessAgent(
        mode="stockfish",
        stockfish_path=stockfish_path,
        think_time_s=think_time_s,
    )

    # Snapshot initial position from Chess.app to confirm a fresh game.
    initial = await snapshot_board(pid, window_id)
    standard_start = chess.Board()
    if any(
        initial.piece_at(sq) != standard_start.piece_at(sq)
        for sq in chess.SQUARES
    ):
        print(
            "WARNING: Chess.app board doesn't match standard starting position. "
            "Continuing anyway, but moves may diverge.",
            file=sys.stderr,
        )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cua_overlay.mcp_server"],
        env=dict(os.environ),
    )

    moves_played: list[tuple[str, str]] = []  # (white_uci, black_uci|"-")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("  MCP session initialized — playing")

            for ply_pair in range(plies):
                # ---- our (White) move ----
                if agent.is_game_over:
                    print(f"  game over: {agent.board.result()}")
                    break
                white_move = agent.pick_move()
                if white_move is None:
                    break
                src_label, dst_label = agent.move_to_labels(white_move)

                # Fresh snapshot so element_index is valid (cua-driver caches
                # element_index per (pid, window_id, turn_id) — stale indices
                # raise an error from cua-driver).
                _, idx_map = await snapshot(pid, window_id)
                src_idx = idx_map.get(src_label)
                dst_idx = idx_map.get(dst_label)
                if src_idx is None or dst_idx is None:
                    print(
                        f"  could not resolve label → element_index: "
                        f"src_label={src_label!r}  dst_label={dst_label!r}",
                        file=sys.stderr,
                    )
                    break

                t0 = time.monotonic()
                src_resp = await click_element(session, pid, window_id, src_idx)
                await asyncio.sleep(inter_click_s)
                dst_resp = await click_element(session, pid, window_id, dst_idx)
                elapsed = (time.monotonic() - t0) * 1000.0
                agent.commit(white_move)
                src_ok = "✓" if src_resp.get("ok") else "✗"
                dst_ok = "✓" if dst_resp.get("ok") else "✗"
                print(
                    f"  white  {white_move.uci()}  "
                    f"({src_label} → {dst_label})  "
                    f"src={src_ok} dst={dst_ok}  "
                    f"({elapsed:.0f}ms)"
                )

                # ---- wait for Chess.app's engine ----
                await asyncio.sleep(inter_move_s)
                black_move = await wait_for_opponent_move(
                    agent, pid, window_id
                )
                if black_move is None:
                    print(
                        "  black response not detected — board may have "
                        "diverged. stopping for analysis.",
                        file=sys.stderr,
                    )
                    moves_played.append((white_move.uci(), "?"))
                    break
                agent.board.push(black_move)
                moves_played.append((white_move.uci(), black_move.uci()))
                print(f"  black  {black_move.uci()}    (Chess.app engine)")

    agent.close()
    print()
    print(f"  moves: {moves_played}")
    print(f"  final FEN: {agent.fen}")
    if agent.is_game_over:
        print(f"  result: {agent.board.result()}")
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stockfish vs Chess.app — driven by cua-maximalist"
    )
    p.add_argument("--plies", type=int, default=6, help="Move pairs (default 6)")
    p.add_argument("--think-time", type=float, default=0.3)
    p.add_argument("--inter-click-delay", type=float, default=0.4)
    p.add_argument("--inter-move-delay", type=float, default=0.6)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    rc = asyncio.run(
        play_loop(
            plies=args.plies,
            think_time_s=args.think_time,
            inter_click_s=args.inter_click_delay,
            inter_move_s=args.inter_move_delay,
        )
    )
    sys.exit(rc)
