"""mcp__basicCtrl__fill_form — drive any web form via the CDP daemon.

One MCP tool that wraps the cross-app form-fill primitives in
``basicctrl.browser.form_fill``. Designed so the next-session planner
discovers it through the tool list + reads
``basicctrl/skills/_generic/web-form-fill.md`` for context.

Actions:
  - inspect  — open a URL, click a CTA, return the form's field
               schema (idx, type, label, placeholder) so caller can
               build a field_map.
  - fill_and_submit — fill a field_map + click submit + read
                      validation errors + strict-verify confirmation
                      phrase. Returns the same schema as
                      ``form_fill.rsvp_form``.
  - submit_only     — for cases where caller already filled fields
                      via direct CDP and just needs strict-verify
                      submit + post-state read.

Why this exists as its own tool:
  - The browser tool drives raw CDP (navigate, click_xy, js).
    That's lower-level than the typical agent task ("RSVP me to
    this event").
  - Agents currently re-invent text-fill + combobox + validation-
    retry every session. This tool is the single chokepoint that
    captures the cross-app pattern.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal, Optional

import structlog
from mcp.server.fastmcp import FastMCP


_log = structlog.get_logger()


async def _run_in_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def register_form_fill_tool(proxy: FastMCP) -> None:
    """Register mcp__basicCtrl__fill_form on the proxy."""

    @proxy.tool(
        name="fill_form",
        description=(
            "Fill + submit ANY web form (RSVP, signup, contact, survey) "
            "via the CDP browser daemon. Cross-app: lu.ma, Partiful, "
            "Eventbrite, Typeform, Google Forms, etc.\n\n"
            "BEFORE USING: read basicctrl/skills/_generic/web-form-fill.md "
            "for the cross-app pattern (text vs combobox vs checkbox, "
            "React-friendly setters, validation-retry, strict-verify). "
            "Also read any per-platform .md (e.g. basicctrl/skills/lu.ma/) "
            "for site-specific quirks (SMS sign-in, host-questions modals).\n\n"
            "ACTIONS\n"
            "  inspect(url, cta_pattern?)\n"
            "    → navigate to url, click first button matching cta_pattern\n"
            "      (default 'register|request|sign up|join|rsvp'), wait\n"
            "      for modal, return field schema:\n"
            "      [{idx, type, name, placeholder, label}, ...]\n"
            "    Use the returned label text to build field_map matching\n"
            "    the user's profile + task context.\n\n"
            "  fill_and_submit(field_map, submit_text?)\n"
            "    → fill all fields per field_map, click submit, read\n"
            "      validation errors, strict-verify confirmation.\n"
            "    field_map is JSON: {\"<idx>\": {\"type\":\"text|combobox|checkbox\",\n"
            "                                    \"value\": <str|bool>}}\n"
            "    Returns: {ok, verified, filled_count, validation_errors,\n"
            "              missing_fields, post_body_excerpt}\n\n"
            "  submit_only(submit_text?)\n"
            "    → click submit on already-filled form, return verify state.\n\n"
            "STRICT-VERIFY: tool only sets verified=True when an explicit\n"
            "confirmation PHRASE is found in body innerText (e.g. 'request\n"
            "received', \"you're on the waitlist\", 'thanks for registering').\n"
            "It will NOT false-positive on substring matches in body labels.\n\n"
            "VALIDATION RETRY: if submit fails with 'X — This field is\n"
            "required' errors, the response surfaces missing_fields. Caller\n"
            "should fix and call fill_and_submit again with corrected map.\n\n"
            "Requires the CDP browser daemon to be alive. Auto-starts via\n"
            "basicctrl.browser.admin.ensure_daemon. Chrome must have\n"
            "remote-debugging enabled (one-time chrome://inspect tick)."
        ),
    )
    async def fill_form(
        action: Literal["inspect", "fill_and_submit", "submit_only"],
        url: Optional[str] = None,
        cta_pattern: str = r"register|request to join|sign up|join waitlist|one-click register|rsvp",
        field_map: Optional[dict[str, dict[str, Any]]] = None,
        submit_text: str = r"register|request|join|submit|send|rsvp",
    ) -> dict[str, Any]:
        from basicctrl.browser import admin, helpers
        from basicctrl.browser import form_fill as ff

        # ensure daemon
        try:
            if not await _run_in_thread(admin.daemon_alive):
                await _run_in_thread(admin.ensure_daemon)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"daemon unreachable: {exc}",
                    "hint": "Run chrome://inspect/#remote-debugging tick once."}

        if action == "inspect":
            if not url:
                return {"ok": False, "error": "inspect requires url"}
            await _run_in_thread(helpers.goto_url, url)
            await asyncio.sleep(3)

            # Click the primary CTA to open the form modal
            click_js = (
                "(() => {"
                f"const re = new RegExp({json.dumps(cta_pattern)}, 'i');"
                "const btn = [...document.querySelectorAll('button, a')]"
                "  .find(el => re.test((el.innerText||'').trim()));"
                "if (!btn) return JSON.stringify({clicked:false,"
                "  available:[...document.querySelectorAll('button')]"
                "    .map(b=>(b.innerText||'').trim()).filter(t=>t).slice(0,15)});"
                "btn.click();"
                "return JSON.stringify({clicked:true, text: btn.innerText.trim()});"
                "})()"
            )
            cta = json.loads(await _run_in_thread(helpers.js, click_js))
            await asyncio.sleep(3)

            # Inspect form fields with labels
            schema_js = (
                "(() => {"
                "  const inputs = [...document.querySelectorAll('input, textarea')].map((el, i) => {"
                "    let label = ''; let cur = el;"
                "    for (let j = 0; j < 6; j++) {"
                "      cur = cur.parentElement; if (!cur) break;"
                "      const c = cur.cloneNode(true);"
                "      c.querySelectorAll('input, textarea, select, button').forEach(x => x.remove());"
                "      const t = (c.innerText||'').trim();"
                "      if (t && t.length > 3 && t.length < 250) { label = t; break; }"
                "    }"
                "    return {idx: i, type: el.type, name: el.name, placeholder: el.placeholder,"
                "            checked: el.checked, label: label.slice(0, 200)};"
                "  });"
                "  return JSON.stringify(inputs);"
                "})()"
            )
            raw = await _run_in_thread(helpers.js, schema_js)
            schema = json.loads(raw or "[]")
            return {
                "ok": True,
                "url": url,
                "cta": cta,
                "field_count": len(schema),
                "schema": schema,
                "hint": (
                    "Build field_map: {idx_str: {type, value}}. "
                    "type=text|combobox|checkbox. "
                    "For combobox (placeholder='Select an option'), value "
                    "must MATCH a dropdown option label exactly (case-"
                    "insensitive substring)."
                ),
            }

        if action == "fill_and_submit":
            if not field_map:
                return {"ok": False, "error": "fill_and_submit requires field_map"}
            # JSON keys are strings — convert to int indices
            normalized = {int(k): v for k, v in field_map.items()}
            result = await _run_in_thread(ff.rsvp_form, helpers, normalized, submit_text)
            return result

        if action == "submit_only":
            from basicctrl.browser.form_fill import (
                install_helpers, click_submit, read_validation_errors
            )
            await _run_in_thread(install_helpers, helpers)
            sub = await _run_in_thread(click_submit, helpers, submit_text)
            await asyncio.sleep(3)
            errs = await _run_in_thread(read_validation_errors, helpers)
            body = await _run_in_thread(helpers.js, "document.body.innerText.slice(0, 1500)")
            body_lower = (body or "").lower()
            confirm = [p for p in [
                'request received', 'request sent', "you're going",
                "you're on the waitlist", 'pending approval',
                'thanks for registering', 'check your email'
            ] if p in body_lower]
            return {
                "ok": not errs,
                "verified": bool(confirm),
                "submit": sub,
                "validation_errors": errs[:5],
                "signals": confirm,
                "post_body_excerpt": (body or "")[:500],
            }

        return {"ok": False, "error": f"unknown action: {action}"}

    _log.info("form_fill_tool.registered", tool="fill_form")
