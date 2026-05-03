"""Race orchestrator — wires translators + channels + verifier + idempotency.

Per CONTEXT.md D-09..D-19 (race policy + idempotency + AS stagger + receipts).
Per RESEARCH.md Pattern 2 (anyio Race Pattern) + Pitfall A (shielded scopes
don't see cancel) + Pitfall F (first-claimer-wins by design).

Central contract (RaceOrchestrator.execute):
    1. resolve_race_policy(policy, action_type) BEFORE fan-out (T-2-09)
    2. Classify app to get translator priority (D-20)
    3. Resolve target via highest-priority translator
    4. Build ActionCanonical (tier/channel left None; filled by winner)
    5. Subscribe AX notifs via Phase 1 AXObserverManager.expect (subscribe-before-fire)
    6. Capture HoarePre via L1Cheap.snapshot
    7. Pick channels via registry; build coros with AS stagger (D-15)
    8. Race via race_first_complete (RACE) or single await (SINGLE_CHANNEL)
    9. Verify via Phase 1 Aggregator.verify
   10. Record DuplicateReceipt (D-19) AFTER verify
   11. Fill action.tier + .channel from winner; emit race telemetry
   12. Return (ActionCanonical, HoarePost)

D-17: token claim is owned by the WINNING channel — orchestrator does NOT
pre-claim. Channels each call store.try_claim BEFORE their syscall.

D-13: anyio 4.13 has no built-in FIRST_COMPLETED. race_first_complete is the
custom wrapper using tg.cancel_scope.cancel() to terminate losers.

Pitfall A: channel coros must use the default CancelScope(shield=False).
Wrapping channel bodies in a shielded scope breaks race-cancel correctness.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Awaitable, Callable, Optional

import anyio
import structlog

from basicctrl.actions.channel_registry import ChannelRegistry
from basicctrl.actions.channels.base import Channel, ChannelOutcome
from basicctrl.actions.duplicate_receipt import DuplicateReceipt
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.actions.race_policy import RacePolicy, resolve_race_policy
from basicctrl.state.causal_dag import ActionCanonical, HoarePost
from basicctrl.translators.base import TargetSpec, TranslatorTarget
from basicctrl.translators.registry import TranslatorRegistry
from basicctrl.visualizer.driver import VisualizerBus
from basicctrl.visualizer.hud_driver import HUDDriver


_log = structlog.get_logger()


# AS stagger constant per D-15 (500 ms default; "fast" verbs override to 0 ms).
AS_STAGGER_MS_DEFAULT = 500


class NoTargetResolvable(RuntimeError):
    """Raised when no translator could resolve the target_spec."""


async def race_first_complete(
    coros: list[Awaitable[ChannelOutcome]],
    *,
    on_first_winner: Optional[Callable[[int, ChannelOutcome], Any]] = None,
) -> tuple[int, ChannelOutcome, list[Any]]:
    """Race coroutines; first to return ChannelOutcome(status='fired') wins.
    Cancel losers via tg.cancel_scope.cancel().

    Per D-13 / RESEARCH Pattern 2: anyio 4.13 has no built-in FIRST_COMPLETED.
    This wrapper stores results in a shared list, sets winner_idx on first
    successful outcome, and cancels the task group's cancel scope.

    Per Pitfall A: channel coros MUST use CancelScope(shield=False) (default).
    Shielded scopes won't receive the cancel signal — losers will leak.

    Args:
        coros: list of awaitables, one per channel (already constructed).
        on_first_winner: optional callback invoked with (idx, outcome) when
            the first winner is identified. Used by RaceOrchestrator to set
            the cancel_event so channels with pre-syscall kill-switches (D-18)
            can short-circuit before their syscall. May be sync or async.

    Returns:
        (winner_idx, winner_outcome, all_results_or_exceptions)
        winner_idx == -1 if no channel returned status='fired'.
    """
    n = len(coros)
    results: list[Any] = [None] * n
    winner_idx_box: list[int] = [-1]

    async def _runner(idx: int, coro: Awaitable[ChannelOutcome], tg: Any) -> None:
        try:
            outcome = await coro
            results[idx] = outcome
            # First non-skipped/non-cancelled/non-errored outcome wins.
            if (
                winner_idx_box[0] == -1
                and isinstance(outcome, ChannelOutcome)
                and outcome.status == "fired"
            ):
                winner_idx_box[0] = idx
                if on_first_winner is not None:
                    res = on_first_winner(idx, outcome)
                    # Support both sync and async callbacks.
                    if hasattr(res, "__await__"):
                        await res
                tg.cancel_scope.cancel()
        except anyio.get_cancelled_exc_class():
            # Loser path — record cancelled marker if we don't already have one.
            if results[idx] is None:
                # We don't know the channel name from the coro; the runner
                # doesn't have it. Use 'C1' as a placeholder; orchestrator
                # logs the real channel via _log_race using the coro index.
                results[idx] = ChannelOutcome(channel="C1", status="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            results[idx] = exc

    async with anyio.create_task_group() as tg:
        for idx, coro in enumerate(coros):
            tg.start_soon(_runner, idx, coro, tg)

    if winner_idx_box[0] == -1:
        return (
            -1,
            ChannelOutcome(channel="C1", status="errored", error="no_winner"),
            results,
        )
    winner_outcome = results[winner_idx_box[0]]
    return (winner_idx_box[0], winner_outcome, results)


class RaceOrchestrator:
    """Wires translators + channels + verifier + idempotency. ACT-02 entry point."""

    def __init__(
        self,
        translator_registry: TranslatorRegistry,
        channel_registry: ChannelRegistry,
        idem_store: IdempotencyTokenStore,
        duplicate_receipt: DuplicateReceipt,
        axmgr: Any,         # basicctrl.verifier.axobserver.AXObserverManager
        aggregator: Any,    # basicctrl.verifier.aggregator.Aggregator
        l1_cheap: Any,      # basicctrl.verifier.ensemble.l1_cheap.L1Cheap
        classifier: Any,    # async classify(bundle_id, pid) -> AppProfile
        session_writer: Any,  # basicctrl.persist.session_writer.SessionWriter
    ) -> None:
        self._translators = translator_registry
        self._channels = channel_registry
        self._store = idem_store
        self._duplicate = duplicate_receipt
        self._axmgr = axmgr
        self._agg = aggregator
        self._l1 = l1_cheap
        self._classify = classifier
        self._session = session_writer

    async def execute(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
        action_type: str,
        payload: dict[str, object],
        race_policy: RacePolicy = RacePolicy.AUTO,
        session_id: str = "",
    ) -> tuple[ActionCanonical, HoarePost]:
        """Race orchestrator entry point. See module docstring for the contract."""
        # 1. Resolve race policy (D-09 / T-2-09 server-side override).
        effective = resolve_race_policy(race_policy, action_type)

        # 2. Classify app to get translator priority (D-20).
        profile = await self._classify(bundle_id, pid)

        # 3. Resolve target via translators in priority order.
        translators = self._translators.select_for_priority(profile.translator_priority)
        target: Optional[TranslatorTarget] = None
        for trans in translators:
            target = await trans.resolve(bundle_id, pid, target_spec)
            if target is not None and await trans.validate(target):
                break
            target = None
        if target is None:
            raise NoTargetResolvable(
                f"no translator could resolve target_spec={target_spec!r}"
            )

        # 4. Build action.
        action = ActionCanonical(
            id=uuid.uuid4().hex,
            step_idx=0,
            kind="MUTATE",
            target_key=target.element.composite_key,
            action_type=action_type,
            payload=payload,
            tier=None,        # filled by winner below
            channel=None,     # filled by winner below
            timestamp_ns=time.monotonic_ns(),
            session_id=session_id or self._session.session_id,
        )

        # 5. Subscribe AX notifs BEFORE fan-out (Phase 1 hard rule + F9 fix).
        # subscribe_pending is sync — it registers the subscription with the
        # bridge (capturing subscription_ts_ns BEFORE the action fires) and
        # returns the Future for L0Push to await post-fire. The previous
        # `await self._axmgr.expect(timeout_ms=100)` was a 100ms-per-action
        # no-op that dropped the waiter before the action even fired (F9).
        #
        # F9 part 2: subscribe at the AXApplication ROOT, not at the button.
        # Calculator's keypad buttons don't fire AXValueChanged — the display
        # (a child somewhere else in the AX tree) does. Subscribing at the
        # root catches notifications from any descendant; per-action_id
        # filtering ensures we only see THIS action's events.
        notifs = ["AXValueChanged", "AXFocusedUIElementChanged"]
        pre_fire_future = None
        ax_app_root = _ax_application_root(pid)
        sub_element = ax_app_root if ax_app_root is not None else target.ax_element
        try:
            pre_fire_future = self._axmgr.subscribe_pending(
                target=target.element,
                notifs=notifs,
                action_id=action.id,
                ax_element=sub_element,
            )
            # AXObserver registration crosses an IPC boundary into the target
            # app's process. Give the target's run loop a tick to install the
            # observation before we fire the action — without this warmup,
            # events emitted within the first ~30ms of subscribe propagate
            # back BEFORE the observer table is live and never reach us.
            # Empirically this is the same warmup the existing test_axobserver
            # tests pay via `await asyncio.sleep(0.05)` before _fire_cgevent_click.
            if pre_fire_future is not None:
                await anyio.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            # AX subscription failure is non-fatal — verifier falls back to
            # L1 cheap diff (and L0 returns 0.0 signals).
            _log.debug(
                "race.axmgr_subscribe_failed",
                action_id=action.id,
                error=str(exc),
            )

        # 6. Capture HoarePre.
        before_l1 = await self._l1.snapshot(target.element)

        # 6b. Visualizer ghost cursor (Wave 3 integration).
        # Show ghost cursor BEFORE firing to visualize where the action targets.
        if target.element.bbox is not None:
            bbox_centroid = target.element.bbox.centroid
            await VisualizerBus.send_ghost_cursor(
                x=float(bbox_centroid[0]),
                y=float(bbox_centroid[1]),
                duration_ms=200,  # 200ms lerp per UI-SPEC
            )

        # 7. Pick channels via registry (D-14 default mapping).
        candidate_channels = self._channels.select(profile.translator_priority, effective)
        if not candidate_channels:
            raise NoTargetResolvable(
                f"no channels registered for priority={profile.translator_priority!r}"
            )

        # 8. Build channel coros + apply AS stagger (D-15).
        cancel_event = anyio.Event()
        coros = self._build_channel_coros(
            action, target, candidate_channels, cancel_event
        )

        # 9. Fire (race or single-channel).
        if effective == RacePolicy.RACE and len(coros) > 1:
            def _on_first(_idx: int, _outcome: ChannelOutcome) -> None:
                cancel_event.set()

            winner_idx, _outcome, all_outcomes = await race_first_complete(
                coros, on_first_winner=_on_first
            )
        else:
            # Single-channel path: pick first; no race wrapper.
            outcome = await coros[0]
            all_outcomes = [outcome]
            winner_idx = 0 if (
                isinstance(outcome, ChannelOutcome) and outcome.status == "fired"
            ) else -1

        # 10. Verify (Phase 1 ladder). Hand pre_fire_future to L0Push so it
        # awaits the subscription registered BEFORE the action fired (F9).
        post = await self._agg.verify(
            action=action,
            target=target.element,
            notifs=notifs,
            before_l1=before_l1,
            ax_element=target.ax_element,
            timeout_ms=50,
            pre_fire_future=pre_fire_future,
        )

        # 10b. Visualizer post-action callbacks (Wave 3 integration).
        # Send highlight box if target has bbox.
        if target.element.bbox is not None:
            await VisualizerBus.send_highlight(
                bbox_x=target.element.bbox.x,
                bbox_y=target.element.bbox.y,
                bbox_width=target.element.bbox.w,
                bbox_height=target.element.bbox.h,
                label=target.element.label[:40],
                tier=action.tier or "T1",
                channel=action.channel or "C1",
            )
        # Send HUD update via hud_driver (action added to history).
        hud = HUDDriver()
        if target.element.label:
            hud.append_action(
                action_type=action_type,
                target_label=target.element.label,
                tier=action.tier or "T1",
                channel=action.channel or "C1",
                status="verified" if post.verified else "failed",
                status_detail=post.healed_to if post.healed_to else None,
            )
            hud.send_hud_update()

        # 11. Record duplicate-receipt 2s ring buffer (D-19, AFTER verify).
        self._duplicate.record(
            target.element.composite_key, action_type, time.monotonic_ns()
        )

        # 12. Fill action.tier + .channel from winner (was Optional in Phase 1).
        action_filled = action
        if winner_idx >= 0 and isinstance(all_outcomes[winner_idx], ChannelOutcome):
            winning_channel = all_outcomes[winner_idx].channel
            winning_tier = self._channels.tier_for_channel(winning_channel)
            action_filled = action.model_copy(
                update={"tier": winning_tier, "channel": winning_channel}
            )

        # 13. Emit race telemetry.
        self._log_race(action_filled, all_outcomes, winner_idx, post, candidate_channels)

        return action_filled, post

    def _build_channel_coros(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        channels: list[Channel],
        cancel_event: anyio.Event,
    ) -> list[Awaitable[ChannelOutcome]]:
        """Build channel.fire coros, applying AS stagger to C4 per D-15."""
        coros: list[Awaitable[ChannelOutcome]] = []
        as_class = (target.extras or {}).get("as_class", "slow")
        stagger_ms = 0 if as_class == "fast" else AS_STAGGER_MS_DEFAULT
        for ch in channels:
            if ch.name == "C4" and stagger_ms > 0:
                coros.append(
                    self._staggered_fire(ch, action, target, cancel_event, stagger_ms)
                )
            else:
                coros.append(ch.fire(action, target, self._store, cancel_event))
        return coros

    async def _staggered_fire(
        self,
        ch: Channel,
        action: ActionCanonical,
        target: TranslatorTarget,
        cancel_event: anyio.Event,
        stagger_ms: int,
    ) -> ChannelOutcome:
        """C4 AppleScript stagger per D-15 — sleep before invoking ch.fire so
        faster channels (C2/C5) get a head start. AppleEvent at C4 is
        uncancellable mid-flight; this stagger pushes execution past most race
        windows."""
        await anyio.sleep(stagger_ms / 1000.0)
        if cancel_event.is_set():
            return ChannelOutcome(
                channel="C4",
                status="cancelled",
                skipped_reason="as_stagger_cancelled",
            )
        return await ch.fire(action, target, self._store, cancel_event)

    def _log_race(
        self,
        action: ActionCanonical,
        all_outcomes: list[Any],
        winner_idx: int,
        post: HoarePost,
        candidate_channels: list[Channel],
    ) -> None:
        """Emit race_winner + race_loser NDJSON events."""
        for idx, outcome in enumerate(all_outcomes):
            if not isinstance(outcome, ChannelOutcome):
                continue
            event_name = "race_winner" if idx == winner_idx else "race_loser"
            # Resolve channel name from the candidate at this index when the
            # outcome's channel is the placeholder 'C1' (set by race_first_complete
            # for cancelled losers). Otherwise trust the outcome's channel.
            real_channel = outcome.channel
            if (
                idx < len(candidate_channels)
                and outcome.status == "cancelled"
                and candidate_channels[idx].name != outcome.channel
            ):
                real_channel = candidate_channels[idx].name
            self._session.append_action_log(
                {
                    "event": event_name,
                    "action_id": action.id,
                    "channel": real_channel,
                    "status": outcome.status,
                    "fired_at_ns": outcome.fired_at_ns,
                    "error": outcome.error,
                    "skipped_reason": outcome.skipped_reason,
                    "verifier_confidence": post.confidence,
                    "verifier_verified": post.verified,
                }
            )


def _ax_application_root(pid: int) -> Optional[Any]:
    """Return AXUIElement for the application root, or None if PyObjC isn't
    available (CI / non-macOS hosts). Used by F9 subscribe-at-root pattern.

    Cheap call (~10us); the orchestrator does this once per action."""
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
        )
    except ImportError:
        return None
    try:
        return AXUIElementCreateApplication(pid)
    except Exception:  # noqa: BLE001
        return None
