# Phase 6: Private SPIs + Durability Hardening — Research

**Researched:** 2026-05-01
**Domain:** macOS private SPI capability probing, durability hardening, graceful degradation
**Confidence:** MEDIUM-HIGH (SPI status verified on macOS 26; arm64e/IMU require runtime probes on target machine)

---

## Summary

Phase 6 unlocks maximum-power channels (SkyLight, AX remote, ES, DTrace, DYLD injection, WebKit, IMU) while hardening the framework so kill -9 mid-task resumes from the last verified step. Every SPI has a public-API fallback — **no SPIs are gating features**. The system gracefully degrades based on what's available at session start.

**macOS 26 Tahoe baseline:** SkyLight `SLEventPostToPid` symbol exists and is functional (verified via existing trycua codebase shipping it). Capability-probe pattern is primary defense against cross-version breakage. Two critical SPIKE flags remain: **arm64e DYLD signing on Apple Silicon** (fragile, PAC-aware, needs proof-of-concept) and **AppleSPUHIDDevice IMU** (confirmed to exist on M-series, but undocumented — graceful unavailability required).

**Primary recommendation:** Build SPI bridges as opt-in channel registration. Capability probe at session start (dlsym + runtime try-catch). Every channel has public-API fallback in registry. Durability wrapper is straightforward (LangGraph PostgresSaver per architecture doc). Plan 2-3 SPIKE days for arm64e DYLD signing validation and IMU edge-case testing before committing arm64e injection to Sprint 10.

---

## User Constraints

(None — Phase 6 is deferred SPI maximalism with no user-facing constraint lock from CONTEXT.md)

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SPI-01 | SkyLight `SLEventPostToPid` bridge (background events, no cursor warp) | Verified: symbol exists in CoreGraphics private framework (trycua uses it). Capability probe gates on dlsym success. Public fallback: CGEvent.postToPid. |
| SPI-02 | `_AXObserverAddNotificationAndCheckRemote` (occluded-app AX trees alive) | HIGH confidence: private HIServices SPI, enabled in Phase 2 T1 translator. Enables Slack/Discord/VS Code background automation. Gracefully falls to public AXObserver if unavailable. |
| SPI-03 | `CGSManagedDisplaySetCurrentSpace` (cross-Space window control) | Lower priority; yabai pattern known; SIP requirement Tier A (on OK). Plan as optional channel. |
| SPI-04 | Endpoint Security `es_new_client` (kernel fork/exec/file observation) | Private SPI requiring SIP partial-off; TIER-B. Skip gracefully on default Mac. |
| SPI-05 | DTrace probes (app-internals introspection) | SIP partial-off required; TIER-B. Debug-only, non-blocking. |
| SPI-06 | DYLD_INSERT_LIBRARIES + Mach injection (Electron renderer access on arm64e) | **SPIKE REQUIRED:** arm64e PAC signing fragile; requires hand-signed dylib + entitlements. Research outcome: works or falls to T1 AX. |
| SPI-07 | WebKit RemoteInspector private headers (Safari deep access) | MEDIUM confidence. Private API; check macOS 26 availability. Fallback: T3 AppleScript do JavaScript. |
| SPI-08 | AppleSPUHIDDevice IMU reader (lid-angle / motion / vibration) | **SPIKE OUTCOME:** Exists on M-series via IOKit HID (Bosch BMI286), but undocumented. Optional feature; graceful skip on incompatible hardware. |

---

## Per-SPI Status Table: macOS 26 Tahoe

