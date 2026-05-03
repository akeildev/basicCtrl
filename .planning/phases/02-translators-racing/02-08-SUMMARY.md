---
phase: 02-translators-racing
plan: 08
subsystem: t4-vision-translator
tags: [TRANS-04, T4, uitag, ocrmac, asyncio, to_thread, D-05, D-06, D-08, D-14, Pitfall-C, A1, T-2-04]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: basicctrl.state.graph.UIElement + Bbox + Source.OCR + Source.PIXEL
  - phase: 02-translators-racing
    provides: basicctrl.translators.base (Translator Protocol, TranslatorTarget with grounded_bbox field, TargetSpec from Plan 02-04)
  - external: uitag==0.6.0 (D-05; verified PyPI 2026-04-09; pulls transformers>=5.0.0 transitively per D-08), ocrmac==1.0.1 (Phase 1 dep)
provides:
  - basicctrl.translators.t4_vision.T4VisionTranslator — concrete T4 translator (tier='T4') wrapping uitag.run_pipeline + ocrmac fallback
  - basicctrl.translators.t4_vision._detection_to_uielement — uitag.Detection → UIElement adapter (Source.OCR for vision_text, Source.PIXEL otherwise)
  - basicctrl.translators.t4_vision._score_detections — label-substring case-insensitive matching with highest-confidence tiebreak
  - 8 unit tests for T4 (mocked uitag PipelineResult/Detection via patch.dict + thread isolation assertion)
