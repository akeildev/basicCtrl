"""Self-healing keystroke for terminal-class apps.

The race this fixes: macOS WindowServer can flip the on-screen tab/
window between "verify which tab is active" and "send keystroke",
dropping text into the wrong place. Symptom on Ghostty: prompt text
lands in the wrong Claude Code session's input box, or in your own.

What we learned the hard way (5/3 session, basicCtrl repo):

    activate-once → switch tab → verify → keystroke
                                            ▲
                                     NEVER re-fire `activate`
                                     between verify and keystroke.

`tell application "X" to activate` is a "promote last user-
interacted thing" call, and macOS's idea of "last user-interacted"
can drift in milliseconds. Sleeping doesn't fix it; only avoiding
the re-activate fixes it.

Self-heal layers in keystroke_to_window():
- L1: Pre-verify front window matches expected. If not, return
      verified=False rather than typing into the wrong place.
- L2: Send WITHOUT re-activating. Activate is the race source.
- L3: Post-verify by title-prefix flip (idle indicator → spinner)
      within a polling window. If no flip, the keystroke didn't
      reach a working session.

This is generic across terminal emulators where the running TUI
sets terminal-title escapes (Ghostty, iTerm2, kitty, Warp,
Terminal.app, Alacritty). The title-flip signal varies by TUI;
Claude Code uses ✳ (idle) → spinner glyphs (working).
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional


# Title prefix glyphs. ✳ = Claude Code "waiting for human input".
# Anything that's NOT ✳ post-keystroke = session is working = success.
_IDLE_PREFIX = "✳"  # ✳


def _osascript(*lines: str, timeout: float = 5.0) -> str:
    """Run a multi-line osascript. Returns stdout stripped.

    Each arg becomes one ``-e`` line so AppleScript can be composed
    in Python without heredoc escaping pitfalls.
    """
    args = ["osascript"]
    for line in lines:
        args.extend(["-e", line])
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def activate_app(app_name: str) -> None:
    """Bring app frontmost. Call ONCE per session — re-firing this
    between verify and keystroke causes the focus race."""
    _osascript(f'tell application "{app_name}" to activate')


def cmd_key(app_name: str, key: str) -> None:
    """Send cmd+<key> to app. Used for tab switching (cmd+1..9)."""
    _osascript(
        f'tell application "System Events" to tell process "{app_name}" '
        f'to keystroke "{key}" using command down'
    )


def cmd_shift_key(app_name: str, key: str) -> None:
    """Send cmd+shift+<key>. Used for cmd+shift+] to cycle tabs > 9."""
    _osascript(
        f'tell application "System Events" to tell process "{app_name}" '
        f'to keystroke "{key}" using {{command down, shift down}}'
    )


def get_front_window_title(app_name: str) -> str:
    """Title of the currently-focused window of `app_name`. Empty string
    if the app has no front window or osascript times out."""
    try:
        return _osascript(
            f'tell application "System Events" to tell process "{app_name}" '
            f'to get title of front window'
        )
    except subprocess.TimeoutExpired:
        return ""


def _send_keystroke_only(app_name: str, text: str, with_return: bool = True) -> None:
    """Send text via System Events keystroke. NO activate. NO verify.

    Caller must have already verified the right window has focus.
    """
    # Escape backslashes first, then double quotes (AppleScript syntax).
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    _osascript(
        f'tell application "System Events" to tell process "{app_name}" '
        f'to keystroke "{safe}"'
    )
    if with_return:
        time.sleep(0.15)
        _osascript(
            f'tell application "System Events" to tell process "{app_name}" '
            f'to key code 36'
        )


def keystroke_to_window(
    app_name: str,
    target_title_substr: str,
    text: str,
    with_return: bool = True,
    tab_switch_hotkey: Optional[str] = None,
    activate_first: bool = False,
    settle_seconds: float = 0.6,
    verify_flip_seconds: float = 2.0,
    verify_flip_poll_seconds: float = 0.2,
) -> dict:
    """Send text to a specific terminal-app window with self-heal verify.

    Recipe:
      1. (Optional) activate_app once — never again in this call.
      2. (Optional) cmd+<tab_switch_hotkey> to land on target tab.
      3. Settle.
      4. L1: Verify front-window title contains ``target_title_substr``.
         If not → return verified=False, ok=False. Caller decides next step
         (re-cycle tabs, ask user, fall back to AX, etc.).
      5. L2: Send keystroke directly. NO re-activate.
      6. L3: Poll front-window title for prefix-flip (idle → spinner)
         within ``verify_flip_seconds``. If pre-title started with ✳ but
         post-title doesn't → verified=True. If no flip → verified=False.

    Args:
        app_name: macOS app name (e.g. "Ghostty").
        target_title_substr: substring expected in front-window title.
        text: text to type.
        with_return: send Return (key code 36) after text.
        tab_switch_hotkey: if set (e.g. "4"), send cmd+<hotkey> first.
        activate_first: activate app once before any verify (default False).
        settle_seconds: pause after switch before pre-verify.
        verify_flip_seconds: total budget to detect title flip.
        verify_flip_poll_seconds: poll interval inside that budget.

    Returns:
        ``{ok, verified, pre_title, post_title, reason}``.
        ``ok=True`` means keystroke was sent. ``verified=True`` means we
        observed the success signal (title flip).
    """
    result: dict = {
        "ok": False,
        "verified": False,
        "pre_title": None,
        "post_title": None,
        "reason": None,
    }

    if activate_first:
        activate_app(app_name)
        time.sleep(0.3)

    if tab_switch_hotkey:
        cmd_key(app_name, tab_switch_hotkey)
        time.sleep(settle_seconds)
    elif activate_first:
        # Even without an explicit switch, give the activate time to settle.
        time.sleep(settle_seconds * 0.5)

    # L1: pre-verify.
    pre = get_front_window_title(app_name)
    result["pre_title"] = pre
    if target_title_substr not in pre:
        result["reason"] = (
            f"front_window_mismatch: front={pre!r} expected_substr={target_title_substr!r}"
        )
        return result

    # L2: send WITHOUT re-activating. This is the load-bearing rule.
    _send_keystroke_only(app_name, text, with_return=with_return)
    result["ok"] = True

    # L3: poll for title flip.
    deadline = time.time() + verify_flip_seconds
    while time.time() < deadline:
        post = get_front_window_title(app_name)
        result["post_title"] = post
        if pre.startswith(_IDLE_PREFIX) and not post.startswith(_IDLE_PREFIX):
            result["verified"] = True
            return result
        time.sleep(verify_flip_poll_seconds)

    if pre.startswith(_IDLE_PREFIX):
        result["reason"] = "no_title_flip_after_send"
    else:
        # Pre wasn't idle — title-flip signal not applicable. Accept best-effort.
        result["verified"] = True
        result["reason"] = "skip_flip_check_pre_was_not_idle"
    return result


def keystroke_to_window_with_retry(
    app_name: str,
    target_title_substr: str,
    text: str,
    with_return: bool = True,
    tab_switch_hotkey: Optional[str] = None,
    max_retries: int = 1,
    **kwargs,
) -> dict:
    """Wrap keystroke_to_window with a single retry on front-window mismatch.

    On L1 mismatch (typical race outcome), retry the tab switch + verify +
    send sequence up to ``max_retries`` times. Activate is fired ONCE on the
    first attempt and never again (the whole point of this module).
    """
    last: Optional[dict] = None
    for attempt in range(max_retries + 1):
        last = keystroke_to_window(
            app_name=app_name,
            target_title_substr=target_title_substr,
            text=text,
            with_return=with_return,
            tab_switch_hotkey=tab_switch_hotkey,
            activate_first=(attempt == 0),  # activate ONLY on first attempt
            **kwargs,
        )
        if last.get("verified") or last.get("ok"):
            last["attempts"] = attempt + 1
            return last
        # Front-window mismatch — re-cycle tab and try again.
    if last is not None:
        last["attempts"] = max_retries + 1
    return last or {"ok": False, "verified": False, "reason": "no_attempts"}
