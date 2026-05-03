"""ACT-03 / D-19 — DuplicateReceipt 2s ring buffer behavior tests."""
from __future__ import annotations

from basicctrl.actions.duplicate_receipt import DuplicateReceipt


def test_first_record_not_duplicate() -> None:
    r = DuplicateReceipt()
    assert r.record("key-A", "click", 1_000_000_000) is False


def test_second_within_window_is_duplicate() -> None:
    r = DuplicateReceipt()
    t0 = 1_000_000_000
    r.record("key-A", "click", t0)
    assert r.record("key-A", "click", t0 + 1_000_000) is True  # +1ms


def test_outside_window_is_not_duplicate() -> None:
    r = DuplicateReceipt()
    t0 = 1_000_000_000
    r.record("key-A", "click", t0)
    # 2.1s later → outside the 2s window.
    assert r.record("key-A", "click", t0 + 2_100_000_000) is False


def test_different_action_kind_not_duplicate() -> None:
    r = DuplicateReceipt()
    t0 = 1_000_000_000
    r.record("key-A", "click", t0)
    assert r.record("key-A", "type", t0 + 1_000_000_000) is False


def test_different_target_not_duplicate() -> None:
    r = DuplicateReceipt()
    t0 = 1_000_000_000
    r.record("key-A", "click", t0)
    assert r.record("key-B", "click", t0 + 1_000_000_000) is False


def test_buffer_bounded_under_sliding_window() -> None:
    r = DuplicateReceipt()
    t0 = 1_000_000_000
    # 1100 entries, each 3 ms apart, spanning ~3.3s. After the sliding window
    # prunes anything older than 2s, the buffer should never exceed ~700 (
    # 2s / 3ms). Loose bound: <1000 — proves prune is firing.
    for i in range(1100):
        r.record(f"target-{i}", "click", t0 + i * 3_000_000)
    assert len(r) < 1000
