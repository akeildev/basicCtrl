"""Unit tests for ChessAgent (J2)."""
from __future__ import annotations

import random

import chess
import pytest

from cua_overlay.agents.chess_player import ChessAgent


@pytest.mark.unit
class TestParseLabel:
    def test_parses_occupied_label(self):
        piece, sq = ChessAgent.parse_label("white pawn, e2")
        assert piece == chess.Piece(chess.PAWN, chess.WHITE)
        assert sq == chess.E2

    def test_parses_black_knight(self):
        piece, sq = ChessAgent.parse_label("black knight, g8")
        assert piece == chess.Piece(chess.KNIGHT, chess.BLACK)
        assert sq == chess.G8

    def test_parses_empty_square(self):
        piece, sq = ChessAgent.parse_label("e4")
        assert piece is None
        assert sq == chess.E4

    def test_returns_none_for_non_chess_label(self):
        assert ChessAgent.parse_label("New Game") is None
        assert ChessAgent.parse_label("Score") is None

    def test_handles_extra_whitespace_and_case(self):
        piece, sq = ChessAgent.parse_label("  WHITE Pawn,  e2  ")
        assert piece == chess.Piece(chess.PAWN, chess.WHITE)
        assert sq == chess.E2


@pytest.mark.unit
class TestSyncFromAX:
    def test_reconstructs_starting_position_from_labels(self):
        agent = ChessAgent()
        # Build the labels Chess.app would emit at game start
        labels = []
        starting = chess.Board()
        for sq in chess.SQUARES:
            piece = starting.piece_at(sq)
            sq_name = chess.square_name(sq)
            if piece is None:
                labels.append(sq_name)
            else:
                color = "white" if piece.color else "black"
                pname = chess.piece_name(piece.piece_type)
                labels.append(f"{color} {pname}, {sq_name}")

        synced = agent.sync_from_ax(labels)
        # Board fingerprint should match piece placement
        for sq in chess.SQUARES:
            assert synced.piece_at(sq) == starting.piece_at(sq), (
                f"square {chess.square_name(sq)}: synced={synced.piece_at(sq)} "
                f"expected={starting.piece_at(sq)}"
            )

    def test_ignores_non_chess_labels(self):
        agent = ChessAgent()
        synced = agent.sync_from_ax(["New Game", "Score: 0", "white pawn, e2", "e3"])
        assert synced.piece_at(chess.E2) == chess.Piece(chess.PAWN, chess.WHITE)
        assert synced.piece_at(chess.E3) is None


@pytest.mark.unit
class TestPickMove:
    def test_random_legal_picks_a_legal_move(self):
        agent = ChessAgent(rng=random.Random(0))
        move = agent.pick_move()
        assert move in agent.board.legal_moves

    def test_first_legal_is_deterministic(self):
        a = ChessAgent(mode="first_legal")
        b = ChessAgent(mode="first_legal")
        assert a.pick_move() == b.pick_move()

    def test_returns_none_when_game_over(self):
        agent = ChessAgent()
        # Fool's mate: 1.f3 e5 2.g4 Qh4#
        for uci in ["f2f3", "e7e5", "g2g4", "d8h4"]:
            agent.board.push(chess.Move.from_uci(uci))
        assert agent.is_game_over
        assert agent.pick_move() is None


@pytest.mark.unit
class TestMoveToLabels:
    def test_pawn_advance_emits_bare_dest_label(self):
        agent = ChessAgent()
        move = chess.Move.from_uci("e2e4")
        src, dst = agent.move_to_labels(move)
        assert src == "white pawn, e2"
        assert dst == "e4"

    def test_capture_emits_captured_piece_label(self):
        agent = ChessAgent()
        # Set up a capture: 1.e4 d5 2.exd5
        for uci in ["e2e4", "d7d5"]:
            agent.board.push(chess.Move.from_uci(uci))
        move = chess.Move.from_uci("e4d5")
        src, dst = agent.move_to_labels(move)
        assert src == "white pawn, e4"
        assert dst == "black pawn, d5"

    def test_knight_move(self):
        agent = ChessAgent()
        move = chess.Move.from_uci("g1f3")
        src, dst = agent.move_to_labels(move)
        assert src == "white knight, g1"
        assert dst == "f3"

    def test_castling_uses_king_squares(self):
        agent = ChessAgent()
        # Clear the king-side castling path: 1.Nf3 Nf6 2.g3 g6 3.Bg2 Bg7
        for uci in ["g1f3", "g8f6", "g2g3", "g7g6", "f1g2", "f8g7"]:
            agent.board.push(chess.Move.from_uci(uci))
        move = chess.Move.from_uci("e1g1")  # White short castle
        assert move in agent.board.legal_moves
        src, dst = agent.move_to_labels(move)
        assert src == "white king, e1"
        assert dst == "g1"  # empty after path clearance

    def test_raises_when_no_piece_at_source(self):
        agent = ChessAgent()
        bogus = chess.Move(chess.E5, chess.E6)
        with pytest.raises(ValueError):
            agent.move_to_labels(bogus)


@pytest.mark.unit
class TestCommit:
    def test_pushes_move_and_records_history(self):
        agent = ChessAgent()
        move = chess.Move.from_uci("e2e4")
        agent.commit(move)
        assert agent.board.peek() == move
        assert agent.move_history == [("white pawn, e2", "e4")]

    def test_commit_advances_legal_move_chain(self):
        agent = ChessAgent()
        for uci in ["e2e4", "e7e5", "g1f3"]:
            agent.commit(chess.Move.from_uci(uci))
        assert len(agent.move_history) == 3
        assert agent.board.fullmove_number == 2  # White just moved on move 2