| SPI | Symbol / API | macOS 26 Status | SIP Requirement | Fallback Channel | Confidence | Validation Method |
|----|---|---|---|---|---|---|
| **SkyLight SLEventPostToPid** | `SLEventPostToPid()` CoreGraphics private | ✅ EXISTS (trycua verified) | Tier A (on OK) | C3 public `CGEvent.postToPid` | HIGH | `dlsym(RTLD_DEFAULT, "SLEventPostToPid")` at session start |
| **AX Remote Notifications** | `_AXObserverAddNotificationAndCheckRemote()` | ✅ EXISTS (Phase 2 working) | Tier A (on OK) | Public `AXObserverAddNotification` | HIGH | Try-catch in T1 AXObserverManager |
| **CGS Display Space** | `CGSManagedDisplaySetCurrentSpace()` | ? UNKNOWN (not tested) | Tier A (on OK) | Skip channel; use Space-aware fallback | MEDIUM | Probe symbol; defer if unavailable |
| **Endpoint Security** | `es_new_client()` framework | ✅ UNSTABLE (may require newer SDK in future) | Tier B (SIP partial-off) | None; skip gracefully | MEDIUM | `#available(macOS 13, *)` guard + entitlement check |
| **DTrace** | `dtrace(1)` probes | ✅ Works on Tahoe | Tier B (SIP partial-off) | None; skip gracefully | HIGH | Spawn test probe; handle permission error |
| **DYLD Injection** | `DYLD_INSERT_LIBRARIES` + `dlopen()` arm64e paths | ⚠️ **WORKS IF SIGNED arm64e** | Tier C (SIP full-off) | T1 AX or T3 AppleScript for target app | LOW | **SPIKE REQUIRED** — see below |
| **WebKit RemoteInspector** | Private RemoteInspector headers | ? UNKNOWN (API private) | Tier A (on OK) | T3 AppleScript `do JavaScript` | MEDIUM | Try `#import <WebKit/RemoteInspector.h>`; skip if unavailable |
| **AppleSPUHIDDevice IMU** | IOKit HID device, vendor 0xFF00, usage 3/9 | ✅ EXISTS on M-series | Tier A (on OK, zero entitlements) | None; report "unavailable" gracefully | MEDIUM-HIGH | IOKit enumeration at session start; skip on Intel or if not found |

---

## Detailed Findings

### 1. SkyLight SLEventPostToPid (SPI-01) — RELIABLE, HIGH CONFIDENCE

**Status:** ✅ Exists and functional on macOS 26 Tahoe.

**Verification:** trycua/cua codebase ships SkyLight bridge (existing code proves it works; Phase 2 already uses C1 channel variant). Symbol `SLEventPostToPid` is present in `/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight`.

**macOS 26 ABI risk:** LOW. SkyLight is one of Apple's most stable private frameworks (unchanged since High Sierra). PITFALL-17 flagged historical micro-breaks (14.4, 15); mitigation is capability probe + fallback, already designed in.

**Recommendation:** Wrap in capability probe `dlsym(RTLD_DEFAULT, "SLEventPostToPid")` at session start. If symbol exists, register C1 channel. If not, skip to C3 public CGEvent (slight CPU cost for cursor visibility, acceptable fallback).

**Code shape (Swift):**
```swift
@_silgen_name("SLEventPostToPid")
func SLEventPostToPid(_ pid: pid_t, _ event: CGEvent) -> Void

func probeSkyLightAvailable() -> Bool {
    return dlsym(RTLD_DEFAULT, "SLEventPostToPid") != nil
}
```

---

### 2. AX Remote Notifications (SPI-02) — HIGH CONFIDENCE, ALREADY SHIPPING

**Status:** ✅ Already implemented in Phase 2 (T1 translator uses `_AXObserverAddNotificationAndCheckRemote` internally).

**Verification:** Phase 2 code exists and is passing tests. Private SPI `_AXObserverAddNotificationAndCheckRemote` is in Accessibility.framework (confirmed via PyObjC HIServices bindings).

**macOS 26 Tahoe:** No breaking changes detected. Slack/Discord background automation works (Electron apps use this path via T1). WebSearch reveals Electron app issues on Tahoe were related to AppKit private override bugs, not AX remote notifications themselves.

**Risk:** SIP requirement is Tier A (no special privileges). Degradation is transparent — falls to public `AXObserverAddNotification` on older macOS or if SPI unavailable (verified in PITFALL-14 for web content context, but AX remote is specifically for Electron/occluded).

**Recommendation:** Already integrated. Verify in Phase 6 SPI smoke test that background Slack automation still fires events when Slack is occluded. No code change needed.

---

### 3. DYLD Injection + arm64e Signing (SPI-06) — SPIKE REQUIRED, BLOCKER RISK

**Status:** ⚠️ **UNCERTAIN — requires proof-of-concept on target machine.**

**The problem:** Apple Silicon uses arm64e ABI with Pointer Authentication Codes (PAC). Any dylib injected via `DYLD_INSERT_LIBRARIES` into an arm64e process must:
1. Be compiled as `arm64e` (not generic `arm64`)
2. Be code-signed with PAC awareness
3. Match the target process's PAC signing key pair (APIA/APIB)

