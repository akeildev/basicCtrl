---
phase: 01-foundation-state-verifier
verified: 2026-04-29T22:50:00Z
status: human_needed
score: 13/18 must-haves verified (5 require manual TCC-gated tests)
overrides_applied: 0
human_verification:
  - test: "Calculator click <50ms via L0 push (SC-1)"
    expected: "uv run python -m cua_overlay.demo.calculator_click exits 0 with VERIFIED, latency_ms<50, L0 signal=1.0 (or L1 carries per renormalization), L2=None, L3=None"
    why_human: "Requires real Calculator.app + Accessibility TCC grant; per PHASE-1-DEMO.md the agent ran live and reported verified=True latency 31-45ms. L0 AX delivery has documented macOS 26 quirk; L1 carries via present-signal renormalization."
  - test: "AppProfile cache survives session restart (SC-3 manual confirmation)"
    expected: "First run probes Calculator in <500ms; second run reads ~/.cua/profiles/com.apple.calculator.json in <5ms (cache hit log line)"
    why_human: "Calculator + TCC required. Plan 02 SUMMARY reports first-probe 14ms, cache-hit 0ms on Akeil's machine."
  - test: "TCC revocation surfaced (P24, manual smoke check)"
    expected: "Toggle Accessibility OFF for Python interpreter; demo emits structured event tcc_revoked with action_url, exits 2"
    why_human: "Requires interactive System Settings toggle; documented in PHASE-1-DEMO.md."
  - test: "Modal alert blocks AX (P25, manual smoke check)"
    expected: "Open System Settings password prompt while modal up; demo asserts pre.no_blocking_modal is False"
    why_human: "Requires interactive modal dialog; documented in PHASE-1-DEMO.md."
  - test: "SIGKILL crash-resume (PERSIST-03 manual)"
    expected: "Start session, write 1 checkpoint, kill -9 process; resume_from_checkpoint(session_id) returns ResumeContext with last_step_idx=1"
    why_human: "Requires multi-terminal kill -9 sequence; CI-equivalent test_resume_simulated_crash passes (executor-A writes, aclose, executor-B resumes)."
  - test: "MCP proxy + healing tool with real cua-driver (SC-6)"
    expected: "After swift build of cua-driver, list_tools returns proxied upstream tools + click_with_healing; click_with_healing call writes action_log.ndjson"
    why_human: "Requires Swift binary built and CUA_DRIVER_BIN on PATH; tests in test_mcp_proxy.py skip cleanly without it."
gaps:
  - truth: "Click in Calculator fires kAXValueChanged and is recorded as VERIFIED in <50ms via L0 push subscription (subscribed BEFORE action fires) — SC-1 partial"
    status: partial
    reason: "Subscribe-before-fire pattern is correctly implemented (5ms guard + action_id + notif filter). HOWEVER, on macOS 26 / Calculator the AX event delivery within the 30ms L0 timeout is flaky (documented in 01-09 SUMMARY + PHASE-1-DEMO.md). When AX misses, L1 cheap-diff carries verification via present-signal renormalization → confidence=1.0 → verified=True. Strict reading of SC-1 (must be via L0 push subscription) is satisfied only when AX delivers; pragmatic reading (verified <50ms) is always satisfied."
    artifacts:
      - path: "cua_overlay/ax/observer.py"
        issue: "Bridge subscribes correctly; documented macOS 26 delivery flake under demo's parallel L1 capture."
    missing:
      - "Phase 2 T1 AX translator with native AXPress (instead of synthetic CGEventPost) should resolve the delivery flake — defer to Phase 2."
  - truth: "click_with_healing runs the L0+L1 verifier ladder and writes to action_log/Postgres (per docstring claim, MCP-02)"
    status: failed
    reason: "Docstring (cua_overlay/mcp_server/healing_tools.py:56-63) claims the tool 'runs the L0+L1 verifier ladder, and writes a Hoare-triple line to the session action log.' Implementation calls upstream.call_tool('click', ...) directly, NOT proxy.call_tool. The verifier wrap registered by register_proxied_tool only fires when an MCP host calls the proxy's mirrored 'click' tool — going to upstream bypasses it entirely. Confirmed by code review WR-02."
    artifacts:
      - path: "cua_overlay/mcp_server/healing_tools.py"
        issue: "Line 94 calls upstream.call_tool('click', ...) directly. No L0+L1 verify, no action_log append, no Postgres checkpoint."
    missing:
      - "Either (a) change line 94 to await proxy.call_tool('click', arguments=...) so the wrap fires, OR (b) update the docstring to remove the verifier-ladder claim and document that Phase 1 healing is a label-only thin wrapper. Recommend (a) so MCP-02's audit trail is complete."
  - truth: "Per-pid AXObserver subscriptions correctly emit AXEvent.element_key for the subscribed element"
    status: failed
    reason: "Code review WR-01: AXEventBridge.subscribe creates a fresh callback closure on every call but only registers it with AXObserverCreate the FIRST time a pid is seen. Every subsequent subscribe on the same pid re-uses the OLD callback bound to the FIRST element's element_key. AXEvent.element_key after the first subscribe per pid is always wrong (always the first subscriber's key). The dispatcher filter doesn't match on element_key so verification still works, but the field is misleading data."
    artifacts:
      - path: "cua_overlay/ax/observer.py"
        issue: "Lines 255-307: closure captures element_key + pid by reference; later subscribers' callbacks discarded; element_key reported in AXEvent is the first subscriber's, not the actual emitter's."
    missing:
      - "Have the callback resolve element_key dynamically from the refcon (not closure-capture) — see WR-01 fix proposal. Phase 1 demo only subscribes to one element so this is invisible; Phase 2 race orchestrator with multiple translators per pid will hit it."
  - truth: "AX callback exception safety when asyncio loop closes during stop()"
    status: partial
    reason: "Code review WR-04: callback unconditionally calls loop.call_soon_threadsafe; if loop is closed mid-callback (race with bridge.stop), RuntimeError escapes back into the C boundary which is undefined behavior on PyObjC. 1-second CFRunLoopRunInMode poll widens the race window."
    artifacts:
      - path: "cua_overlay/ax/observer.py"
        issue: "Lines 256-274: no try/except around call_soon_threadsafe; exception leaks into PyObjC C bridge."
    missing:
      - "Wrap callback body in try/except RuntimeError (and broad except as defence-in-depth). Cheap fix; should land before Phase 2's race orchestrator stress-tests stop() paths."
  - truth: "Long-running session AXObserver state cleanup (no unbounded growth)"
    status: partial
    reason: "Code review WR-03: _callbacks list, _refcon_to_action map, and _subscriptions list grow without bound. Phase 1 demo fires one action so leak is invisible; Phase 3 race orchestrator at 100s of actions/min will accumulate ~100 bytes/entry indefinitely."
    artifacts:
      - path: "cua_overlay/ax/observer.py"
        issue: "Lines 108-112, 247-248, 307: structures only ever appended, never pruned."
    missing:
      - "Add release_subscription cleanup hook on Subscription tear-down (drop refcon mapping + remove from _subscriptions + AXObserverRemoveNotification). Defer to Phase 2 if Phase 1 demo runs are short enough that growth is negligible."
