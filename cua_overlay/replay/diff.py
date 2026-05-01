"""Session differ — LCS alignment of action_log.ndjson from two sessions."""
import json
from pathlib import Path
from typing import Optional, List, Tuple
from pydantic import BaseModel, Field


class DiffRow(BaseModel, frozen=True):
    """A single row in the diff output.

    Kinds:
    - 'common': same step in both sessions
    - 'added': new step in B only
    - 'removed': step removed from A
    - 'changed': same target, different outcome (e.g., failed→verified)
    - 'heal': changed with before_verdict=failed and after_verdict=verified
    """

    kind: str = Field(..., description="common, added, removed, changed, heal")
    step_idx_a: Optional[int] = None
    step_idx_b: Optional[int] = None
    action_a: Optional[dict] = None
    action_b: Optional[dict] = None
    before_verdict: Optional[str] = None  # For changed/heal rows
    after_verdict: Optional[str] = None   # For changed/heal rows
    heal_reason: Optional[str] = None


def lcs_alignment(seq_a: List[dict], seq_b: List[dict]) -> List[Tuple[Optional[int], Optional[int]]]:
    """Longest common subsequence alignment.

    Match key is (app, target_label, action_type) tuple.

    Returns list of (index_a, index_b) pairs:
    - (i, j): matched steps
    - (i, None): removed from A
    - (None, j): added in B
    """
    def match_key(action):
        return (action.get("app"), action.get("target_label"), action.get("action_type"))

    keys_a = [match_key(a) for a in seq_a]
    keys_b = [match_key(b) for b in seq_b]

    # DP table for LCS
    m, n = len(keys_a), len(keys_b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if keys_a[i - 1] == keys_b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # Backtrack to build alignment
    alignment = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and keys_a[i - 1] == keys_b[j - 1]:
            alignment.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
            alignment.append((None, j - 1))
            j -= 1
        else:
            alignment.append((i - 1, None))
            i -= 1

    return list(reversed(alignment))


class SessionDiffer:
    """Compare two session action_logs and generate diff."""

    def __init__(self, session_a_id: str, session_b_id: str):
        self.session_a = self._load_session(session_a_id)
        self.session_b = self._load_session(session_b_id)
        self.heals_a = self._load_heals(session_a_id)
        self.heals_b = self._load_heals(session_b_id)

    def _load_session(self, session_id: str) -> List[dict]:
        """Load action_log.ndjson from session directory."""
        path = Path.home() / ".cua" / "sessions" / session_id / "action_log.ndjson"
        actions = []
        if path.exists():
            with open(path) as f:
                for line in f:
                    if line.strip():
                        actions.append(json.loads(line))
        return actions

    def _load_heals(self, session_id: str) -> List[dict]:
        """Load heals.ndjson from session directory."""
        path = Path.home() / ".cua" / "sessions" / session_id / "heals.ndjson"
        heals = []
        if path.exists():
            with open(path) as f:
                for line in f:
                    if line.strip():
                        heals.append(json.loads(line))
        return heals

    def generate_diff(self) -> List[DiffRow]:
        """Generate diff output with alignment markers.

        Returns list of DiffRow objects with kinds: common, added, removed, changed, heal.
        """
        alignment = lcs_alignment(self.session_a, self.session_b)

        diff = []
        for idx_a, idx_b in alignment:
            if idx_a is not None and idx_b is not None:
                # Matched step — check for translator swap or outcome change
                action_a = self.session_a[idx_a]
                action_b = self.session_b[idx_b]

                # Detect changes: different tier or verdict
                tier_a = action_a.get("tier")
                tier_b = action_b.get("tier")
                verdict_a = action_a.get("verdict")
                verdict_b = action_b.get("verdict")

                if tier_a != tier_b or verdict_a != verdict_b:
                    # Changed step
                    is_heal = verdict_a == "failed" and verdict_b == "verified"

                    diff.append(DiffRow(
                        kind="heal" if is_heal else "changed",
                        step_idx_a=idx_a,
                        step_idx_b=idx_b,
                        action_a=action_a,
                        action_b=action_b,
                        before_verdict=verdict_a,
                        after_verdict=verdict_b,
                        heal_reason=f"{tier_a}→{tier_b}" if tier_a != tier_b else None,
                    ))
                else:
                    # No change
                    diff.append(DiffRow(
                        kind="common",
                        step_idx_a=idx_a,
                        step_idx_b=idx_b,
                        action_a=action_a,
                        action_b=action_b,
                    ))
            elif idx_a is not None:
                # Removed from A
                diff.append(DiffRow(
                    kind="removed",
                    step_idx_a=idx_a,
                    action_a=self.session_a[idx_a],
                ))
            else:
                # Added in B
                diff.append(DiffRow(
                    kind="added",
                    step_idx_b=idx_b,
                    action_b=self.session_b[idx_b],
                ))

        return diff