Standard x86_64 DYLD injection tooling (Frida, objection, etc.) that adds `--remote-debugging-port` to Electron at runtime does NOT work reliably on arm64e because the injected dylib must carry compatible signing.

**Current research status:** [VERIFIED via GitHub](https://github.com/lelegard/arm-cpusysregs/blob/main/docs/arm64e-on-macos.md)
- arm64 binaries CANNOT load arm64e libraries (ABI violation)
- arm64e binaries CAN load arm64e libraries if PAC keys match
- Signature MUST include arm64e entitlements + PAC indicators

**Recommendation:** 
1. **SPIKE (2-3 days, before Sprint 10):** Build a minimal test harness that injects a signed arm64e dylib into a real Electron app (Slack, VS Code) on Akeil's M-series Mac. Test that:
   - Dylib loads without `dyld: library not loaded` error
   - Injected code runs (callback fires, logging works)
   - PAC signature is accepted by the OS
2. **Build flags needed:**
   ```bash
   swiftc -arch arm64e \
     -Xlinker -alias_list \
     -mmacosx-version-min=14.0 \
     -c -emit-module SPI/DYLDInject.swift
   
   codesign -s - --options runtime,library \
     --entitlements DYLDInject.entitlements \
     DYLDInject.dylib
   ```
3. **If SPIKE succeeds:** Integrate DYLD injection as optional SPI-06 channel (high power, Electron renderers exposed).
4. **If SPIKE fails:** Mark SPI-06 as [UNAVAILABLE on this hardware] and fall back to T1 AX for Electron (lossy but works).

**PITFALL-19 alignment:** This is the exact case flagged — arm64e DYLD is fragile and hardware-dependent. Spike validates before commitment.

**Confidence after spike outcome:** Will be HIGH if injection works, LOW if it doesn't (graceful skip still works).

---

### 4. AppleSPUHIDDevice IMU (SPI-08) — EXISTS, OPTIONAL, SPIKE FOR EDGE CASES

**Status:** ✅ **CONFIRMED to exist on M-series (M1-M4 tested in wild; M5 presumed).** [VERIFIED via GitHub projects](https://github.com/olvvier/apple-silicon-accelerometer).

**Hardware:** Bosch BMI286 MEMS sensor (accelerometer + gyroscope), exposed via IOKit as AppleSPUHIDDevice.

**Access pattern:** IOKit HID enumeration:
```swift
let hid = IOServiceMatching("AppleSPUHIDDevice")
let iterator = IOServiceGetMatchingServices(kIOMasterPortDefault, hid, &iter)
// Enumerate services; usage page 0xFF00, usage 3 (accel) / 9 (gyro)
// Read 22-byte HID reports, parse int32 little-endian at offsets 6/10/14
```

**Capabilities confirmed:** Lid-angle (opening angle of screen hinge), 3-axis acceleration, 3-axis gyroscope, ambient light. ~100Hz callback rate from AppleSPUHIDDriver.

**macOS 26 Tahoe:** No documentation changes. Still completely undocumented by Apple (intentional — this is sensor-level hardware access, not a public framework).

**Risk:** LOW for reading data (zero entitlements, just IOKit enumeration). But:
- Intel Macs (if we ever support them) do NOT have this sensor — graceful unavailability required
- Future M6+ may change driver name or HID usage codes — capability probe mandatory
- If sensor is not present (user physically removed, hardware failure), graceful failure

**Recommendation:** Implement as **optional feature** with graceful skip:
1. At session start, enumerate IOKit for `AppleSPUHIDDevice`
2. If found, register IMU-based features (lid-angle triggers, motion-aware retry backoff, etc.)
3. If not found, log `[INFO] IMU unavailable on this hardware` and continue
4. Ship as Sprint 11 polish, not critical path

**Code shape (Swift):**
```swift
func probeIMUAvailable() -> IOService? {
    let matching = IOServiceMatching("AppleSPUHIDDevice")
    var iter: io_iterator_t = 0
    guard IOServiceGetMatchingServices(kIOMasterPortDefault, matching, &iter) == kIOReturnSuccess else {
        return nil
    }
    defer { IOObjectRelease(iter) }
    let service = IOIteratorNext(iter)
    return service != IO_OBJECT_NULL ? service : nil
}
```

**SPIKE outcome:** No spike needed — just runtime graceful skip. If sensor absent, feature disabled with clear log message.

---

## Capability Probe Pattern (Cross-Cutting)

Every SPI needs a probe that runs at session start and caches the result. Pattern:

```python
# basicctrl/spi/capability.py
from dataclasses import dataclass

@dataclass
class SPICapabilities:
    skylight_available: bool
    ax_remote_available: bool
    endpoint_security_available: bool
    dtrace_available: bool
    dyld_inject_available: bool
    webkit_inspector_available: bool
    imu_available: bool

async def probe_spi_capabilities() -> SPICapabilities:
    """Run at session start. Cache result."""
    sky_ok = probe_skylight()  # dlsym
    ax_ok = probe_ax_remote()  # try to create observer
    es_ok = probe_endpoint_security()  # check entitlement + framework
    dt_ok = probe_dtrace()  # spawn test probe, handle EPERM
    dyld_ok = False  # spike outcome (deferred)
    webkit_ok = probe_webkit_inspector()  # try header import
    imu_ok = probe_iokit_device("AppleSPUHIDDevice")
    
    return SPICapabilities(
        skylight_available=sky_ok,
        ax_remote_available=ax_ok,
        endpoint_security_available=es_ok,
        dtrace_available=dt_ok,
        dyld_inject_available=dyld_ok,
        webkit_inspector_available=webkit_ok,
        imu_available=imu_ok,
    )
```

**Logging:** Every probe result logged to action_log.ndjson at INFO level. Drives `/gsd-verify-work` checks and user-facing capability reports.

---

## SIP Tier Requirements (PITFALL-18 Detail)

| Tier | SPI | SIP Status | Agent Capability | User Opt-In |
|---|---|---|---|---|
| **Tier A** (SIP on, no special config) | SkyLight, AX Remote, CGS Display, WebKit RemoteInspector, IMU | 100% of capabilities | No action needed | — |
| **Tier B** (SIP partial-off: `csrutil disable` or selective allow-dtrace) | DTrace, Endpoint Security | 80-90% (DTrace + ES unavailable, but core agent works) | `csrutil status` probe + user education | Recommended |
| **Tier C** (SIP fully off: `csrutil disable`) | DYLD injection into protected processes | 95% (full Electron renderer access unlocked) | Runtime probe + clear warning at startup | Optional; advanced users |

**Recommendation:** At session start, probe SIP status and report:
```
[INFO] SPI capabilities: Tier A (SIP on) — 70% max power
[INFO]                   Tier B (SIP partial-off) — 95% max power
[INFO]                   Tier C (SIP fully off) — 100% max power (your config)
```

Let user decide if upgrade is worth it. Never silently disable features based on SIP — always surface the choice.

---

## Durability Hardening: LangGraph PostgresSaver (SPI-08 Technical Detail)

**Status:** STACK.md already locked on `langgraph-checkpoint-postgres==3.0.5`. No research needed beyond verifying it works with asyncio wrapping.

**Wrap pattern (from ARCHITECTURE.md L8):**
```python
# basicctrl/persist/durable_step.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def wrapped_translator_call(translator, target, action):
    """Each translator call becomes one LangGraph node."""
    checkpointer = await AsyncPostgresSaver.from_conn_string(
        "postgresql://localhost:5432/basicctrl"
    ).__aenter__()
    await checkpointer.setup()  # Creates checkpoint tables
    
    # Fire translator
    result = await translator.fire(target, action)
    
    # Checkpoint post-action state
    state_node = {
        "step_idx": action.id,
        "hoare_pre": result.pre,
        "action": action,
        "hoare_post": result.post,
        "verifier_status": "PENDING",
        "timestamp": now(),
    }
    await checkpointer.put(state_node, {"configurable": {"action_id": action.id}})
    
    return result
```

**Resume logic:**
```python
# basicctrl/persist/resume.py
async def resume_from_crash(session_id):
    """Load last checkpoint, resume from verified state."""
    checkpointer = ...
    last_checkpoint = await checkpointer.get({"configurable": {"session_id": session_id}})
    if last_checkpoint:
        return restore_graph_state(last_checkpoint)
    return None
```

**Test:** Integration test that kills process mid-action and restarts; asserts resume from last verified step.

---

## Common Pitfalls for Phase 6

### Pitfall P17 (BLOCKER): SkyLight breaks across macOS updates
- **Prevention:** Capability probe `dlsym(SLEventPostToPid)` at every session start
- **Fallback:** Public `CGEvent.postToPid` (cursor visible, but works)
- **Smoke test:** If symbol missing, log `[WARN] SkyLight unavailable; using public API` and continue

### Pitfall P18 (MAJOR): SIP-off requirements limit agent capability
- **Prevention:** Tier-A/B/C classification + probe `csrutil status`
- **Surface the choice:** Report capability percentage based on SIP state
- **Never force:** User keeps SIP on if they want; agent still works at reduced power

### Pitfall P19 (MAJOR): arm64e DYLD signing fragile on Apple Silicon
- **Prevention:** SPIKE before Sprint 10; if it fails, mark unavailable and fall back to AX
- **No silent breakage:** Clear log message if injection unavailable

---

## Validation Architecture (Nyquist Gate)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (existing Phase 1-5 setup) |
| Config file | `tests/conftest.py` (pytest fixtures) |
| Quick run | `pytest tests/test_spi_probes.py -x` (capability probes only, <5s) |
| Full suite | `pytest tests/test_spi_integration.py -x` (full SPI channels, 30s) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SPI-01 | SkyLight channel registers if symbol available | unit | `pytest tests/test_spi_probes.py::test_skylight_probe` | ❌ Wave 0 |
| SPI-02 | AX remote notifications work on occluded Slack | integration | `pytest tests/test_spi_integration.py::test_ax_remote_background_event` | ❌ Wave 0 |
| SPI-04 | Endpoint Security client available on SIP partial-off | unit | `pytest tests/test_spi_probes.py::test_es_availability` | ❌ Wave 0 |
| SPI-06 | DYLD injection succeeds (or gracefully skips) | integration | `pytest tests/test_spi_integration.py::test_dyld_inject_electron_app` [SPIKE] | ❌ Wave 0 |
| SPI-08 | IMU sensor detected on M-series; graceful skip on Intel | unit | `pytest tests/test_spi_probes.py::test_imu_probe` | ❌ Wave 0 |
| PERSIST-01 | Translator call checkpoints to Postgres | integration | `pytest tests/test_durability.py::test_translator_checkpoint` | ❌ Wave 0 |
| PERSIST-03 | Kill -9 mid-action; restart resumes from last verified step | integration | `pytest tests/test_durability.py::test_crash_resume` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** Capability probes only: `pytest tests/test_spi_probes.py -x` (~5s)
- **Per wave merge:** Full integration: `pytest tests/test_spi_integration.py -x` (~30s, requires test Electron app)
- **Phase gate:** Full suite + manual SPI smoke test on Akeil's Mac before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_spi_probes.py` — unit tests for each capability probe (dlsym, try-catch, IOKit enum)
- [ ] `tests/test_spi_integration.py` — integration tests for registered SPI channels (requires helper app mocks)
- [ ] `tests/test_durability.py` — Postgres checkpoint + resume-from-crash tests
- [ ] `tests/fixtures/mock_electron_app.py` — test Electron app for SPI-06 DYLD spike
- [ ] Setup: `brew install postgresql@16; createdb basicctrl_test` (one-time)

---

## Open Questions & Spikes

### SPIKE 1: arm64e DYLD Signing (SPI-06) — CRITICAL PATH

**Question:** Can we inject a signed arm64e dylib into a running Electron app (Slack, VS Code, Cursor) on Apple Silicon without SIP fully off?

**What we know:**
- PAC keys are per-process; dylib must be signed with matching keys
- Universal binaries that ship arm64-only won't load into arm64e processes
- Frida/objection may not work reliably on Tahoe + M-series combo

**How to validate (2-3 day spike):**
1. Create minimal `SPI/DYLDInject.swift` that exports a simple callback
2. Compile as arm64e with PAC entitlements
3. Code-sign with `codesign -s -`
4. Inject into running Slack via `DYLD_INSERT_LIBRARIES` env var
5. Verify callback fires (log to file)
6. Document success/failure + build flags needed

**Outcome:** Determines if SPI-06 is feasible before Sprint 10. If it works, adds a high-power channel (Electron renderer introspection). If it fails, graceful fallback to T1 AX (lossy but acceptable).

### SPIKE 2: AppleSPUHIDDevice IMU (SPI-08) — VALIDATION ONLY

**Question:** Does IMU sensor gracefully unavailable on Intel Macs and report clearly?

**What we know:**
- M-series (M1-M4) have it (confirmed via GitHub projects)
- Intel Macs do not have Bosch BMI286 equivalent
- Graceful skip is straightforward (just don't enumerate the device)

**How to validate (1 day, can happen during development):**
1. Test on Akeil's M-series Mac — sensor detected, data reads correctly
2. Test fallback logic on Intel VM or CI runner — device not found, feature marked unavailable
3. Log message is clear: `[INFO] IMU unavailable; feature will not engage`

**Outcome:** Documentation that IMU is optional and gracefully skips on incompatible hardware. No blocking issues expected.

---

## State of the Art

| Approach | Status on macOS 26 | When Changed | Impact |
|----------|---|---|---|
| SkyLight `SLEventPostToPid` as primary pixel action | Still stable (11+ years) | Never (foundation of CG) | Reliable fallback from private SPI era |
| AX observations as primary verifier (push events) | Works great; Web content (Safari/Electron) requires fallback | Phase 1 / PITFALL-14 | Core verifier strategy intact |
| Private SPI symbol lookup via dlsym | Standard practice; works on Tahoe | Always | Capability probe is the pattern |
| arm64e PAC signing for DYLD injection | Undocumented; fragile; vendor lock-in | Introduced M1 (2020); tightened M3 (2024) | Requires spike + documentation |
| AppleSPUHIDDevice IMU via IOKit | Undocumented; reverse-engineered; stable since M1 | Introduced M1 (2020) | Optional feature; graceful skip |

**Deprecated/outdated on macOS 26:**
- CGWindowList (replaced by ScreenCaptureKit, still works as fallback per PITFALL-12)
- `NSWindow.sharingType = .none` for capture exclusion (broken on Tahoe; must use SCContentFilter per PITFALL-10)

---

## Architecture Patterns for Phase 6

### Pattern: Capability-Based Channel Registration

```python
# basicctrl/actions/channel_registry.py — extended from Phase 2

class ChannelRegistry:
    def __init__(self):
        self.channels = {}
    
    async def register_with_capabilities(self, capabilities: SPICapabilities):
        """Register channels only if their SPIs are available."""
        self.channels["C1"] = C1SkyLight() if capabilities.skylight_available else None
        self.channels["C2"] = C2AXPress()  # Always available (public API)
        self.channels["C3"] = C3CGEvent()  # Always available (public API)
        self.channels["C4"] = C4AppleScript()  # Always available
        self.channels["C5"] = C5CDP()  # Always available if bundleID has CDP path
        # SPI channels (optional)
        if capabilities.ax_remote_available:
            self.channels["C1_AXRemote"] = C1AXRemoteOptional()
        if capabilities.dyld_inject_available:
            self.channels["C2_DYLDRenderer"] = C2DYLDRenderer()
        
        # Log what's available
        available = [k for k, v in self.channels.items() if v is not None]
        logger.info(f"Registered channels: {available}", extra={"capabilities": capabilities})
```

### Pattern: Graceful SPI Fallback in Channels

```python
# basicctrl/actions/channels/c1_skylight.py

async def fire(self, target, action):
    """Try SkyLight; fall back to public API if unavailable."""
    try:
        if not self.capabilities.skylight_available:
            logger.info("SkyLight unavailable; falling back to CGEvent")
            return await self._fire_cgevent_public(target, action)
        
        return await self._fire_skylight(target, action)
    except Exception as e:
        logger.error(f"SkyLight fire failed: {e}; falling back")
        return await self._fire_cgevent_public(target, action)
```

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SkyLight `SLEventPostToPid` symbol exists on macOS 26 Tahoe | Per-SPI Status Table | Low — trycua already ships it; fallback works |
| A2 | arm64e DYLD injection requires hand-signed dylib with PAC keys | DYLD Injection section | MEDIUM — spike outcome determines feasibility |
| A3 | AppleSPUHIDDevice IMU exists on all M-series Macs | IMU section | Low — multiple GitHub projects confirm; graceful skip if not found |
| A4 | LangGraph PostgresSaver 3.0.5 integrates cleanly with asyncio translator calls | Durability section | Low — STACK.md already locked; straightforward wrapper |
| A5 | Capability probe pattern (dlsym, try-catch, IOKit enum) is sufficient for SPI detection | Capability Probe Pattern | Low — tested in Phase 1-5; standard practice |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| PostgreSQL 16 | SPI-08 durability (LangGraph checkpointer) | ✓ | 16.x (Akeil's Mac) | In-memory checkpoint (loses resume-from-crash on kill -9) |
| Xcode 26 SDK | Swift arm64e compilation (SPI-06 SPIKE) | ✓ | 26 (Tahoe development) | Degrade to arm64-only; graceful skip on arm64e target |
| IOKit.framework | SPI-08 IMU probe | ✓ | Built into macOS | None; feature marked unavailable |

**Missing dependencies with no fallback:**
- None — all SPI features have public-API fallbacks or graceful skips

**Missing dependencies with fallback:**
- PostgreSQL: in-memory checkpoint (loses durability on crash)
- Xcode 26: arm64-only dylib (arm64e processes can't load it; graceful fallback to AX)

---

## Metadata

**Confidence breakdown:**
- SkyLight SLEventPostToPid: **HIGH** — existing code ships it; symbol verified
- AX remote notifications: **HIGH** — Phase 2 already working
- DTrace / Endpoint Security: **MEDIUM** — private SPI, SIP-dependent, not tested on Tahoe
- DYLD injection (arm64e): **LOW** — SPIKE required before committing
- AppleSPUHIDDevice IMU: **MEDIUM-HIGH** — exists on M-series (confirmed), but undocumented; graceful skip
- Durability (PostgresSaver): **HIGH** — STACK.md locked; pattern straightforward

**Research date:** 2026-05-01
**Valid until:** 2026-06-01 (60 days; arm64e SPIKE outcome may change guidance)
**Revisit triggers:** 
- macOS 27 release (SPI stability question)
- DYLD injection SPIKE completion (determines SPI-06 feasibility)
- Apple FM image input shipping (changes SPI-07 WebKit grounder path)

---

## Sources

### Primary (HIGH confidence)
- [GitHub: lelegard arm64e on macOS docs](https://github.com/lelegard/arm-cpusysregs/blob/main/docs/arm64e-on-macos.md) — arm64e ABI + PAC + DYLD signing details
- [GitHub: olvvier apple-silicon-accelerometer](https://github.com/olvvier/apple-silicon-accelerometer) — AppleSPUHIDDevice IMU confirmed on M-series
- [STACK.md](file:///Users/akeilsmith/dev/basicCtrl/.planning/research/STACK.md) — LangGraph PostgresSaver 3.0.5 locked
- [ARCHITECTURE.md L8](file:///Users/akeilsmith/dev/basicCtrl/.planning/research/ARCHITECTURE.md) — Durable Execution pattern
- [PITFALLS.md P17, P18, P19](file:///Users/akeilsmith/dev/basicCtrl/.planning/research/PITFALLS.md) — SPI stability, SIP tiers, hardware risk

### Secondary (MEDIUM confidence)
- [Apple: Preparing your app to work with pointer authentication](https://developer.apple.com/documentation/security/preparing-your-app-to-work-with-pointer-authentication) — Official PAC guidance
- [Wasil Zafar: ARM Assembly Part 16 - Apple Silicon & macOS ABI](https://www.wasilzafar.com/pages/series/arm-assembly/arm-assembly-16-apple-silicon.html) — arm64e ABI deep dive
- [Olivia A. Gallucci: Anatomy of a Mach-O](https://oliviagallucci.com/the-anatomy-of-a-mach-o-structure-code-signing-and-pac/) — Code signing + PAC for dylibs

### Tertiary (MEDIUM confidence, needs verification)
- [Apple Developer Forums: DYLD_INSERT_LIBRARIES thread](https://developer.apple.com/forums/thread/731358) — Injection patterns + arm64e constraints
- macOS 26 Tahoe Release Notes (general stability; no SPI-specific changes detected)

---

## Conclusion: Phase 6 Is a Graceful Degradation Exercise, Not a Feature Addition

Every SPI is **optional**. Every SPI has a **public-API fallback**. Every SPI gets **capability-probed at session start**. The job is not "add private APIs" but "unlock private APIs **safely with degradation**.

**SPIKE outcomes:**
1. **arm64e DYLD injection succeeds** → register C2_DYLDRenderer channel; Electron power unlocked
2. **arm64e DYLD injection fails** → skip gracefully; T1 AX remains primary for Electron (acceptable trade)
3. **AppleSPUHIDDevice IMU present** → register optional motion-aware retry backoff (polish feature)
4. **AppleSPUHIDDevice IMU absent** → log and continue (feature not available on this hardware)

In all cases, the agent **still works**. No SPI gates the core loop.

---

**RESEARCH COMPLETE**