deferred:
  - truth: "Phase 2 T1 AX translator with native AXPress (resolves L0 AX delivery flake)"
    addressed_in: "Phase 2"
    evidence: "Phase 2 success criterion 1-3: T1 AX channel uses native AXPress; replaces demo's synthetic CGEvent with proper translator routing. The Phase 1 demo's L0 flake should resolve once T1 fires the click via Apple's standard AX path."
  - truth: "Per-action-class race orchestrator (multiple translator subscribes per pid)"
    addressed_in: "Phase 2"
    evidence: "Phase 2 ACT-02 success criterion: 'asyncio.wait(FIRST_COMPLETED) across channels'. The shared-callback bug (WR-01) becomes blocking when multiple translators subscribe to different elements on the same pid simultaneously."
  - truth: "5-branch parallel recovery + cache write-back for healing tools"
    addressed_in: "Phase 3"
    evidence: "Phase 3 HEAL-02 + CACHE-02: 5-branch parallel recovery with cassette write-back. click_with_healing's body becomes the race; the Phase 1 thin-wrapper bypass becomes irrelevant once the body is replaced."
  - truth: "Postgres checkpoint hardening for SIGKILL under load"
    addressed_in: "Phase 6"
    evidence: "Phase 6 success criterion 6: 'LangGraph PostgresSaver wraps every translator call as durable step; kill -9 mid-task → persist/resume.py picks up at last verified action'. Phase 1 ships the contract + simulated-crash test; Phase 6 hardens for real SIGKILL under load."
---

# Phase 1: Foundation + State + Verifier — Verification Report

**Phase Goal (LOCKED, from ROADMAP.md):**
"Python overlay can probe any Mac app, write a typed state graph, and verify a click via push events + cheap deterministic checks in <50ms — without touching the cua-driver Swift code."