affects:
  - phase-02 plan 02-09 (T5 Pixel translator delegates coordinate resolution to T4 per D-07; T4 must ship first — now unblocked)
  - phase-02 plan 02-09 (C1 public CGEvent channel — T4's D-14 default channel binding lands in 02-09)
  - phase-02 plan 02-10 (race orchestrator wires T4+C1 alongside T1+C2, T2+C5, T3+C4 as fourth default tier-channel pair per D-14)
  - phase-02 plan 02-12 (Chess.app integration test — T4 logs image_width/image_height for A1 Retina ratio surfacing per T-2-04)

# Tech tracking
tech-stack:
  added: []  # uitag==0.6.0 + ocrmac==1.0.1 + transformers>=5.0.0 already pinned in pyproject.toml
  patterns:
    - "Translator Protocol implementation #4 — T4VisionTranslator implements Translator without nominal subclassing (duck-typed @runtime_checkable Protocol from Plan 02-04). Same shape as T1/T2/T3."
    - "Sync-API isolation pattern (Pitfall C) — uitag.run_pipeline is sync (Apple Vision + YOLO11 inference, 1-5s); wrapping it in asyncio.to_thread keeps the racing event loop responsive. Reusable for any future translator wrapping a sync ML pipeline (Phase 4 UI-TARS, Phase 4 V-Droid)."
    - "Lazy-import pattern for optional deps — `from uitag import run_pipeline` inside the to_thread closure means the import happens on first call, not module load. Test patch.dict(sys.modules, {'uitag': fake}) works cleanly. Same pattern as T3's lazy applescript import."
    - "Two-tier fallback chain — uitag (primary YOLO11 + Vision OCR) → ocrmac (text-only fallback when uitag returns no detections). Per RESEARCH Open Question 5 + A10 the third tier (geometric grid mapping for Chess.app) lands in Plan 02-12 as a test-side helper, not in this module."
    - "TDD strict per task — RED commit (failing tests) → GREEN commit (implementation). Same shape as Plans 02-05 / 02-06 / 02-07."

key-files:
  created:
    - "basicctrl/translators/t4_vision.py — T4VisionTranslator class; _screenshot_to_path uses CGWindowListCreateImage; _run_uitag wraps run_pipeline in asyncio.to_thread; _ocrmac_fallback wraps ocrmac.OCR.recognize() in asyncio.to_thread; _detection_to_uielement maps Detection fields to UIElement; _score_detections does label-substring matching"
  modified:
    - "basicctrl/translators/__init__.py — re-exports T4VisionTranslator alongside T1/T2/T3"
    - "tests/unit/translators/test_t4_vision.py — replaced Wave-0 importorskip stub with 8 mocked-uitag tests"

key-decisions:
  - "Lazy-import uitag inside the to_thread closure (not at module top-level) — keeps unit tests host-independent (no real uitag/transformers/MLX needed in CI), allows patch.dict(sys.modules, {'uitag': fake_module}) to override the import per test, and means T4VisionTranslator can be instantiated on any host without uitag installed (returns empty detections + falls to ocrmac). Same pattern as T3's lazy applescript import."
  - "_detection_to_uielement uses Source.OCR for det.source=='vision_text' and Source.PIXEL otherwise — this is the exact mapping from RESEARCH §Pattern 7 verbatim. ocr_text is populated only on vision_text (matches the semantic that pixel/yolo detections have no text content). The window_id=0 placeholder is correct for vision-grounded elements (no AX window association)."
  - "Label-substring case-insensitive scoring (rather than exact match) — pragmatic: uitag's label normalisation isn't documented; user-supplied target labels frequently differ in case/whitespace from detected labels. Highest-confidence tiebreak ensures the best detection wins when multiple candidates match (verified by test_score_detections_label_substring_case_insensitive: 'white pawn' matches 3 detections; 0.95-confidence wins over 0.7 even though 0.99 'black pawn' has higher score overall)."
  - "Empty-label TargetSpec returns highest-confidence overall (rather than None) — supports 'click here' / generic-target use cases where the caller just wants the most-prominent element. Tests verify (test_score_detections_picks_highest_confidence_no_label)."
  - "image_width/image_height logged at INFO level (not DEBUG) — A1 Retina verification depends on these dimensions being trivially greppable from session logs after the first Chess integration test runs. INFO matches Phase 1's structlog convention for 'data the user/operator may need to inspect'."
  - "ocrmac fallback unpacks bbox as normalised [0..1] coords — per ocrmac API docs (Phase 1 verifier already uses this). Multiplied by image_width/image_height to convert to pixel coords. If image dimensions unavailable (uitag failed entirely), bbox is used as-is (best-effort)."
  - "validate() returns True iff grounded_bbox is not None — vision-grounded coords are the only source of truth at fire time. No live-state pre-probe (would require a second screenshot + uitag run, doubling the resolve cost). The verifier's L1 pixel ROI dHash post-fire is the analogous validity check."

patterns-established:
  - "Wave-2 plan shape continues from 02-05 / 02-06 / 02-07: replace Wave-0 importorskip stub with TDD RED → GREEN per task. Plan 02-09 (T5 Pixel + C1 + C3) follows this exact shape — and per D-07 will compose this T4 instance for coordinate resolution."
  - "Lazy-import optional deps inside the work closure — when a translator wraps a heavy/optional library (uitag pulls transformers + MLX; applescript pulls OSAKit), put the import inside the function that uses it. Two benefits: (1) tests can patch.dict(sys.modules, {'name': fake}) without monkey-patching the translator module; (2) module imports stay fast and don't hard-fail when the optional dep is absent. Test-friendly + production-resilient."
  - "Two-tier fallback chain inside resolve() — primary path (uitag SoM) → fallback path (ocrmac OCR) → return None. The caller (race orchestrator) gets None and tries the next translator. No exceptions escape resolve(); errors are logged + swallowed. Same shape as T3's runtime_error capture in execute()."

requirements-completed:
  - TRANS-04

# Threats mitigated
threats_mitigated:
  - "T-2-04 uitag bbox origin: physical pixels vs logical points (Retina). Mitigated by emitting (image_width, image_height) at INFO level in `t4.uitag_completed` event on every resolve. First-integration Chess test (Plan 02-12) will compare these against Quartz screensize; if 2:1 ratio observed, RESEARCH A1 mitigation applies a divisor inside _detection_to_uielement (work item for Plan 02-12 if the ratio surfaces). Verification: tests/unit/translators/test_t4_vision.py::test_run_uitag_runs_in_to_thread asserts (iw=1024, ih=768) round-trip from PipelineResult."
  - "Pitfall C uitag-blocks-event-loop — T4._run_uitag wraps the synchronous run_pipeline in `await asyncio.to_thread(_sync)`, executing inference (1-5s wall time) on a worker thread. Race orchestrator's other channels (C1/C2/C5) make progress in parallel. Verified by test_run_uitag_runs_in_to_thread (asserts captured thread name != 'MainThread'). Same pattern applies to ocrmac fallback (also wrapped in asyncio.to_thread)."
  - "D-06 hard rule (no MacPaw/Screen2AX) — `grep -ci 'screen2ax\\|macpaw' basicctrl/translators/t4_vision.py` returns 0. Verified at acceptance-criteria check-time AND runtime-asserted by test_no_screen2ax_or_macpaw_imports (reads module source; asserts both literal and lower-case forms absent). Mitigates against accidental reintroduction during refactor."

# Metrics
duration: 4min
completed: 2026-04-30
---

# Phase 2 Plan 08: T4 Vision Translator Summary

**T4 Vision translator ships using uitag 0.6.0 (Apple Vision + YOLO11 MLX, 90.8% ScreenSpot-Pro) with ocrmac 1.0.1 fallback for OCR-only paths (Chess.app D-27 with 3D Metal board where uitag may return no detections). Per Pitfall C uitag.run_pipeline (sync, 1-5s inference) is wrapped in asyncio.to_thread to keep the racing event loop responsive. Per D-06 the synthetic-AX-tree research alternative is grep-enforced absent from the module — `grep -ci 'screen2ax|macpaw'` returns 0. Per A1 / T-2-04 every resolve logs (image_width, image_height) at INFO level so Plan 02-12's first-integration Chess test surfaces whether uitag returns physical pixels (2× Retina) or logical points; if mismatch observed, the RESEARCH-documented divisor lands in _detection_to_uielement as a follow-up work item.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-30T07:37:36Z
- **Completed:** 2026-04-30T07:40:00Z
- **Tasks:** 1 (`type=auto tdd=true`)
- **Files created:** 1 (basicctrl/translators/t4_vision.py)
- **Files modified:** 2 (basicctrl/translators/__init__.py, tests/unit/translators/test_t4_vision.py — replaced Wave-0 stub)

## Task Commits

1. **Task 1 RED — failing T4VisionTranslator unit tests:** `439007b` (test) — 8 tests; ModuleNotFoundError on import.
2. **Task 1 GREEN — T4VisionTranslator implementation:** `9cf992c` (feat) — 8/8 unit tests pass; full unit suite 222 passed (was 214 after 02-07).

## D-14 T4→C1 Default Binding (C1 lands in Plan 02-09)

Per CONTEXT.md D-14 the canonical Phase 2 default tier-channel mapping is:

| Tier | Channel | Method | Plan / Status |
|------|---------|--------|---------------|
| T1 (AX) | C2 (kAXPress) | `AXUIElementPerformAction(elem, "AXPress")` | 02-05 (shipped) |
| T2 (CDP) | C5 (Input.dispatchMouseEvent) | `cdp.send.Input.dispatchMouseEvent(mousePressed/mouseReleased)` | 02-06 (shipped) |
| T3 (AS) | C4 (AppleScript) | `applescript.AppleScript(source).run()` on cua-as ThreadPool | 02-07 (shipped) |
| **T4 (Vision)** | **C1 (CGEvent public)** | (Plan 02-09) | **02-08 ships T4; 02-09 ships C1** |
| T5 (Pixel) | C3 (CGEvent postToPid) | (Plan 02-09) | (Plan 02-09) |

This plan ships T4 only — C1 + C3 + T5 land together in Plan 02-09 (T5 delegates to T4 for coordinates per D-07; that's why T4 must ship first).

## T4 Resolution Flow

```
TargetSpec(label='white pawn')
   ↓
T4.resolve(bundle_id='com.apple.Chess', pid, target_spec)
   ↓
1. _screenshot_to_path(pid):
     CGWindowListCreateImage → CGImage → PIL.Image (RGBA, BGRA byte buffer)
     → save to tempfile.NamedTemporaryFile(suffix='.png', delete=False)
     ← returns Path or None on failure (Quartz unavailable / convert error)
   ↓ screenshot_path
2. _run_uitag(screenshot_path):     ← await asyncio.to_thread (Pitfall C)
     def _sync():
       from uitag import run_pipeline       ← lazy import (test-friendly)
       result, _ann, _man = run_pipeline(
         str(path),
         florence_task='<OD>',
         overlap_px=50, iou_threshold=0.5,
         recognition_level='accurate',
         use_yolo=True,
       )
       detections = list(result.detections or [])
       return (detections, result.image_width, result.image_height)
   ↓ (detections, image_width, image_height)
3. _log.info('t4.uitag_completed', detection_count, image_width, image_height)
   ↑ T-2-04 / A1: every resolve emits image dims for Retina ratio surfacing
   ↓
4. best = _score_detections(detections, target_spec)
     label_lower = target_spec.label.lower() = 'white pawn'
     candidates = [d for d in detections if 'white pawn' in d.label.lower()]
     return max(candidates, key=lambda d: d.confidence) if candidates else None
   ↓ best (uitag.Detection or None)
5. if best is None:
     ocr_matches = await _ocrmac_fallback(path, spec)  ← await asyncio.to_thread
       def _sync():
         import ocrmac                                 ← lazy
         results = ocrmac.OCR(str(path)).recognize()   ← list[(text, conf, bbox)]
         return [r for r in results if 'white pawn' in r[0].lower()]
     if not ocr_matches:
       _log.info('t4.no_match', label='white pawn')
       return None                                     ← caller falls to next translator
     # Use ocr_matches[0] → TranslatorTarget(element=UIElement(source=[OCR], ...))
   ↓
6. elem = _detection_to_uielement(best, pid, bundle_id)
     Source.OCR if best.source=='vision_text' else Source.PIXEL
     UIElement(role='AXUnknown', role_path=f'AXVision/{best.source}[{best.som_id}]', ...)
   ↓
7. return TranslatorTarget(element=elem, grounded_bbox=elem.bbox)
   ↓ caller (race orchestrator) routes to channel C1 per D-14 default binding
```

## D-06 Hard Rule Verification

The plan's acceptance criteria specify `grep -ci 'screen2ax\|macpaw' basicctrl/translators/t4_vision.py` returns **0**.

Initial GREEN draft contained the literal `MacPaw / Screen2AX` in the module docstring (rationale prose: "NO MacPaw/Screen2AX in Phase 2 — research repo, conflicts with pyobjc 12.1, not on PyPI"). The grep correctly flagged it as 1. Same shape as Plan 02-06's D-03 grep deviation and Plan 02-07's D-04 grep deviation (docstring prose triggers grep-enforced rules).

**Fix:** Rephrased docstring to "the synthetic-AX-tree research alternative is OUT OF SCOPE in Phase 2 — research repo, conflicts with pyobjc 12.1, not on PyPI". Preserved the D-06 reference for human readers; removed the grep-flagged literals. Verified post-edit: `grep -ci 'screen2ax|macpaw'` returns 0.

This is now the canonical pattern for D-XX hard rules: when the rule is grep-enforced, the rule reference must be by D-number, NOT by quoted forbidden term. Documented in this Summary's Deviations section.

## Files Created/Modified

### Created
- `basicctrl/translators/t4_vision.py` (~290 lines) — T4VisionTranslator
  - `tier: Literal["T1"-"T5"] = "T4"` Protocol field
  - `_screenshot_to_path(pid)` — CGWindowListCreateImage → PIL.Image → temp PNG
  - `_run_uitag(path)` — `asyncio.to_thread(_sync)` wrapping `from uitag import run_pipeline`
  - `_ocrmac_fallback(path, spec)` — `asyncio.to_thread(_sync)` wrapping `ocrmac.OCR(path).recognize()`
  - `_detection_to_uielement(det, pid, bundle_id)` — Source.OCR / Source.PIXEL adapter
  - `_score_detections(detections, spec)` — label-substring case-insensitive + highest-confidence tiebreak
  - `resolve(bundle_id, pid, target_spec)` — full flow: screenshot → uitag → score → ocrmac fallback → adapt
  - `validate(target)` — `grounded_bbox is not None`

### Modified
- `basicctrl/translators/__init__.py` — adds `T4VisionTranslator` re-export and to `__all__`
- `tests/unit/translators/test_t4_vision.py` — replaced Wave-0 importorskip stub with 8 mocked-uitag tests

## Acceptance Criteria — All PASS

| Literal | Required | Found |
|---------|----------|-------|
| `class T4VisionTranslator` in t4_vision.py | YES | 1 |
| `from uitag import run_pipeline` | YES | 1 |
| `asyncio.to_thread` | YES | 3 |
| `ocrmac` | YES | 13 |
| `image_width` (T-2-04 / A1 logging) | YES | 7 |
| `T4VisionTranslator` re-exported in __init__.py | YES | YES |
| `grep -ci 'screen2ax\|macpaw'` returns | 0 | 0 |
| `uv run pytest -q tests/unit/translators/test_t4_vision.py` | 8 passed | 8 passed |
| `uv run python -c "from basicctrl.translators import T4VisionTranslator; print(T4VisionTranslator().tier)"` prints | T4 | T4 |
| Full unit suite (was 214 after 02-07) | +8 = 222 | 222 passed, 8 skipped, 29 deselected |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-06 grep-enforced 'Screen2AX/MacPaw' literals in module docstring**
- **Found during:** Task 1 GREEN (acceptance criteria check)
- **Issue:** Module docstring contained the literal `MacPaw / Screen2AX` substring in prose ("NO MacPaw/Screen2AX in Phase 2 — research repo..."), which the strict acceptance criterion `grep -ci 'screen2ax\|macpaw' basicctrl/translators/t4_vision.py` correctly flagged as 1 (must be 0). Same shape as Plan 02-06's D-03 grep deviation (`browser_harness` in docstring) and Plan 02-07's D-04 grep deviation (`osascript` in docstring).
- **Fix:** Rephrased docstring to "the synthetic-AX-tree research alternative is OUT OF SCOPE in Phase 2 — research repo, conflicts with pyobjc 12.1, not on PyPI". Preserved the D-06 reference for human readers.
- **Files modified:** `basicctrl/translators/t4_vision.py` (docstring only)
- **Commit:** `9cf992c` (rolled into Task 1 GREEN since the file hadn't been committed yet between bug discovery and fix)

## Issues Encountered

- **PreToolUse:Edit / PreToolUse:Write hook re-prompts** — runtime asks the agent to re-read files between edits. All files had been Read at the start of the session OR Written in the same session. Edits succeeded as confirmed by post-edit `pytest` and `grep` runs. No content changes lost.
- **No real Chess.app integration test in this plan** — per the plan's success criteria + Phase 2 wave structure, real-app integration tests live in Plan 02-12 (Chess.app T4 SoM + T5 CGEvent fires per D-27). This plan ships the unit-tested T4; 02-12 will exercise it against a running Chess.app and surface the A1 Retina ratio.

## User Setup Required

None for unit tests — they run on any host. The uitag and ocrmac modules are mocked via `patch.dict('sys.modules', {'uitag': fake_module})` so the real PyObjC Vision + MLX YOLO11 path isn't touched in tests.

For Plan 02-12's eventual Chess integration test (D-27):
- macOS Screen Recording TCC granted to the Python interpreter (system prompt fires once on first CGWindowListCreateImage call from this binary)
- Chess.app pre-installed (`/System/Applications/Chess.app` — system app)
- First run will populate the model cache for uitag's bundled YOLO11 weights (~18 MB) and Florence-2 task prompts; ANE inference time after warmup is 200-800ms typical; CPU fallback is 1-5s

## Next Plan Readiness

- **Plan 02-09 (T5 Pixel + C1 public CGEvent + C3 CGEvent.postToPid):** T5 imports T4VisionTranslator and constructs/composes it for coordinate resolution per D-07. T4 already shipped — Plan 02-09 unblocked. C1 + C3 follow the C2/C5/C4 channel shape (try_claim → cancel-check → fire). Per RESEARCH §Pattern 8 + Pitfall I (CGEvent.postToPid cursor warp) the channels need careful event source construction.
- **Plan 02-10 (race orchestrator):** wires `TranslatorRegistry.select_for_priority(profile.translator_priority)` against `ChannelRegistry.select(priority, race_policy)` with `IdempotencyTokenStore` + `cancel_event`. Four default-binding pairs ready after Plan 02-09: T1+C2, T2+C5, T3+C4, T4+C1, T5+C3.
- **Plan 02-12 (Chess T4 SoM + T5 CGEvent fires integration test, D-27):** T4 logs (image_width, image_height) on every resolve — the first run on Akeil's Retina display will surface whether the dims match Quartz screensize (1:1 logical points) or are 2× (physical pixels). If 2:1, the divisor patch lands in `_detection_to_uielement` as a follow-up. The three-tier fallback (uitag → ocrmac → geometric 8×8 grid) is implemented across this plan + the test fixture.
- **No blockers.** All 8 unit tests pass; full unit suite 222 passed.

## Self-Check: PASSED

Files created (verified via `[ -f path ]`):
- FOUND: `basicctrl/translators/t4_vision.py`

Files modified (verified):
- FOUND: `basicctrl/translators/__init__.py` (re-exports T4VisionTranslator)
- FOUND: `tests/unit/translators/test_t4_vision.py` (replaced Wave-0 stub with 8 mocked tests)

Commits verified (all in `git log --oneline`):
- FOUND: `439007b` test(02-08): RED T4VisionTranslator unit tests
- FOUND: `9cf992c` feat(02-08): GREEN T4VisionTranslator (uitag + ocrmac fallback)

Acceptance criteria literals (all greppable, verified):
- FOUND: `class T4VisionTranslator`, `from uitag import run_pipeline`, `asyncio.to_thread`, `ocrmac`, `image_width` in `basicctrl/translators/t4_vision.py`
- VERIFIED: `grep -ci 'screen2ax|macpaw' basicctrl/translators/t4_vision.py` returns 0 (D-06 hard rule)
- FOUND: `T4VisionTranslator` in `basicctrl/translators/__init__.py`

Verification commands (all pass):
- `uv run pytest -q tests/unit/translators/test_t4_vision.py` → 8 passed in 0.07s
- `uv run python -c "from basicctrl.translators import T4VisionTranslator; print(T4VisionTranslator().tier)"` → `T4`
- `grep -ci "screen2ax|macpaw" basicctrl/translators/t4_vision.py` → 0
- `SKIP_INTEGRATION=1 uv run pytest -q tests/ -m "not integration and not manual"` → 222 passed, 8 skipped, 29 deselected in 1.10s (was 214 after 02-07; +8 from this plan's 8 T4 unit tests)

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
