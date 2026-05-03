"""LearningLoop — per-session ObservedAction buffer + flush_to_recipe.

Wires the existing `RecipeSynthesizer` + `EpisodicMemory` into the live
healing-tools path:

    healing_tools.click_with_healing → LearningLoop.record_action(...)
    register_task_complete(...)      → LearningLoop.flush_to_recipe(...)

Buffered ObservedAction entries are accumulated only when the verifier
returns `verified=True`. On flush, we synthesize a Recipe, embed the
(app, task_label) pair via `Embedder`, and index into FAISS so the next
session's `Planner.plan_action(... episodic_query=...)` can short-circuit
to the recipe instead of calling the LLM (D-20).
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from cua_overlay.learning.schemas import ObservedAction
from cua_overlay.state.causal_dag import ActionCanonical

log = structlog.get_logger(__name__)


@dataclass
class FlushResult:
    flushed: bool
    reason: str = ""
    recipe_name: Optional[str] = None
    app_bundle_id: Optional[str] = None
    task_class: Optional[str] = None
    state_fingerprint: Optional[str] = None
    step_count: int = 0


@dataclass
class LearningLoop:
    """Per-process buffer of successful ObservedAction entries.

    Caller threading model: healing tools drop into `record_action` from
    inside an asyncio task. Flushes happen from `register_task_complete`,
    also async. The internal `_buffer` is protected by an asyncio.Lock so
    concurrent click_with_healing calls in different MCP requests don't
    corrupt it.
    """

    embedder: Optional[Any] = None  # Embedder instance (duck-typed for tests)
    episodic: Optional[Any] = None  # EpisodicMemory (duck-typed for tests)
    synthesizer: Optional[Any] = None  # RecipeSynthesizer (duck-typed for tests)
    skills_root: Optional[Any] = None  # Override for auto-write target dir.
                                       # Production: `cua_overlay/skills/`.
                                       # Tests pass `tmp_path` so auto-write
                                       # doesn't pollute the real skills tree.
    _buffer: list[ObservedAction] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _step_idx: int = 0

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    async def record_action(
        self,
        action: ActionCanonical,
        verified: bool,
        gesture_type: str,
    ) -> None:
        """Append an ObservedAction iff the post-state verified.

        We only record successful actions: failed actions don't belong in a
        success recipe. The recovery_log captures failure context separately.
        """
        if not verified:
            return
        gt = gesture_type if gesture_type in {"keystroke", "click", "scroll"} else "click"
        async with self._lock:
            obs = ObservedAction(
                step_idx=self._step_idx,
                action=action,
                user_gesture_type=gt,  # type: ignore[arg-type]
                timestamp=time.time(),
                success=True,
                ax_delta=None,
            )
            self._buffer.append(obs)
            self._step_idx += 1

    async def flush_to_recipe(
        self,
        task_label: str,
        task_class: str,
        app_bundle_id: str,
        state_fingerprint: Optional[str] = None,
    ) -> FlushResult:
        """Synthesize a Recipe from the buffer and index into FAISS.

        Drops the buffer either way — partial flushes leave nothing behind.
        Returns FlushResult so callers (the MCP tool) can surface the
        outcome to the host.
        """
        async with self._lock:
            actions = list(self._buffer)
            self._buffer.clear()
            self._step_idx = 0

        if not actions:
            return FlushResult(flushed=False, reason="empty_buffer")

        if self.synthesizer is None or self.episodic is None or self.embedder is None:
            return FlushResult(
                flushed=False,
                reason="memory_components_unavailable",
            )

        recipe = await self.synthesizer.synthesize(
            observed_actions=actions,
            app_bundle_id=app_bundle_id,
            task_label=task_label,
        )

        # State fingerprint: SHA-256 of (bundle_id, task_class, action_count) by
        # default. Callers that have a richer state hash can pass one in.
        if state_fingerprint is None:
            state_fingerprint = hashlib.sha256(
                f"{app_bundle_id}|{task_class}|{len(actions)}".encode()
            ).hexdigest()

        from cua_overlay.agents.embedder import task_source_text

        action_summary = ",".join(
            a.action.action_type for a in actions[:10]  # cap at 10 for stable embed
        )
        source_text = task_source_text(app_bundle_id, task_label, action_summary)
        embedding = self.embedder.encode(source_text)

        await self.episodic.index_recipe(
            recipe=recipe,
            app_bundle_id=app_bundle_id,
            task_class=task_class,
            state_fingerprint=state_fingerprint,
            embedding=embedding,
            source_text=source_text,
        )

        # Fix #5: also persist a human-readable recipe markdown alongside
        # the FAISS row, so future planner prompts (which load
        # skills/<bundle>/*.md via skills.loader.read_all_skills) get
        # context about workflows we have already run successfully.
        try:
            self._auto_write_skill_md(
                app_bundle_id=app_bundle_id,
                task_class=task_class,
                task_label=task_label,
                actions=actions,
            )
        except Exception as exc:  # noqa: BLE001 — auto-write must never
            # block the recipe-index commit on FAISS.
            log.warning("learning_loop.skill_autowrite_failed", error=str(exc))

        log.info(
            "learning_loop.flushed",
            task_label=task_label,
            task_class=task_class,
            app_bundle_id=app_bundle_id,
            steps=len(actions),
            state_fingerprint=state_fingerprint[:12],
        )
        return FlushResult(
            flushed=True,
            reason="indexed",
            recipe_name=recipe.name,
            app_bundle_id=app_bundle_id,
            task_class=task_class,
            state_fingerprint=state_fingerprint,
            step_count=len(actions),
        )

    def _auto_write_skill_md(
        self,
        app_bundle_id: str,
        task_class: str,
        task_label: str,
        actions: list[ObservedAction],
    ) -> None:
        """Append a recipe markdown to `<skills_root>/<bundle>/<task_class>.md`.

        skills_root defaults to `cua_overlay/skills/` (production). Tests
        override via `LearningLoop(skills_root=tmp_path)` so they don't
        pollute the shipped skills tree.

        The format mirrors the human-curated skills (intent, AX shape,
        action sequence) so when the planner loads `read_all_skills(bundle)`
        it sees both hand-written and auto-discovered patterns. Each call
        appends a new run record so we don't clobber prior knowledge.
        """
        from datetime import datetime, timezone
        from pathlib import Path

        if self.skills_root is not None:
            base = Path(self.skills_root)
        else:
            base = Path(__file__).resolve().parent.parent / "skills"
        skills_dir = base / app_bundle_id
        skills_dir.mkdir(parents=True, exist_ok=True)
        path = skills_dir / f"{task_class}.md"

        steps_md_lines = []
        for i, obs in enumerate(actions, start=1):
            a = obs.action
            payload_summary = ""
            if isinstance(a.payload, dict):
                if "combo" in a.payload:
                    payload_summary = f' combo={a.payload["combo"]!r}'
                elif "text" in a.payload:
                    text_preview = str(a.payload["text"])[:60]
                    payload_summary = f' text={text_preview!r}'
                elif "label" in a.payload:
                    payload_summary = f' label={a.payload["label"]!r}'
            steps_md_lines.append(
                f"{i}. `{a.action_type}`{payload_summary}"
            )

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        block = (
            f"\n## Recipe: {task_label}\n\n"
            f"> Auto-recorded {ts} after a successful run "
            f"({len(actions)} step(s)).\n\n"
            f"### Steps\n\n"
            + "\n".join(steps_md_lines)
            + "\n"
        )

        if path.exists():
            existing = path.read_text(encoding="utf-8")
            # Avoid duplicating identical recipes back-to-back.
            if existing.rstrip().endswith(block.rstrip()):
                return
            path.write_text(existing + block, encoding="utf-8")
        else:
            header = (
                f"# {app_bundle_id} — {task_class}\n\n"
                f"> Auto-generated skill notes. Recipes below were captured "
                f"after successful task runs by the learning loop. Hand-curated "
                f"patterns may sit in sibling files in this directory.\n"
            )
            path.write_text(header + block, encoding="utf-8")