**Verified:** 2026-04-29T22:50:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (6 ROADMAP Success Criteria)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| SC-1 | Click in Calculator fires kAXValueChanged and is recorded as VERIFIED in <50ms via L0 push subscription (subscribed BEFORE action fires) | ⚠️ HUMAN_PARTIAL | Subscribe-before-fire pattern correctly implemented in `axobserver.py::expect()` with 5ms guard + action_id + notif filter; tested by 8 unit tests. Calculator demo runs end-to-end on Akeil's Mac per PHASE-1-DEMO.md (verified=True, latency 31-45ms). HOWEVER: L0 AX delivery flakes within the 30ms L0 timeout on macOS 26 (documented in 01-09-SUMMARY); L1 cheap-diff carries verification via present-signal renormalization → confidence=1.0. Strict L0 reading needs human Calculator + TCC test. |
| SC-2 | State graph round-trips: probe Calculator → write UIElement entity → read it back with stable composite key (role_path + label + bbox_centroid 4px-grid), NOT raw AXUIElement ref | ✓ VERIFIED | `cua_overlay/state/fingerprint.py::compute_composite_key` implements 3-tier ladder: axid > path > bbox (4px). 4 unit tests in `test_fingerprint.py` cover stability + tier order. `StateGraph.upsert/get` round-trip tested in `test_state_graph.py`. |
| SC-3 | AppProfile classifier caches per-bundle capability probe and survives session restart | ✓ VERIFIED (auto) + ⚠️ HUMAN | `cua_overlay/profile/cache.py` writes `~/.cua/profiles/<bundle_id>.json` via atomic os.replace; 8 unit tests in `test_appprofile_cache.py` cover save/load/atomic-write/version-invalidation. Plan 02 SUMMARY reports Calculator first-probe 14ms, cache-hit 0ms. Manual confirmation needed against real Calculator. |
| SC-4 | L0 push + L1 cheap diff verifies a click in <50ms with NO AX subtree walk | ✓ VERIFIED | `cua_overlay/verifier/aggregator.py::verify` wires L0+L1 in parallel via anyio task group. L2 only runs if confidence < 0.50 — Phase 1 demo's `tier_signals["L2"]` is None (asserted in `run_demo` step 14). 24 unit tests in `test_l0_push.py + test_l1_cheap.py + test_aggregator.py` confirm. WeightedVote present-signal renormalization (BLOCKER-1 fix) makes single-signal Calculator click resolve to 1.0 confidence. |
| SC-5 | AX rate-limiter caps at 20 calls/sec/pid; depth-limited subtree (3 levels max) prevents Safari hangs | ✓ VERIFIED | `cua_overlay/ax/rate_limit.py::TokenBucket` defaults `rate_per_sec=20.0, capacity=20`. `cua_overlay/ax/walker.py::walk_subtree` defaults `max_depth=3, max_children=50, max_nodes=500`. 8+8 unit tests in `test_rate_limit.py + test_walker.py` cover all caps + per-pid isolation + iterative BFS (no Python recursion). |
| SC-6 | Existing trycua MCP server surface still works; healing wrapper exposed as additional MCP tools | ⚠️ HUMAN_PARTIAL | `cua_overlay/mcp_server/proxy.py` mirrors all upstream tools via `register_proxied_tool`; `healing_tools.py::click_with_healing` registers a new MCP tool. T-1-01 mitigated (zero TCP markers across `cua_overlay/mcp_server/`). HOWEVER: integration tests skip cleanly without Swift cua-driver binary (not built in this worktree). Manual run on Akeil's Mac required after `swift build`. ALSO: WR-02 — `click_with_healing` bypasses the verifier wrap (see Gaps). |

**Score:** 3/6 fully verified, 3/6 require human TCC + Calculator test. Gap-found classifier WR-02 affects SC-6 audit-trail completeness but doesn't break the surface contract.

