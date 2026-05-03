"""Unit tests for build_dynamic_wrapper.

The proxy bug we're fixing: FastMCP's auto-schema treats `**kwargs` as
a single `kwargs: dict` field, so clients can't call proxied action-class
tools with the natural argument shape. The dynamic wrapper builds a
function whose signature mirrors the upstream tool's JSON Schema; FastMCP
then generates the right input model.

These tests pin two contracts:
  1. The wrapper's introspectable signature matches the schema.
  2. Calls into the wrapper flatten back into a kwargs dict for the runner.
"""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock

import pytest

from basicctrl.mcp_server.dynamic_wrapper import build_dynamic_wrapper


@pytest.mark.unit
class TestSignatureMirroring:
    def test_required_params_have_no_default(self):
        schema = {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "label": {"type": "string"},
            },
            "required": ["pid", "label"],
        }
        runner = AsyncMock(return_value={"ok": True})
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        sig = inspect.signature(fn)
        assert set(sig.parameters.keys()) == {"pid", "label"}
        assert sig.parameters["pid"].default is inspect.Parameter.empty
        assert sig.parameters["label"].default is inspect.Parameter.empty

    def test_optional_params_default_to_none(self):
        schema = {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
            },
            "required": ["pid"],
        }
        runner = AsyncMock(return_value=None)
        fn = build_dynamic_wrapper(
            tool_name="get_window_state", input_schema=schema, runner=runner
        )
        sig = inspect.signature(fn)
        assert sig.parameters["pid"].default is inspect.Parameter.empty
        assert sig.parameters["window_id"].default is None

    def test_optional_listed_before_required_still_compiles(self):
        """Schema lists `count` (optional) BEFORE `pid` (required). The
        generated function source must place required params first or
        Python rejects it with 'parameter without a default follows
        parameter with a default'."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "modifier": {"type": "array"},
                "pid": {"type": "integer"},
            },
            "required": ["pid"],
        }
        runner = AsyncMock(return_value="ok")
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        sig = inspect.signature(fn)
        # Required `pid` must precede the defaulted params in the signature.
        names = list(sig.parameters.keys())
        assert names.index("pid") < names.index("count")
        assert names.index("pid") < names.index("modifier")

    def test_param_types_propagate(self):
        schema = {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "ratio": {"type": "number"},
                "label": {"type": "string"},
                "pressed": {"type": "boolean"},
                "tags": {"type": "array"},
                "meta": {"type": "object"},
            },
            "required": ["x"],
        }
        runner = AsyncMock(return_value=None)
        fn = build_dynamic_wrapper(
            tool_name="t", input_schema=schema, runner=runner
        )
        sig = inspect.signature(fn)
        # Required `x` keeps its int annotation directly; optional params get
        # Optional[T] wrappers — we just confirm the names are present here.
        assert "x" in sig.parameters
        assert "ratio" in sig.parameters
        assert "label" in sig.parameters
        assert "pressed" in sig.parameters
        assert "tags" in sig.parameters
        assert "meta" in sig.parameters


@pytest.mark.unit
class TestCallBehavior:
    @pytest.mark.asyncio
    async def test_required_args_pass_through(self):
        runner = AsyncMock(return_value="ok")
        schema = {
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
        }
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        result = await fn(pid=12345)
        assert result == "ok"
        runner.assert_awaited_once_with({"pid": 12345})

    @pytest.mark.asyncio
    async def test_unset_optional_args_are_dropped(self):
        runner = AsyncMock(return_value="ok")
        schema = {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
                "label": {"type": "string"},
            },
            "required": ["pid"],
        }
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        await fn(pid=1)
        runner.assert_awaited_once_with({"pid": 1})

    @pytest.mark.asyncio
    async def test_set_optional_args_are_included(self):
        runner = AsyncMock(return_value="ok")
        schema = {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
                "element_index": {"type": "integer"},
            },
            "required": ["pid"],
        }
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        await fn(pid=1, window_id=42, element_index=13)
        runner.assert_awaited_once_with(
            {"pid": 1, "window_id": 42, "element_index": 13}
        )

    @pytest.mark.asyncio
    async def test_no_props_schema_yields_no_arg_wrapper(self):
        runner = AsyncMock(return_value="ok")
        fn = build_dynamic_wrapper(
            tool_name="status",
            input_schema={"type": "object", "properties": {}},
            runner=runner,
        )
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0
        await fn()
        runner.assert_awaited_once_with({})

    @pytest.mark.asyncio
    async def test_missing_required_raises_typeerror(self):
        runner = AsyncMock(return_value=None)
        schema = {
            "type": "object",
            "properties": {"pid": {"type": "integer"}},
            "required": ["pid"],
        }
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        with pytest.raises(TypeError):
            await fn()  # missing required pid


@pytest.mark.unit
class TestFallback:
    @pytest.mark.asyncio
    async def test_no_schema_uses_kwargs_fallback(self):
        runner = AsyncMock(return_value="ok")
        fn = build_dynamic_wrapper(
            tool_name="legacy", input_schema=None, runner=runner
        )
        # Fallback unwraps a single nested kwargs dict.
        await fn(kwargs={"a": 1, "b": 2})
        runner.assert_awaited_once_with({"a": 1, "b": 2})

    @pytest.mark.asyncio
    async def test_unparseable_schema_uses_kwargs_fallback(self):
        runner = AsyncMock(return_value=None)
        # All-non-identifier param names → fallback
        schema = {"type": "object", "properties": {"-bad-": {"type": "string"}}}
        fn = build_dynamic_wrapper(
            tool_name="weird", input_schema=schema, runner=runner
        )
        await fn(kwargs={"-bad-": "value"})
        runner.assert_awaited_once_with({"-bad-": "value"})


@pytest.mark.unit
class TestFastMCPIntrospection:
    """The whole point: FastMCP's func_metadata should produce a real input
    model from our wrapper, not the synthetic `kwargs: dict` field."""

    def test_func_metadata_extracts_named_fields(self):
        from mcp.server.fastmcp.utilities.func_metadata import func_metadata

        schema = {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
                "element_index": {"type": "integer"},
            },
            "required": ["pid"],
        }
        runner = AsyncMock(return_value=None)
        fn = build_dynamic_wrapper(
            tool_name="click", input_schema=schema, runner=runner
        )
        meta = func_metadata(fn)
        json_schema = meta.arg_model.model_json_schema(by_alias=True)
        props = json_schema.get("properties", {})
        # The bug we're fixing: a `**kwargs` wrapper makes this `{"kwargs": {...}}`.
        # The fix produces real top-level fields.
        assert "pid" in props
        assert "window_id" in props
        assert "element_index" in props
        assert "kwargs" not in props
        # Required propagates.
        assert "pid" in (json_schema.get("required") or [])
