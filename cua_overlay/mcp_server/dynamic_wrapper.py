"""Dynamic-signature wrapper builder for proxied upstream MCP tools.

FastMCP infers a Pydantic input model from the registered function's
signature via `inspect.signature(fn, eval_str=True)`. A function declared
as `_wrapped(**kwargs)` therefore exposes a single `kwargs: dict` field —
clients calling `session.call_tool("click", {"pid": 1, ...})` get a
"kwargs: Field required" validation error because the JSON-RPC arguments
don't match that synthetic model.

This module builds a wrapper function whose signature *mirrors* the
upstream tool's `inputSchema`. FastMCP's auto-schema then produces a
proper input model that accepts the natural argument shape.

Used by `proxy.py` for both passthrough and action-class wrappers.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import structlog

log = structlog.get_logger(__name__)

# JSON Schema primitive types → Python type names for code generation.
# We use string names rather than typing objects because the wrapper is
# built via `exec`; FastMCP re-evaluates annotations from the function
# globals so the names need to be importable in the exec namespace.
_JSON_TO_PY: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "array": "list",
    "null": "type(None)",
}


def _python_type_for(prop: dict[str, Any]) -> str:
    """Return a Python type expression (as a string) for a JSON Schema property.

    Falls back to `Any` for unions / enums / unknown types — those still
    serialize round-trip via JSON-RPC, we just lose schema fidelity.
    """
    t = prop.get("type")
    if isinstance(t, list):
        # Pydantic + FastMCP handle Union via typing.Union; keep simple.
        return "Any"
    if isinstance(t, str):
        return _JSON_TO_PY.get(t, "Any")
    return "Any"


def build_dynamic_wrapper(
    *,
    tool_name: str,
    input_schema: Optional[dict[str, Any]],
    runner: Callable[[dict[str, Any]], Awaitable[Any]],
    fallback_kwargs_name: str = "kwargs",
) -> Callable[..., Awaitable[Any]]:
    """Return an async function whose parameters match `input_schema`.

    The function collects its named arguments into a kwargs dict (dropping
    optional fields that were left unset / None) and awaits `runner(kwargs)`.

    Args:
        tool_name: Used in the generated function's `__name__` and in log
            messages — surfaces in MCP errors so clients can tell which
            tool the validation came from.
        input_schema: Upstream tool's JSON Schema (`tool.inputSchema`).
            When None or unparseable, falls back to a `**kwargs` shape
            (preserves existing behaviour for tools that don't ship a
            schema).
        runner: Async callable that takes the assembled kwargs dict and
            returns whatever the wrapper should yield to the host. The
            wrapper itself is dumb — it just collects args.
        fallback_kwargs_name: Used in the fallback shape only.

    Returns:
        An async function with annotations FastMCP can introspect.
    """
    if not input_schema or not isinstance(input_schema, dict):
        return _build_fallback_wrapper(tool_name, runner, fallback_kwargs_name)

    properties = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])

    if not properties:
        # No declared params — wrapper takes none, calls runner with {}.
        async def _no_args() -> Any:
            return await runner({})

        _no_args.__name__ = f"_proxied_{_safe_ident(tool_name)}"
        return _no_args

    # Build code text for a function whose parameters are the schema keys.
    # We split required (no default) and optional (defaulted to None) so
    # required args fail fast if missing.
    safe_names: list[tuple[str, str, bool]] = []  # (raw_name, py_type, required)
    for raw_name, prop in properties.items():
        if not isinstance(raw_name, str) or not raw_name.isidentifier():
            log.warning(
                "dynamic_wrapper.skipping_non_ident_param",
                tool_name=tool_name,
                param=raw_name,
            )
            continue
        py_type = _python_type_for(prop if isinstance(prop, dict) else {})
        is_required = raw_name in required
        safe_names.append((raw_name, py_type, is_required))

    if not safe_names:
        # All params had unsafe names — fall back to **kwargs.
        return _build_fallback_wrapper(tool_name, runner, fallback_kwargs_name)

    # Required params MUST come first in the generated signature so Python's
    # "no positional w/ default before one without" rule holds. We preserve
    # within-group order (matches schema property order) for stable signatures.
    safe_names.sort(key=lambda triple: 0 if triple[2] else 1)

    # Generate the function source. Required params take their type; optional
    # params take Optional[T] = None.
    sig_parts: list[str] = []
    body_parts: list[str] = ["    kwargs: dict = {}"]
    for raw_name, py_type, is_required in safe_names:
        if is_required:
            sig_parts.append(f"{raw_name}: {py_type}")
            body_parts.append(f"    kwargs[{raw_name!r}] = {raw_name}")
        else:
            sig_parts.append(f"{raw_name}: Optional[{py_type}] = None")
            body_parts.append(
                f"    if {raw_name} is not None: kwargs[{raw_name!r}] = {raw_name}"
            )

    fn_name = f"_proxied_{_safe_ident(tool_name)}"
    src = (
        f"async def {fn_name}({', '.join(sig_parts)}):\n"
        + "\n".join(body_parts)
        + "\n    return await _runner(kwargs)\n"
    )
    namespace: dict[str, Any] = {
        "Optional": Optional,
        "Any": Any,
        "_runner": runner,
        # The Python builtins below are referenced by name in annotations,
        # so they must be importable at exec-time.
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "dict": dict,
        "list": list,
    }
    try:
        exec(src, namespace)
    except SyntaxError as exc:
        log.warning(
            "dynamic_wrapper.exec_failed_falling_back",
            tool_name=tool_name,
            error=str(exc),
        )
        return _build_fallback_wrapper(tool_name, runner, fallback_kwargs_name)

    return namespace[fn_name]


def _build_fallback_wrapper(
    tool_name: str,
    runner: Callable[[dict[str, Any]], Awaitable[Any]],
    kwargs_name: str,
) -> Callable[..., Awaitable[Any]]:
    """Last-resort wrapper for tools without a usable schema.

    Generates a function whose only parameter is a typed `kwargs: dict`,
    so FastMCP's auto-schema produces a clean single-field input model
    (rather than the broken-and-cosmetic `**kwargs` shape). Hosts that
    don't have an upstream schema must still wrap real args inside the
    `kwargs` field — which matches the historical behaviour.
    """
    src = (
        f"async def _proxied_fallback_{_safe_ident(tool_name)}"
        f"({kwargs_name}: dict = None) -> Any:\n"
        f"    payload = {kwargs_name} or {{}}\n"
        f"    return await _runner(payload)\n"
    )
    namespace: dict[str, Any] = {"_runner": runner, "Any": Any, "dict": dict}
    exec(src, namespace)
    return namespace[f"_proxied_fallback_{_safe_ident(tool_name)}"]


def _safe_ident(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)
