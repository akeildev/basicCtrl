"""AX (Accessibility) safety primitives + observer bridge.

This subpackage's real implementation is split across two parallel Wave-2 plans:

- Plan 01-03 owns: ``element.py``, ``rate_limit.py``, ``walker.py``, ``modal_probe.py``, ``errors.py``
- Plan 01-04 owns: ``observer.py`` (AXEventBridge — CFRunLoop thread + asyncio Queue bridge)

The ``__init__.py`` does NOT re-export any names; downstream callers import from
the submodules directly. This avoids import-order races between the two parallel
worktrees during the wave merge.
"""
