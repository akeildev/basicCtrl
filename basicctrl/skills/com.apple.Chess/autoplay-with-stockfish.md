# Chess.app — autoplay with local Stockfish

> Field-tested 2026-05-03. Won as White vs Computer (default difficulty)
> in 17 moves from a mid-game position. Total: ~10 min, ~83 tool calls,
> 0 self-heal triggers. Final move Bg6# (mate in 1 from depth-22 query).

## Bundle ID

`com.apple.Chess`

## Mental model

Chess.app is fully AX-driven. Every square is an `AXButton` with a
**semantic label**:

```
"white pawn, e2"      ← occupied square (color, piece, square)
"e4"                  ← empty square (just the algebraic name)
```

That means we get the entire board state from one `get_window_state`
snapshot — no vision, no OCR, no pixel work. The 64-square grid lives
inside the first `AXGroup` of the window; element_indexes 1-64 map to
a1-h8 in column-major order (a1=1, b1=2, ..., a2=9, ..., h8=64) but
**don't rely on the index math** — read the labels.

The window title is the move-state oracle:

```
"(White to Move)"     → my turn
"(Black to Move)"     → bot is thinking (or title is lagging)
"(White wins!)"       → checkmate, game over
"(Stalemate)"         → draw
```

**Title can lag** — bot may have already moved while title still says
"Black to Move". Verify via `list_windows on_screen_only=true` rather
than the snapshot title; the windows API updates faster.

## Prerequisites

```
brew install stockfish    # local UCI engine (~/4MB binary)
```

Stockfish 18+ at depth 18-22 returns moves in 1-3 seconds. More than
enough to crush Chess.app's default difficulty.

## Helper script

`basicctrl/skills/com.apple.Chess/chess_helper.py` parses an AX
snapshot, builds FEN, queries Stockfish, returns the move + element
indexes:

```bash
cat snapshot.txt | python3 chess_helper.py [--depth 22] [--castling KQkq] [--ep -]
# →
# {
#   "fen": "...",
#   "bestmove_uci": "f2f4",
#   "src_square": "f2", "dst_square": "f4",
#   "src_index": 14, "dst_index": 30
# }
```

**Castling-rights flag matters.** Once your king moves, drop "KQ" from
the flag. Helper defaults to `KQ` (white still has rights) — pass
`--castling -` once you've moved king or both rooks.

## Recipe — full game loop

```python
# Per turn — 1 snapshot + 1 bash + 2 clicks + 1 sleep = 5 calls

1. get_window_state(pid, window_id)                    # full AX dump
2. (extract piece labels, save to file or paste inline)
3. cat snapshot.txt | python3 chess_helper.py --depth 22 --castling <state>
   → src_index, dst_index, bestmove_uci
4. click(pid, window_id, element_index=src_index)      # select piece
5. click(pid, window_id, element_index=dst_index)      # move target
6. sleep(4)                                            # bot thinks 2-4s
7. (loop)
```

**Same snapshot = both clicks valid.** The element_index cache is
per-snapshot, but indexes from one snapshot work for both source AND
destination clicks within that turn. Don't re-snapshot between
clicks.

## Win condition detection

```python
title = list_windows(pid, on_screen_only=True)[0]["title"]
if "wins" in title or "Stalemate" in title:
    break
```

Title flips from "(White to Move)" → "(White wins!)" the instant the
mating move lands. Use this as the loop termination, not snapshot
parsing.

## Bot-deviation handling

The bot deviates from Stockfish's predicted PV ~20% of the time on
default difficulty. **Re-query every turn from the actual current
position** — never blindly follow Stockfish's predicted line beyond
the immediate move.

If bot plays unexpectedly:
1. Re-snapshot
2. Build fresh FEN from actual position
3. Query Stockfish anew
4. Play the move it returns now (not the next move from the previous
   PV line)

## Promotion handling (untested)

Stockfish returns 5-char UCI like `a7a8q` for promotion. Chess.app
likely opens an AXPopover for piece choice on promotion. **Not yet
field-tested.** When it happens:
1. Click source pawn (e.g. a7) → select
2. Click promotion square (a8) → triggers popover
3. snapshot → look for AXPopover children "Queen", "Rook", "Bishop",
   "Knight"
4. click the matching choice
5. Default to Queen unless Stockfish suggests otherwise

## Castling handling (untested in this run)

Castling in UCI is e.g. `e1g1` (kingside). Click king e1, click g1.
Chess.app should auto-move the rook. If it doesn't, click rook h1
then click f1.

## En passant handling (untested)

UCI move includes the destination square (e.g. `e5d6` capturing on
d6). The captured pawn (on d5) gets removed automatically by the app
— don't try to click it.

## Traps

- **Pawns don't capture backward.** Trivial chess fact, but I almost
  blundered by trying `f4xg3` when a black queen landed on g3 (white
  f4 pawn captures FORWARD-diagonal only — to e5/g5 — never g3).
  Always trust Stockfish's bestmove; never override with hand-analysis.

- **Castling rights drop the moment the king moves.** Pass
  `--castling -` (or `--castling kq` if black still has rights) on
  every turn after Ke1-d2. Stockfish silently mis-evaluates if you
  leave KQ in.

- **Bot sometimes hangs queens.** Don't be surprised — default
  difficulty isn't deep enough to see all tactics. Take material
  with confidence when Stockfish says so.

- **Title-lag illusion.** "Black to Move" right after my move
  doesn't mean my move failed — it means the bot is thinking and
  Chess.app's status text is just slow to refresh. Always check
  `list_windows(on_screen_only=true)` for the real title.

## Sample game (this run)

Mid-game start position:
```
FEN: r1b2rk1/pppn1ppp/n3p2q/1N1pP3/3P4/6PN/PPP2P2/R2QKB1R w KQ - 0 1
```

17 moves to mate. Notable Stockfish calls:
- Move 7: Nh3-g5 sacrificial line, +5.45 eval, bot took the bait
- Move 9: Nxh7 piece sac for h-file invasion
- Move 11: Rxg6 — eval flipped to mate-in-8
- Move 17: **Bd3-g6#** — depth-22 returned mate-in-1 in 3ms

## Memory loop integration

After successful games, register in FAISS:

```python
register_task_complete(
    task_label="play and win chess.app vs computer",
    task_class="game_full_play",
    app_bundle_id="com.apple.Chess",
)
```

Note: only fires recipes if the run used `*_with_healing` wrappers.
This recipe used raw `click` (per-square AX is reliable enough — no
healing needed for Chess.app), so the FAISS recipe won't auto-fire.
That's why the markdown above is the load-bearing artifact for this
app — read it on next run.
