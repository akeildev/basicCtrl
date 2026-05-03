"""Parse Chess.app AX snapshot → FEN → Stockfish best move → element_indexes.

Usage:
  cat /tmp/ax_snapshot.txt | python3 /tmp/chess_helper.py [--depth 22]

Stdin: pipe the AX `tree_markdown` output from get_window_state.
Stdout: JSON {fen, bestmove_uci, src_square, dst_square, src_index, dst_index, side}.
"""
from __future__ import annotations
import sys, re, json, subprocess

PIECE_MAP = {
    "pawn": "p", "knight": "n", "bishop": "b",
    "rook": "r", "queen": "q", "king": "k",
}

# Match AXButton lines like:
#   "[14] AXButton "white pawn, f2" (white pawn, f2)"  → occupied
#   "[7] AXButton "g1" (g1)"                            → empty square
LINE_RE = re.compile(
    r"\[(\d+)\] AXButton \"([^\"]+)\""
)

def parse_ax_snapshot(text: str):
    """Return ({square: (piece_char, idx)}, {square: idx}).
    Pieces: piece_char follows FEN convention (uppercase=white).
    Empty squares included so we can look up dest.
    """
    pieces = {}     # square -> (FEN_char, element_index)
    by_square = {}  # square -> element_index (any square, occupied or empty)
    for m in LINE_RE.finditer(text):
        idx = int(m.group(1))
        label = m.group(2).strip()
        # Empty square label is just like "f4" (one letter+digit).
        if re.fullmatch(r"[a-h][1-8]", label):
            by_square[label] = idx
            continue
        # Occupied: "white pawn, f2"
        parts = [p.strip() for p in label.split(",")]
        if len(parts) != 2:
            continue
        descr, sq = parts
        if not re.fullmatch(r"[a-h][1-8]", sq):
            continue
        words = descr.lower().split()
        if len(words) < 2:
            continue
        color, piece = words[0], words[1]
        if piece not in PIECE_MAP:
            continue
        ch = PIECE_MAP[piece]
        if color == "white":
            ch = ch.upper()
        pieces[sq] = (ch, idx)
        by_square[sq] = idx
    return pieces, by_square


def build_fen(pieces: dict, side: str = "w", castling: str = "KQ", ep: str = "-"):
    """Build FEN from {square: (char, idx)}. Defaults assume mid-game,
    white to move, white still has KQ rights."""
    rows = []
    for rank in range(8, 0, -1):
        row = ""
        empty = 0
        for file in "abcdefgh":
            sq = f"{file}{rank}"
            entry = pieces.get(sq)
            if entry is None:
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                row += entry[0]
        if empty:
            row += str(empty)
        rows.append(row)
    return f"{'/'.join(rows)} {side} {castling} {ep} 0 1"


def stockfish_best(fen: str, depth: int = 22) -> str | None:
    """Return UCI bestmove, e.g. 'e2e4', 'g1f3', 'a7a8q' (promotion)."""
    cmd_input = f"uci\nisready\nposition fen {fen}\ngo depth {depth}\nquit\n"
    try:
        out = subprocess.run(
            ["stockfish"],
            input=cmd_input, text=True, capture_output=True, timeout=30,
        )
    except Exception as e:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("bestmove "):
            mv = line.split()[1]
            if mv == "(none)":
                return None
            return mv
    return None


def main():
    args = sys.argv[1:]
    depth = 22
    castling = "KQ"  # default; override via --castling
    ep = "-"
    side = "w"
    for i, a in enumerate(args):
        if a == "--depth" and i+1 < len(args):
            depth = int(args[i+1])
        if a == "--castling" and i+1 < len(args):
            castling = args[i+1]
        if a == "--ep" and i+1 < len(args):
            ep = args[i+1]
        if a == "--side" and i+1 < len(args):
            side = args[i+1]

    text = sys.stdin.read()
    pieces, by_square = parse_ax_snapshot(text)
    fen = build_fen(pieces, side=side, castling=castling, ep=ep)
    mv = stockfish_best(fen, depth=depth)
    if not mv or len(mv) < 4:
        print(json.dumps({"error": "no_move", "fen": fen}))
        return
    src, dst = mv[:2], mv[2:4]
    promo = mv[4:] if len(mv) > 4 else ""
    print(json.dumps({
        "fen": fen,
        "bestmove_uci": mv,
        "src_square": src,
        "dst_square": dst,
        "promotion": promo,
        "src_index": by_square.get(src),
        "dst_index": by_square.get(dst),
    }, indent=2))


if __name__ == "__main__":
    main()