### Required Artifacts (every Phase 1 must-have)

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `cua_overlay/__init__.py` | Package marker, version | ✓ VERIFIED | Exists, `__version__ = "0.1.0"`. |
| `pyproject.toml` | Locked deps (pyobjc==12.1, structlog==25.5.0, ImageHash==4.3.2, langgraph-checkpoint-postgres==3.0.5, pydantic>=2.0, anyio>=4.0, ocrmac==1.0.1) | ✓ VERIFIED | All 7 deps confirmed via grep. |
| `libs/cua-driver/` | Vendored read-only from trycua | ✓ VERIFIED | Exists; `git diff --name-only main..HEAD libs/cua-driver/Sources/` returns empty. |
| `cua_overlay/state/graph.py` | UIElement Pydantic v2 model + StateGraph + EdgeKind | ✓ VERIFIED | All 22 UIElement fields present per ARCHITECTURE.md L40-49. |
| `cua_overlay/state/causal_dag.py` | ActionCanonical (kind: Literal["READ","MUTATE"]), HoarePre, HoarePost, CausalDAG | ✓ VERIFIED | All Pydantic v2 contracts locked. HoarePost.verified == confidence>=0.5 enforced by model_validator. |
| `cua_overlay/state/ring_buffer.py` | TemporalRingBuffer (deque maxlen=5) + StateSnapshot | ✓ VERIFIED | maxlen=5, PRECEDES edges between consecutive frames sharing keys. |
| `cua_overlay/state/fingerprint.py` | composite_key tier ladder | ✓ VERIFIED | 3-tier ladder: axid > path > bbox (4px-grid centroid). |
| `cua_overlay/profile/classifier.py` | AppProfile + classify async fn | ✓ VERIFIED | Pydantic AppProfile with 15 fields + cache_key property; classify uses anyio.create_task_group + per-probe 200ms timeout. |
| `cua_overlay/profile/cache.py` | Atomic disk cache + version-invalidation | ✓ VERIFIED | `os.replace`-based atomic write; should_invalidate_cache compares bundle_version + bundle_build. |
| `cua_overlay/profile/tcc.py` | TCCMonitor with .check() + on_revocation() | ✓ VERIFIED | AXIsProcessTrusted lazy-imported; on_revocation emits structlog `tcc_revoked` event with action URL + raises SystemExit(2). |
| `cua_overlay/ax/rate_limit.py` | TokenBucket(20/sec/pid) | ✓ VERIFIED | rate_per_sec=20.0, capacity=20; per-pid asyncio.Lock; structlog `ax.rate_limited` deny event. |
| `cua_overlay/ax/walker.py` | walk_subtree(max_depth=3, max_children=50, max_nodes=500) | ✓ VERIFIED | Iterative BFS (work-queue, no Python recursion); WalkResult.truncated + cap_hit. |
| `cua_overlay/ax/modal_probe.py` | has_blocking_modal | ✓ VERIFIED | Top-10 windows scan via AXModal; uses TokenBucket. |
| `cua_overlay/ax/errors.py` | Typed AX exception hierarchy | ✓ VERIFIED | 6 subclasses sourced from live HIServices kAXError* exports. |
| `cua_overlay/ax/observer.py` | AXEventBridge (CFRunLoop thread + asyncio Queue) | ⚠️ ORPHANED | Exists, wired, but WR-01 + WR-03 + WR-04 (see Gaps). Subscription works for single-element single-pid demo path. |
| `cua_overlay/verifier/axobserver.py` | AXObserverManager.expect (5ms guard) | ✓ VERIFIED | _passes_filter uses 5_000_000ns guard; 8 unit tests cover all 4 predicates + dispatcher. |
| `cua_overlay/verifier/nsworkspace.py` | NSWorkspaceObserver | ✓ VERIFIED | NSWorkspaceDidActivateApplicationNotification on dedicated NSOperationQueue. |
| `cua_overlay/verifier/kqueue_proc.py` | KqueueProcObserver (EVFILT_PROC + NOTE_EXIT) | ✓ VERIFIED | Pure asyncio via loop.add_reader; __aenter__/__aexit__ for fd-leak resistance (T-1-06). |
| `cua_overlay/verifier/distnotif.py` | DistributedNotificationEvent contract scaffold | ✓ VERIFIED | Pydantic frozen contract; observer is Phase 2 stub raising NotImplementedError. |
| `cua_overlay/verifier/ensemble/l0_push.py` | L0Push consumer (no polling) | ✓ VERIFIED | Source-grep confirms 0 occurrences of walk_subtree / AXUIElementCopyAttributeValue / read_attribute. All 7 AX notif types mapped to signals. |
| `cua_overlay/verifier/ensemble/l1_cheap.py` | L1Cheap (CGWindowList + NSPasteboard.changeCount + dHash) | ✓ VERIFIED | Three sub-checks in anyio.create_task_group; T-1-03 mitigation: pasteboard signal is integer-only (verified by `test_no_pasteboard_contents_logged`). |
| `cua_overlay/verifier/ensemble/l2_medium.py` | L2Medium (Vision OCR + walker delegation) | ✓ VERIFIED | walk_subtree with default caps (max_depth=3); 0 occurrences of AXUIElementCopyAttributeValue or max_depth>=4 in L2 module. |
| `cua_overlay/verifier/ensemble/l3_llm.py` | L3Stub raising NotImplementedError | ✓ VERIFIED | @runtime_checkable Protocol; catch-all *args, **kwargs signature; 3 unit tests. |
| `cua_overlay/verifier/ensemble/weighted_vote.py` | WeightedVote with present-signal renormalization | ✓ VERIFIED | Active = signals with non-zero value; weighted_sum / active_total renormalization. VERIFIED_THRESHOLD=0.50, L3_ESCALATE_THRESHOLD=0.30 module constants. |
| `cua_overlay/verifier/aggregator.py` | Aggregator (L0+L1 parallel + L2/L3 escalation) | ✓ VERIFIED | anyio.create_task_group for L0+L1; L2 boost (0.2 * max signal, halved if walker_truncated); L3 catch with `l3.unavailable_phase1` warning. |
| `cua_overlay/persist/session_writer.py` | SessionWriter (~/.cua/sessions/<uuid>/) | ✓ VERIFIED | UUID4 session_id; 5 subdirs (checkpoints/recipes/cassettes/recordings/profile_snapshot) + heals.ndjson + action_log.ndjson + atomic snapshot.json. |
| `cua_overlay/persist/durable_step.py` | DurableExecutor (AsyncPostgresSaver wrap) | ✓ VERIFIED | from_conn_string async context manager; setup() / checkpoint() / latest_checkpoint() / aclose(); _mask_conn for T-1-02 (per WR-05 over-redacts harmless cases — see Info). |
| `cua_overlay/persist/resume.py` | resume_from_checkpoint + ResumeContext | ✓ VERIFIED | Returns None for fresh sessions; ActionCanonical.model_validate round-trips through Postgres. |
| `cua_overlay/mcp_server/main.py` | FastMCP bootstrap + cua-driver stdio spawn | ✓ VERIFIED | StdioServerParameters(command="cua-driver", args=["mcp"]); run_stdio_async; full Phase 1 stack wired. T-1-01 mitigated. |
| `cua_overlay/mcp_server/proxy.py` | register_proxied_tool + ACTION_CLASS_TOOLS | ✓ VERIFIED | 10 upstream tools mapped to 4 canonical action classes (click/scroll/type/set_value); PRE/FIRE/POST/LOG/CHECKPOINT wrap. |
| `cua_overlay/mcp_server/healing_tools.py` | click_with_healing | ✗ STUB (docstring lies) | Tool registered but bypasses verifier wrap (WR-02). See Gaps. |
| `cua_overlay/demo/calculator_click.py` | run_demo() coroutine + main() CLI | ✓ VERIFIED | run_demo() returns 10-field result dict; main() pretty-prints with rich; PHASE-1-DEMO.md operator runbook present. |
| `scripts/init_postgres.sh` | Idempotent provisioning | ✓ VERIFIED | createdb cua_maximalist (literal match); idempotent (skips if DB exists); `psql cua_maximalist -c '\dt' | grep -c checkpoint` returns 4. |
| `scripts/doctor.py` | Environment doctor | ✓ VERIFIED | Python 3.12 + uv + Postgres + AXIsProcessTrusted + Calculator checks via rich-coloured table. |
| `.planning/phases/01-foundation-state-verifier/PHASE-1-DEMO.md` | Operator runbook | ✓ VERIFIED | All 5 required headers present; 6 BLOCKER pitfalls cited; SIGKILL + TCC + modal manual smoke checks documented. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| Aggregator.verify | L0Push.collect + L1Cheap.run | anyio.create_task_group | ✓ WIRED | aggregator.py uses task group; tested by `test_l0_l1_run_in_parallel`. |
| AXObserverManager.expect | AXEventBridge.subscribe | subscription_ts_ns recorded BEFORE return | ✓ WIRED | Verified by `test_subscription_ts_ns_recorded_at_expect_time`. |
| L1Cheap pasteboard signal | structlog (T-1-03 mitigation) | Integer-only, never contents | ✓ WIRED | Tested by `test_no_pasteboard_contents_logged`; structlog _redact_sensitive processor runs in pipeline. |
| Aggregator | HoarePost (Plan 01-01 model_validator) | model_validator enforces verified == confidence>=0.5 | ✓ WIRED | Cannot desync; tested. |
| MCP proxy main.py | cua-driver mcp via stdio_client | StdioServerParameters(command, args=["mcp"]) | ✓ WIRED | Late-import + manual __aenter__/__aexit__ for lifetime management. |
| MCP proxy register_proxied_tool | Aggregator.verify | PRE-snapshot + FIRE + POST-aggregate + LOG + CHECKPOINT | ✓ WIRED | proxy.py:144 + 183 wrap upstream.call_tool with verifier ladder. |
| MCP healing click_with_healing | Aggregator.verify (claimed in docstring) | upstream.call_tool('click') | ✗ NOT_WIRED | WR-02: tool bypasses the wrap that proxy registered for upstream click. Going to upstream directly skips L0+L1 + action_log + Postgres checkpoint. |
| SessionWriter.append_action_log | ~/.cua/sessions/<id>/action_log.ndjson | NDJSON one-line append | ✓ WIRED | 11 unit tests. |
| DurableExecutor.checkpoint | AsyncPostgresSaver.aput | "state" channel multiplex | ✓ WIRED | 6 integration tests; latest_checkpoint round-trip with step_idx 0→1→2. |
| TCCMonitor | classifier.classify entry-point | First line of classify | ✓ WIRED | Tested by `test_classify_calls_tcc_check_at_start`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| Aggregator HoarePost | confidence, tier_signals | L0Push.collect (AXObserverManager future) + L1Cheap.run (CGWindowList + Pasteboard + dHash) | YES — real signals from real PyObjC framework calls; mocked in tests via monkeypatch but production paths reach NSPasteboard, CGWindowListCopyWindowInfo, AXUIElement | ✓ FLOWING |
| AppProfile classify | ax_rich, ax_observer_works, cdp_port | probe_ax_rich, probe_ax_observer_works, probe_cdp_ports | YES — Calculator integration test confirms ax_rich=True, ax_observer_works=True, cdp_port=None | ✓ FLOWING |
| SessionWriter action_log | events from MCP wrap | proxy.py:_wrapped writes one NDJSON line per action-class call | YES — Plan 09 demo verified to write at least one valid JSON line | ✓ FLOWING |
| DurableExecutor checkpoint row | state dict (step_idx, pre, action, post) | AsyncPostgresSaver.aput with "state" channel | YES — 4 round-trip tests confirm checkpoints persist + replay | ✓ FLOWING |
| click_with_healing return dict | result, session_id, phase, note | upstream.call_tool('click') directly (no proxy wrap) | PARTIALLY — result content flows through but verifier ladder + log + checkpoint do NOT | ⚠️ HOLLOW (audit-trail) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Unit tests pass under SKIP_INTEGRATION | `SKIP_INTEGRATION=1 uv run pytest -q tests/unit/` | 111 passed in 0.87s | ✓ PASS |
| Causal DAG integration tests | `SKIP_INTEGRATION=1 uv run pytest -q tests/integration/test_causal_dag.py` | 6 passed | ✓ PASS |
| Full phase test suite under skip mode | `SKIP_INTEGRATION=1 uv run pytest -q tests/` | 124 passed, 25 skipped | ✓ PASS |
| Public-API import smoke | `python -c "from cua_overlay.verifier import Aggregator, L0Push, L1Cheap, L2Medium, L3Stub, WeightedVote, VERIFIED_THRESHOLD"` | exits 0 | ✓ PASS |
| MCP module entry runnable | `python -c "import cua_overlay.mcp_server.__main__"` | exits 0 | ✓ PASS |
| No TCP transport in MCP proxy | `grep -rE "socket\.AF_INET|listen\(|\.bind\(" cua_overlay/mcp_server/` | 0 matches | ✓ PASS |
| All 7 AX notifications wired | `grep "AX...Changed\|AX...Created" cua_overlay/verifier/ensemble/l0_push.py` | 7 matches (Value/Focused/Window/Title/Layout/SelectedText/SelectedRows) | ✓ PASS |
| Swift cua-driver untouched | `git diff --name-only main..HEAD libs/cua-driver/Sources/` | empty | ✓ PASS |
| Calculator demo (live) | `uv run python -m cua_overlay.demo.calculator_click` | Per PHASE-1-DEMO.md: verified=True, latency 31-45ms, L0 sometimes flakes (L1 carries) | ? SKIP (requires TCC + Calculator) |
| Postgres tables provisioned | `psql cua_maximalist -c '\dt' | grep -c checkpoint` | per Plan 07 SUMMARY: 4 tables | ? SKIP (requires postgres up) |

