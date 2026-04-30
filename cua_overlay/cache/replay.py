"""CassetteReplayEngine: deterministic replay with pHash-based step matching.

Per CONTEXT.md D-19, D-23: Cassette replay runs recorded steps until the first
step doesn't match (pHash delta > 8 bits). On mismatch, replay stops and falls
through to live RaceOrchestrator execution. This enables fast paths (cache hits
skip planning) and setup for Plan 03-08 write-back.

pHash threshold (8 bits) is empirically derived per D-23 to detect real drifts
without false positives (Tahoe screenshot regression).
"""
from __future__ import annotations

import logging
from typing import Optional

from cua_overlay.cache.cassette import Cassette


log = logging.getLogger(__name__)


def hamming_distance(h1: str, h2: str) -> int:
    """Calculate Hamming distance between two hex pHash strings.

    Converts each hex digit to 4-bit binary and counts differing bits.

    Args:
        h1: hex pHash string (e.g., "abc123def456")
        h2: hex pHash string (e.g., "abc123def789")

    Returns:
        Total count of differing bits (0-64 for 64-bit hashes)
    """
    if len(h1) != len(h2):
        # Pad shorter hash with zeros
        max_len = max(len(h1), len(h2))
        h1 = h1.ljust(max_len, "0")
        h2 = h2.ljust(max_len, "0")

    distance = 0
    for c1, c2 in zip(h1, h2):
        # Convert hex chars to 4-bit binary and XOR
        bits1 = int(c1, 16)
        bits2 = int(c2, 16)
        xor = bits1 ^ bits2
        # Count set bits in XOR result
        distance += bin(xor).count("1")
    return distance


class CassetteReplayEngine:
    """Replay recorded cassette steps with pHash-based matching.

    Per D-19: Replays cassette until first non-matching step (pHash diff > 8),
    then falls through to live RaceOrchestrator.

    Attributes:
        _cassette: Cassette instance to replay
        _race_orchestrator: RaceOrchestrator for fallthrough on mismatch
        _l1_cheap: L1CheapDiff for pHash snapshot comparison
        _session_writer: SessionWriter for replay events
        _phash_threshold: max Hamming distance for pHash match (default 8)
    """

    def __init__(
        self,
        cassette: Cassette,
        race_orchestrator,
        l1_cheap,
        session_writer,
        target_pid: int,
        bundle_id: str,
    ):
        """Initialize CassetteReplayEngine.

        Args:
            cassette: Cassette instance to replay
            race_orchestrator: RaceOrchestrator for fallthrough
            l1_cheap: L1CheapDiff for pHash comparison
            session_writer: SessionWriter for events
            target_pid: process ID of target app
            bundle_id: bundle ID of target app
        """
        self._cassette = cassette
        self._race_orchestrator = race_orchestrator
        self._l1_cheap = l1_cheap
        self._session_writer = session_writer
        self._target_pid = target_pid
        self._bundle_id = bundle_id
        self._phash_threshold = 8

    async def replay(
        self,
    ) -> tuple[bool, Optional[int], list[dict]]:
        """Replay cassette steps until first mismatch.

        Returns: (success: bool, first_mismatch_step_idx: Optional[int], replay_events: List[dict])

        Core loop:
          1. For each step in cassette:
             a. Execute the recorded action via race_orchestrator
             b. Take screenshot, compute pHash
             c. Compare pHash to recorded value (Hamming distance)
             d. If mismatch (distance > threshold), stop and return
             e. Emit event for successful step
          2. If all steps matched, return success

        Errors are treated as mismatches (degrade to live execution).
        """
        replay_events: list[dict] = []

        if not self._cassette.steps:
            return (True, None, replay_events)

        for step_idx, step in enumerate(self._cassette.steps):
            try:
                # Replay: execute the recorded action
                outcome = await self._race_orchestrator.execute(
                    bundle_id=self._bundle_id,
                    target_key=step.action_canonical.target_key,
                    action_type=step.action_canonical.action_type,
                    payload=step.action_canonical.payload,
                    kind=step.action_canonical.kind,
                )

                # Verify: take screenshot, compute pHash
                current_snapshot = await self._l1_cheap.snapshot(
                    self._target_pid, self._bundle_id
                )
                current_phash = current_snapshot.get("phash")

                if current_phash is None:
                    # No baseline pHash — treat as mismatch
                    event = {
                        "event": "cassette_mismatch",
                        "step_idx": step_idx,
                        "reason": "missing_current_phash",
                    }
                    replay_events.append(event)
                    log.warning(f"Cassette replay mismatch at step {step_idx}: missing pHash")
                    return (False, step_idx, replay_events)

                # Match: compare pHash
                recorded_phash = step.screenshot_phash
                if recorded_phash is None:
                    event = {
                        "event": "cassette_mismatch",
                        "step_idx": step_idx,
                        "reason": "missing_recorded_phash",
                    }
                    replay_events.append(event)
                    log.warning(f"Cassette replay mismatch at step {step_idx}: no recorded pHash")
                    return (False, step_idx, replay_events)

                hamming = hamming_distance(recorded_phash, current_phash)
                if hamming > self._phash_threshold:
                    # Mismatch detected
                    event = {
                        "event": "cassette_mismatch",
                        "step_idx": step_idx,
                        "hamming": hamming,
                        "threshold": self._phash_threshold,
                        "recorded_phash": recorded_phash,
                        "current_phash": current_phash,
                    }
                    replay_events.append(event)
                    log.info(
                        f"Cassette replay mismatch at step {step_idx}: "
                        f"hamming {hamming} > {self._phash_threshold}"
                    )
                    return (False, step_idx, replay_events)

                # Match: continue to next step
                event = {
                    "event": "cassette_step_replay_ok",
                    "step_idx": step_idx,
                    "hamming": hamming,
                }
                replay_events.append(event)
                log.debug(f"Cassette replay step {step_idx} matched (hamming={hamming})")

            except Exception as e:
                # Error during replay or verification — treat as mismatch
                event = {
                    "event": "cassette_mismatch",
                    "step_idx": step_idx,
                    "reason": "replay_error",
                    "error": str(e),
                }
                replay_events.append(event)
                log.error(f"Cassette replay error at step {step_idx}: {e}")
                return (False, step_idx, replay_events)

        # All steps matched
        log.info(f"Cassette replay successful: all {len(self._cassette.steps)} steps matched")
        return (True, None, replay_events)
