"""Unit tests for LearningLoop + Embedder helpers.

We avoid loading the real sentence-transformers model in unit tests —
both because of cold-start cost (~3s) and to keep CI hermetic. The
embedder is duck-typed everywhere it matters, so a MagicMock with the
.encode signature is a faithful stand-in.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from cua_overlay.agents.embedder import task_source_text
from cua_overlay.agents.learning_loop import LearningLoop
from cua_overlay.state.causal_dag import ActionCanonical


def _make_action(target_key: str = "btn", action_type: str = "click") -> ActionCanonical:
    return ActionCanonical(
        id=f"act_{target_key}_{action_type}",
        step_idx=0,
        kind="MUTATE",
        target_key=target_key,
        action_type=action_type,
        payload={},
        timestamp_ns=int(time.monotonic_ns()),
        session_id="test_session",
    )


@pytest.mark.unit
class TestTaskSourceText:
    def test_includes_app_and_task(self):
        s = task_source_text("com.apple.calculator", "math_17x23")
        assert "com.apple.calculator" in s
        assert "math_17x23" in s

    def test_includes_action_summary_when_provided(self):
        s = task_source_text("X", "T", "click,click,type")
        assert "click,click,type" in s


@pytest.mark.unit
class TestLearningLoopRecord:
    @pytest.mark.asyncio
    async def test_record_drops_unverified_actions(self):
        loop = LearningLoop()
        await loop.record_action(_make_action(), verified=False, gesture_type="click")
        assert loop.buffer_size == 0

    @pytest.mark.asyncio
    async def test_record_appends_verified_actions(self):
        loop = LearningLoop()
        await loop.record_action(_make_action("a"), verified=True, gesture_type="click")
        await loop.record_action(_make_action("b"), verified=True, gesture_type="click")
        assert loop.buffer_size == 2

    @pytest.mark.asyncio
    async def test_record_normalizes_unknown_gesture_to_click(self):
        loop = LearningLoop()
        await loop.record_action(_make_action(), verified=True, gesture_type="bogus")
        assert loop.buffer_size == 1
        assert loop._buffer[0].user_gesture_type == "click"


@pytest.mark.unit
class TestLearningLoopFlush:
    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self):
        loop = LearningLoop()
        result = await loop.flush_to_recipe(
            task_label="t", task_class="c", app_bundle_id="app"
        )
        assert result.flushed is False
        assert result.reason == "empty_buffer"

    @pytest.mark.asyncio
    async def test_flush_without_components_returns_unavailable(self):
        loop = LearningLoop()
        await loop.record_action(_make_action(), verified=True, gesture_type="click")
        result = await loop.flush_to_recipe(
            task_label="t", task_class="c", app_bundle_id="app"
        )
        assert result.flushed is False
        assert result.reason == "memory_components_unavailable"

    @pytest.mark.asyncio
    async def test_flush_synthesizes_and_indexes(self, tmp_path):
        synth = MagicMock()
        recipe = MagicMock()
        recipe.name = "math_17x23"
        synth.synthesize = AsyncMock(return_value=recipe)

        episodic = MagicMock()
        episodic.index_recipe = AsyncMock(return_value=None)

        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=[0.1] * 384)

        loop = LearningLoop(
            embedder=embedder,
            episodic=episodic,
            synthesizer=synth,
            skills_root=tmp_path,
        )
        await loop.record_action(
            _make_action("ac"), verified=True, gesture_type="click"
        )
        await loop.record_action(
            _make_action("1"), verified=True, gesture_type="click"
        )

        result = await loop.flush_to_recipe(
            task_label="math_17x23",
            task_class="calculator_math",
            app_bundle_id="com.apple.calculator",
        )

        assert result.flushed is True
        assert result.recipe_name == "math_17x23"
        assert result.step_count == 2
        synth.synthesize.assert_awaited_once()
        episodic.index_recipe.assert_awaited_once()
        embedder.encode.assert_called_once()
        # Buffer drained after flush
        assert loop.buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_uses_caller_supplied_state_fingerprint(self, tmp_path):
        synth = MagicMock()
        synth.synthesize = AsyncMock(return_value=MagicMock(name="r"))
        episodic = MagicMock()
        episodic.index_recipe = AsyncMock()
        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=[0.0] * 384)

        loop = LearningLoop(
            embedder=embedder,
            episodic=episodic,
            synthesizer=synth,
            skills_root=tmp_path,
        )
        await loop.record_action(_make_action(), verified=True, gesture_type="click")

        await loop.flush_to_recipe(
            task_label="t",
            task_class="c",
            app_bundle_id="app",
            state_fingerprint="deadbeef",
        )
        kwargs = episodic.index_recipe.await_args.kwargs
        assert kwargs["state_fingerprint"] == "deadbeef"

    @pytest.mark.asyncio
    async def test_flush_auto_writes_skill_md(self, tmp_path):
        """Fix #5: a successful flush_to_recipe also persists a recipe
        markdown alongside the FAISS index, so the planner can pick it
        up via skills.loader.read_all_skills on future runs."""
        synth = MagicMock()
        synth.synthesize = AsyncMock(return_value=MagicMock(name="recipe"))
        episodic = MagicMock()
        episodic.index_recipe = AsyncMock(return_value=None)
        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=[0.0] * 384)

        loop = LearningLoop(
            embedder=embedder,
            episodic=episodic,
            synthesizer=synth,
            skills_root=tmp_path,
        )
        # Mix an action with a key combo + a typed-text action so the
        # generated markdown includes both flavors of payload summary.
        await loop.record_action(
            _make_action(target_key="cmd_n", action_type="key_combo:cmd+n"),
            verified=True,
            gesture_type="keystroke",
        )
        await loop.record_action(
            _make_action(target_key="text", action_type="type_into_focused"),
            verified=True,
            gesture_type="keystroke",
        )
        await loop.flush_to_recipe(
            task_label="add a calendar event",
            task_class="calendar_event_create",
            app_bundle_id="com.apple.iCal",
        )

        md_path = tmp_path / "com.apple.iCal" / "calendar_event_create.md"
        assert md_path.exists()
        body = md_path.read_text(encoding="utf-8")
        assert "Auto-generated skill notes" in body
        assert "add a calendar event" in body
        # Step list rendered the action_types we recorded.
        assert "key_combo:cmd+n" in body
        assert "type_into_focused" in body

    @pytest.mark.asyncio
    async def test_flush_appends_to_existing_skill_md(self, tmp_path):
        """Re-running the same task appends a new dated block instead of
        clobbering prior history."""
        synth = MagicMock()
        synth.synthesize = AsyncMock(return_value=MagicMock(name="recipe"))
        episodic = MagicMock()
        episodic.index_recipe = AsyncMock(return_value=None)
        embedder = MagicMock()
        embedder.encode = MagicMock(return_value=[0.0] * 384)

        loop = LearningLoop(
            embedder=embedder,
            episodic=episodic,
            synthesizer=synth,
            skills_root=tmp_path,
        )

        # Pre-seed a skill file as if a human had hand-written it.
        d = tmp_path / "com.apple.iCal"
        d.mkdir(parents=True)
        (d / "calendar_event_create.md").write_text(
            "# Hand-curated\n\nstable selectors etc.\n", encoding="utf-8"
        )

        await loop.record_action(
            _make_action(action_type="key_combo:cmd+n"),
            verified=True,
            gesture_type="keystroke",
        )
        await loop.flush_to_recipe(
            task_label="add a calendar event",
            task_class="calendar_event_create",
            app_bundle_id="com.apple.iCal",
        )
        body = (d / "calendar_event_create.md").read_text(encoding="utf-8")
        # Hand-curated content preserved.
        assert "Hand-curated" in body
        # New auto-recorded block appended.
        assert "Auto-recorded" in body