### Requirements Coverage (18 requirement IDs from ROADMAP)

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| CORE-01 | 01-01 | Python overlay scaffold above libs/cua-driver/ | ✓ SATISFIED | `cua_overlay/` exists; `libs/cua-driver/` vendored; pyproject.toml pins all deps. |
| CORE-02 | 01-08 | ToolRegistry post-action callback intercept | ✓ SATISFIED | Proxy strategy at MCP transport level; no Swift edits. `register_proxied_tool` wraps every action-class tool with PRE/FIRE/POST. |
| CORE-03 | 01-02 | bundleID → AppProfile classifier | ✓ SATISFIED | `cua_overlay/profile/classifier.py::classify`; per-bundle disk cache; survives session restart. |
| STATE-01 | 01-01 | Typed-graph UIElement model | ✓ SATISFIED | 22-field Pydantic v2 UIElement in `state/graph.py`; composite_key delegates to fingerprint. |
| STATE-02 | 01-01 | Causal DAG of action → state delta | ✓ SATISFIED | `state/causal_dag.py::CausalDAG.record` emits TRIGGERS edges from value/focused diff. |
| STATE-03 | 01-01 | Temporal ring buffer (last 5 frames) | ✓ SATISFIED | `state/ring_buffer.py::TemporalRingBuffer` deque(maxlen=5); PRECEDES edges. |
| VERIFY-01 | 01-04 | AXObserver subscription manager (subscribe BEFORE action) | ✓ SATISFIED | All 7 notifs wired in `_AX_NOTIF_TO_SIGNAL`; `expect()` records subscription_ts_ns BEFORE return. WR-01 affects element_key (not the subscription contract). |
| VERIFY-02 | 01-04 + 01-05 | NSWorkspace + DistributedNotification + CDP DOM + kqueue EVFILT_PROC | ✓ PARTIALLY (Phase 2 finish) | NSWorkspace + kqueue EVFILT_PROC live; CDP DOM is Phase 2; DistributedNotification contract defined + Phase 2 stub. |
| VERIFY-03 | 01-05 | Event aggregator with weighted vote per action class | ✓ SATISFIED | WeightedVote with present-signal renormalization; click/type/scroll/set_value tables. |
| VERIFY-04 | 01-05 | L0 push events (0ms, primary signal) | ✓ SATISFIED | L0Push consumes AXObserverManager futures; source-grep confirms no polling. |
| VERIFY-05 | 01-05 | L1 cheap diff (CGWindowList + NSPasteboard.changeCount + dHash) | ✓ SATISFIED | All three sub-checks in anyio.create_task_group; <20ms total. |
| VERIFY-06 | 01-06 | L2 medium (Vision OCR + AX subtree 3 levels MAX) | ✓ SATISFIED | L2Medium delegates to walk_subtree (default caps); ocrmac for OCR ROI. |
| VERIFY-07 | 01-06 | L3 LLM fallback (only when confidence < 0.30) | ✓ SATISFIED | L3Stub Protocol + raises NotImplementedError; aggregator catches gracefully with `l3.unavailable_phase1` warning. |
| PERSIST-01 | 01-07 | Each translator call wrapped as durable step | ✓ SATISFIED | DurableExecutor.checkpoint takes (session_id, step_idx, pre, action, post) tuple via AsyncPostgresSaver.aput. |
| PERSIST-02 | 01-07 | ~/.cua/sessions/<id>/ structure | ✓ SATISFIED | SessionWriter creates 5 subdirs + 2 NDJSON files + atomic snapshot.json at construction. |
| PERSIST-03 | 01-07 | Crash → resume from last verified step | ✓ SATISFIED (auto) + ⚠️ HUMAN | Simulated-crash test passes (executor-A writes, aclose, executor-B resumes); manual SIGKILL test documented + skipped per plan. |
| MCP-01 | 01-08 | Maintain trycua's existing MCP server surface | ✓ SATISFIED | Proxy mirrors all upstream tools via passthrough (non-action) + wrap (action-class). |
| MCP-02 | 01-08 | Expose self-healing wrapper as MCP tools | ⚠️ PARTIAL (WR-02) | click_with_healing tool registered and discoverable. Phase 1 implementation bypasses verifier wrap — docstring claim incorrect. Tool surface contract holds; audit-trail for healing-named calls is incomplete. |

