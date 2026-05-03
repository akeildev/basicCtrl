"""Chess game-state tracker + move picker for basicCtrl autoplayer.

Wraps `python-chess.Board` to:
  - Drive an internal board (push moves, generate legal moves)
  - Optionally sync from a list of Chess.app AX labels (sanity check)
  - Convert a `chess.Move` to (source_label, dest_label) strings that match
    Chess.app's AXButton labels: "white pawn, e2" → "e4" (or "<piece>, <sq>"
    when capturing).

Pure Python — no MCP, no asyncio. The autoplayer script wires this to the
healing tools.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

import chess
import chess.engine

# AX label format observed on Chess.app:
#   Occupied: "<color> <piece>, <square>"   e.g. "white pawn, e2"
#   Empty:    "<square>"                    e.g. "e4"
_OCCUPIED_RE = re.compile(
    r"^(?P<color>white|black)\s+"
    r"(?P<piece>king|queen|rook|bishop|knight|pawn)"
    r",\s*(?P<square>[a-h][1-8])$",
    re.IGNORECASE,
)
_EMPTY_RE = re.compile(r"^(?P<square>[a-h][1-8])$", re.IGNORECASE)

PIECE_NAME_TO_TYPE = {
    "king": chess.KING,
    "queen": chess.QUEEN,
    "rook": chess.ROOK,
    "bishop": chess.BISHOP,
    "knight": chess.KNIGHT,
    "pawn": chess.PAWN,
}

PIECE_TYPE_TO_NAME = {v: k for k, v in PIECE_NAME_TO_TYPE.items()}


PickerMode = Literal["random_legal", "first_legal", "stockfish"]


@dataclass
class ChessAgent:
    """Tracks board state and converts moves to AX-button labels."""

    mode: PickerMode = "random_legal"
    board: chess.Board = field(default_factory=chess.Board)
    move_history: list[tuple[str, str]] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    # Stockfish config (used only when mode == "stockfish"). Path defaults
    # to the brew-installed binary; think_time_s is per-move budget.
    stockfish_path: str = "/opt/homebrew/bin/stockfish"
    think_time_s: float = 0.2
    _engine: Optional[chess.engine.SimpleEngine] = field(default=None, init=False, repr=False)

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:  # noqa: BLE001
                pass
            self._engine = None

    def __del__(self):
        self.close()

    # ---- introspection ----
    @property
    def fen(self) -> str:
        return self.board.fen()

    @property
    def is_game_over(self) -> bool:
        return self.board.is_game_over()

    # ---- AX label parsing ----
    @staticmethod
    def parse_label(label: str) -> Optional[tuple[Optional[chess.Piece], int]]:
        """Parse one AX label.

        Returns (piece_or_None, square_index) where square_index is 0..63
        per python-chess (a1=0, h1=7, a8=56, h8=63). Returns None if the
        label isn't a chess square at all (titles, score boards, etc.).
        """
        s = label.strip()
        m = _OCCUPIED_RE.match(s)
        if m:
            color = chess.WHITE if m.group("color").lower() == "white" else chess.BLACK
            piece_type = PIECE_NAME_TO_TYPE[m.group("piece").lower()]
            sq = chess.parse_square(m.group("square").lower())
            return (chess.Piece(piece_type, color), sq)
        m = _EMPTY_RE.match(s)
        if m:
            sq = chess.parse_square(m.group("square").lower())
            return (None, sq)
        return None

    def find_opponent_move(self, observed: chess.Board) -> Optional[chess.Move]:
        """Find the legal move on `self.board` that produces `observed`'s
        piece placement.

        Used after we've pushed our own move to detect what Chess.app's
        engine played in response. Returns None when no legal move makes
        the placements line up — the caller should then re-poll AX or
        treat it as a temporary inconsistency.

        Comparison ignores side-to-move / castling / en-passant metadata
        (sync_from_ax can't recover those from labels alone) — only piece
        placement matters.
        """
        target_map = {sq: observed.piece_at(sq) for sq in chess.SQUARES}
        for move in self.board.legal_moves:
            self.board.push(move)
            try:
                match = all(
                    self.board.piece_at(sq) == target_map[sq] for sq in chess.SQUARES
                )
            finally:
                self.board.pop()
            if match:
                return move
        return None

    def sync_from_ax(self, ax_labels: list[str]) -> chess.Board:
        """Reconstruct a chess.Board from a list of AX labels.

        Useful as a sanity check against `self.board` after a move. Does
        NOT mutate `self.board` — caller decides whether to trust the AX
        view over the pushed move (Chess.app sometimes lags one frame).
        Returns the synthesized board.

        Note: side-to-move + castling rights + en passant cannot be
        derived from labels alone. The synthesized board's metadata is
        left at defaults; only piece placement is authoritative.
        """
        board = chess.Board.empty()
        for label in ax_labels:
            parsed = self.parse_label(label)
            if parsed is None:
                continue
            piece, sq = parsed
            if piece is not None:
                board.set_piece_at(sq, piece)
        return board

    # ---- move generation ----
    def pick_move(self) -> Optional[chess.Move]:
        if self.is_game_over:
            return None
        moves = list(self.board.legal_moves)
        if not moves:
            return None
        if self.mode == "first_legal":
            return moves[0]
        if self.mode == "stockfish":
            return self._pick_stockfish_move()
        # random_legal
        return self.rng.choice(moves)

    def _pick_stockfish_move(self) -> Optional[chess.Move]:
        """Lazy-spawn Stockfish over UCI; ask for the best move within the
        per-call think-time budget."""
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
        result = self._engine.play(
            self.board,
            chess.engine.Limit(time=self.think_time_s),
        )
        return result.move

    # ---- move → labels ----
    def move_to_labels(self, move: chess.Move) -> tuple[str, str]:
        """Convert a chess.Move to (source_label, dest_label).

        Source label always includes piece info ("white pawn, e2") because
        Chess.app's AXButton for an occupied square embeds the piece.
        Dest label is the captured piece's label when capturing, otherwise
        the bare square name ("e4").

        Special moves:
          - Castling: returns (king_src_label, king_dst_label). Chess.app
            commits the rook automatically when the king lands.
          - En passant: dest square is empty visually but the move IS a
            capture; we emit the bare dest-square label so the click lands
            on the correct cell. (Chess.app does the rest.)
          - Promotion: dest label is the bare square; the user / autoplayer
            still has to handle the promotion dialog separately. Random
            legal play in <20 plies almost never promotes — punt for J2.
        """
        piece = self.board.piece_at(move.from_square)
        if piece is None:
            raise ValueError(
                f"no piece at source square for move {move.uci()}; "
                f"board:\n{self.board}"
            )
        src_label = self._format_occupied_label(piece, move.from_square)

        to_sq_name = chess.square_name(move.to_square)
        captured = self.board.piece_at(move.to_square)
        if captured is not None:
            dst_label = self._format_occupied_label(captured, move.to_square)
        else:
            dst_label = to_sq_name
        return src_label, dst_label

    @staticmethod
    def _format_occupied_label(piece: chess.Piece, square: int) -> str:
        color_name = "white" if piece.color else "black"
        piece_name = PIECE_TYPE_TO_NAME[piece.piece_type]
        return f"{color_name} {piece_name}, {chess.square_name(square)}"

    # ---- commit move (after AX driver fires both clicks) ----
    def commit(self, move: chess.Move) -> None:
        """Push the move onto the internal board. Caller invokes after
        the autoplayer confirms both clicks landed."""
        src_label, dst_label = self.move_to_labels(move)
        self.move_history.append((src_label, dst_label))
        self.board.push(move)