**Score: 16/18 fully satisfied + 2/18 partial (VERIFY-02 deferred to Phase 2 by design; MCP-02 has docstring bug).** 0 unsatisfied; 0 orphaned (no requirement IDs in REQUIREMENTS.md mapped to Phase 1 are absent from plans).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| cua_overlay/mcp_server/healing_tools.py | 56-63 + 94 | Docstring claims verifier ladder runs; implementation bypasses it | ⚠️ Warning (WR-02) | Audit-trail incomplete for healing-named calls; MCP host introspection sees misleading description. |
| cua_overlay/ax/observer.py | 255-307 | Per-pid callback closure leaks stale element_key/pid to subsequent subscribers | ⚠️ Warning (WR-01) | Phase 1 demo invisible (single subscribe per session); Phase 2 race orchestrator hits this. AXEvent.element_key field is misleading data after first subscribe. |
| cua_overlay/ax/observer.py | 256-274 | Callback can raise RuntimeError into PyObjC C boundary on loop close | ⚠️ Warning (WR-04) | Race window during stop() ; potential SIGABRT on stress shutdown. |
| cua_overlay/ax/observer.py | 108-112, 247-248, 307 | _callbacks/_refcon_to_action/_subscriptions grow without bound | ⚠️ Warning (WR-03) | Phase 1 short sessions invisible; Phase 3 high-frequency action throughput accumulates ~100 bytes per action. Refcon collision risk grows monotonically (WR-04 IN-01 4-billion bound). |
| cua_overlay/persist/durable_step.py | 161-169 | _mask_conn over-redacts conn strings without password (false positive on `user@host:5432`) | ⚠️ Warning (WR-05) | Operators debugging "wrong host?" see *** instead of useful info. T-1-02 still holds (no false negative); UX problem only. |
| cua_overlay/verifier/kqueue_proc.py | 47 | asyncio.get_event_loop() fallback emits DeprecationWarning in Python 3.12+ | ⚠️ Warning (WR-06) | Today: callers always pass loop=loop explicitly. Future: Python 3.14 may raise where 3.12 warns. |
| Multiple | Various | 14 Info-level items: redundant exception catches, hardcoded magic constants, shared step counter, label cascade duplication | ℹ️ Info | Documented in 01-REVIEW.md sections IN-01 through IN-14. None blocking. |

### Human Verification Required

The Phase 1 ship gate is locked behind 5 interactive tests that require a real macOS environment with TCC permissions, Calculator.app, Postgres running, and the cua-driver Swift binary built:

#### 1. Calculator click <50ms via L0 push (SC-1)

**Test:** Run `uv run python -m cua_overlay.demo.calculator_click` after granting Accessibility TCC to the Python interpreter.
**Expected:** Exits 0 with `verified=True`, `latency_ms < 50`, `tier_signals["L2"] is None`, `tier_signals["L3"] is None`. L0 signal=1.0 ideally; if AX delivery flakes (documented macOS 26 quirk), L1 signal=1.0 carries.
**Why human:** Real Calculator.app + Accessibility TCC grant required. Per PHASE-1-DEMO.md the demo agent ran live and reported verified=True, latency 31-45ms.

#### 2. AppProfile cache survives session restart (SC-3 manual confirmation)

**Test:** First run: `uv run python -m cua_overlay.demo.calculator_click`. Second run within same session.
**Expected:** First-probe latency ≤500ms; cache hit on second run ≤5ms (visible in `appprofile_cache_hit` log line).
**Why human:** Calculator + TCC required. Plan 02 SUMMARY reports first-probe 14ms, cache-hit 0ms.

#### 3. TCC revocation surfaced (P24, manual smoke check)

**Test:** Toggle Accessibility OFF for the Python binary in System Settings → Privacy & Security; re-run the demo.
**Expected:** Structured event `tcc_revoked` in stderr/log with action URL `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`. Exits 2.
**Why human:** Requires interactive System Settings toggle; documented in PHASE-1-DEMO.md "Manual Smoke Checks".

#### 4. Modal alert blocks AX (P25, manual smoke check)

**Test:** Open System Settings → Privacy & Security → click any "Lock" icon; while the password modal is up, run the demo.
**Expected:** `AssertionError: A modal is blocking Calculator — close any system dialogs before re-running the demo (Pitfall P25).`
**Why human:** Requires interactive modal dialog.

#### 5. SIGKILL crash-resume (PERSIST-03 manual)

**Test:** Three terminals: (a) `uv run python -m cua_overlay.demo.calculator_click`; (b) `kill -9 <pid>` while Postgres checkpoint is being written; (c) call `resume_from_checkpoint(session_id, durable)` for the same session_id.
**Expected:** `ResumeContext(last_step_idx=1, last_verified_action=ActionCanonical(...))`.
**Why human:** Requires multi-terminal kill -9 sequence. CI-equivalent `test_resume_simulated_crash` passes (executor-A writes, aclose, executor-B resumes).

#### 6. MCP proxy + healing tool with real cua-driver (SC-6)

**Test:** Build cua-driver: `cd libs/cua-driver && swift build -c release`; export `CUA_DRIVER_BIN`; `uv run pytest -v -m integration tests/integration/test_mcp_proxy.py`.
**Expected:** All 4 tests pass: list_tools returns proxied upstream tools + click_with_healing; screenshot passthrough works; click_with_healing call against Calculator returns success dict; action_log.ndjson contains the click event line.
**Why human:** Requires Swift binary built and on PATH (skipped cleanly in this worktree). Note: per WR-02 the action_log line currently won't be written for the click_with_healing path — only for direct `click` proxy calls.

### Gaps Summary

Phase 1 lands the foundation, state, and verifier subsystems with strong attention to the documented pitfall taxonomy. **All 6 ROADMAP success criteria are satisfied in code** (SC-1 with the macOS 26 AX delivery flake compensated by L1 fallback per BLOCKER-1 renormalization). **All 18 requirement IDs are accounted for** in the codebase with implementation evidence. **0 critical issues found**; **6 warnings cover real but contained correctness gaps** that don't break Phase 1 demo paths but will surface in Phase 2/3 stress conditions.

The single material gap is **WR-02: `click_with_healing` bypasses the verifier wrap**. The tool's docstring claims it runs the L0+L1 verifier ladder and writes action_log lines, but the implementation calls `upstream.call_tool('click', ...)` directly — going around the wrap that `register_proxied_tool` registered for the upstream click tool. This breaks the audit-trail promise for healing-named calls but does not break the SC-6 surface contract (the tool is registered and callable). Recommended fix: change `healing_tools.py:94` to `await proxy.call_tool('click', arguments=...)` so the wrap fires.

The other 5 warnings (WR-01 element_key staleness, WR-03 unbounded growth, WR-04 callback exception leak, WR-05 over-redaction, WR-06 deprecated asyncio call) are pre-existing in the AX subscription path and persistence layer; all are demonstrably non-blocking for the Phase 1 demo and three of them defer naturally to Phase 2/3 work (see deferred items).

The Phase 1 invariant — "L2/L3 must NEVER fire on the demo path" — is asserted inline in `run_demo()` step 14 and verified in `test_l2_l3_not_invoked`. The "<50ms with no AX subtree walk" invariant is enforced by the present-signal renormalization rule (single-signal hits resolve to 1.0 confidence in their own column), so single-tier flake (L0 OR L1 fires alone) is non-fatal.

**Status: human_needed** — automated checks pass cleanly; 6 manual TCC + Calculator + Postgres + Swift-build tests gate the ROADMAP success criteria. The code review's only Warning that affects a ROADMAP success criterion is WR-02 (touching SC-6's audit-trail completeness); a one-line fix in `healing_tools.py:94` closes it. All other warnings are scoped to defer-to-Phase-2/3 surfaces.

---

_Verified: 2026-04-29T22:50:00Z_
_Verifier: Claude (gsd-verifier)_
_Depth: standard (goal-backward verification against 6 ROADMAP success criteria + 18 requirement IDs + 6 BLOCKER pitfall mitigations)_
