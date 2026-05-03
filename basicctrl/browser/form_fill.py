"""Generic web-form fill + submit + validation-retry.

Cross-app pattern. Works on lu.ma, Partiful, Eventbrite, Typeform,
Google Forms — anything that uses standard <input>/<textarea> for
text fields and combobox-styled <input role="combobox"> or click-to-
open dropdowns for selects.

Three primitives:
  - fill_text_input(idx, value)         — react-friendly value setter
  - select_combobox_option(idx, label)  — click input, find option
                                          containing label, click it
  - submit_form(submit_text)            — find + click submit button

Plus the orchestrator:
  - rsvp_form(field_map, submit_text)   — fill all → submit → read
                                          validation errors → return
                                          structured result

Field map shape:
  {
    0: {"type": "text", "value": "Akeil Smith"},
    7: {"type": "combobox", "value": "Yes"},
    10: {"type": "checkbox", "value": True},
  }
  Indices match the page's input order at submit-time.

Result shape:
  {
    "ok": bool,                     # form submitted without validation errors
    "verified": bool,               # post-submit confirmation phrase observed
    "filled_count": int,
    "validation_errors": [str, ...],
    "post_body_excerpt": str,
    "missing_fields": [str, ...],   # parsed from validation errors
  }

Lessons codified (do not repeat):
  - lu.ma combobox is a text-styled <input> with role="combobox" or
    placeholder "Select an option". Plain `value=` setter doesn't fire
    the dropdown. Must click input → wait → click matching option from
    the dropdown listbox.
  - React's onChange listens to .dispatchEvent('input') NOT direct
    .value assignment. Use the prototype-descriptor setter to be
    React-friendly.
  - lu.ma renders validation errors with class containing 'error' or
    role="alert" near each invalid field. Body innerText concatenates
    all of them, so a single body scan finds them.
  - "submit" buttons can match by [type=submit] OR by visible text.
    Prefer [type=submit] inside a <form>; fallback to text match on
    'register'/'request'/'submit'/'send'.
"""
from __future__ import annotations

import json
import time
from typing import Optional


# JS helpers injected once per session.
_HELPER_JS = r"""
window.__bCFormFill = {
  // React-friendly value setter (works for lu.ma, Notion, ChatGPT, Discord,
  // anything using controlled inputs).
  set: (el, value) => {
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                            : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  },
  // List options visible in a dropdown listbox after a combobox is open.
  // Lu.ma uses [role="option"]; some sites use <li> in a [role="listbox"].
  visibleOptions: () => {
    const opts = [...document.querySelectorAll('[role="option"], [role="listbox"] li, [class*="dropdown"] li, [class*="menu-item"]')];
    return opts.map(o => ({text: (o.innerText||'').trim().slice(0, 100)})).filter(x => x.text);
  },
  // Click an option whose text contains needle (case-insensitive).
  // Returns the picked text or null if no match.
  pickOption: (needle) => {
    const re = new RegExp(needle.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&'), 'i');
    const opts = [...document.querySelectorAll('[role="option"], [role="listbox"] li, [class*="dropdown"] li, [class*="menu-item"]')];
    const match = opts.find(o => re.test(o.innerText || ''));
    if (!match) return null;
    match.scrollIntoView({block: 'nearest'});
    match.click();
    return (match.innerText || '').trim();
  },
};
"""


# ---------------------------------------------------------------------------


def install_helpers(helpers_module) -> None:
    """Inject __bCFormFill into the active page. Idempotent.

    helpers_module is `basicctrl.browser.helpers` — passed in to avoid
    a circular import.
    """
    helpers_module.js(_HELPER_JS)


def fill_text_input(helpers_module, idx: int, value: str) -> str:
    """Set value on the idx-th input/textarea. Returns 'ok' or error str."""
    return helpers_module.js(f"""
(() => {{
  const all = document.querySelectorAll('input, textarea');
  const el = all[{idx}];
  if (!el) return 'no_input_at_index';
  window.__bCFormFill.set(el, {json.dumps(value)});
  el.dispatchEvent(new Event('blur', {{bubbles: true}}));
  return 'ok';
}})()
""")


def select_combobox_option(helpers_module, idx: int, option_label: str,
                            wait_after_open: float = 0.5) -> dict:
    """Open the idx-th combobox-styled input and pick the option whose
    text contains ``option_label`` (case-insensitive substring match).

    Returns {ok, picked, available_options} so caller can self-heal:
    if ok=False but available_options has values, retry with a label
    that matches one of them.
    """
    open_res = helpers_module.js(f"""
(() => {{
  const all = document.querySelectorAll('input, textarea');
  const el = all[{idx}];
  if (!el) return JSON.stringify({{ok: false, reason: 'no_input_at_index'}});
  el.focus();
  el.click();
  return JSON.stringify({{ok: true}});
}})()
""")
    if 'no_input' in open_res:
        return {"ok": False, "reason": "no_input_at_index"}
    time.sleep(wait_after_open)

    options_json = helpers_module.js("JSON.stringify(window.__bCFormFill.visibleOptions())")
    options = json.loads(options_json or "[]")
    if not options:
        return {"ok": False, "reason": "no_options_visible_after_open",
                "available_options": []}

    picked = helpers_module.js(f"window.__bCFormFill.pickOption({json.dumps(option_label)})")
    if picked in (None, "null", ""):
        return {"ok": False, "reason": "no_match",
                "wanted": option_label,
                "available_options": [o['text'] for o in options]}
    time.sleep(0.3)
    return {"ok": True, "picked": picked.strip('"'),
            "available_options": [o['text'] for o in options]}


def set_checkbox(helpers_module, idx: int, checked: bool) -> str:
    return helpers_module.js(f"""
(() => {{
  const all = document.querySelectorAll('input, textarea');
  const el = all[{idx}];
  if (!el || el.type !== 'checkbox') return 'not_checkbox';
  if (el.checked !== {str(checked).lower()}) {{
    el.click();
  }}
  return 'ok';
}})()
""")


def click_submit(helpers_module, submit_text_pattern: str = r'register|request|submit|send|join|rsvp') -> dict:
    """Find a button matching the pattern and click it. Returns
    {clicked, text, candidates}."""
    res = helpers_module.js(f"""
(() => {{
  const re = new RegExp({json.dumps(submit_text_pattern)}, 'i');
  // Prefer <button type=submit> inside a <form>
  const submitTyped = [...document.querySelectorAll('form button[type="submit"], button[type="submit"]')]
    .find(b => re.test((b.innerText||'').trim()));
  if (submitTyped) {{
    submitTyped.click();
    return JSON.stringify({{clicked: true, via: 'submit_type', text: submitTyped.innerText.trim()}});
  }}
  // Fallback: any matching visible button (last one is usually the modal CTA)
  const candidates = [...document.querySelectorAll('button')]
    .filter(b => re.test((b.innerText||'').trim()) && (b.innerText||'').trim().length < 50);
  if (candidates.length === 0) {{
    return JSON.stringify({{clicked: false, candidates: []}});
  }}
  const target = candidates[candidates.length - 1];
  target.click();
  return JSON.stringify({{clicked: true, via: 'text_fallback', text: target.innerText.trim()}});
}})()
""")
    return json.loads(res)


def read_validation_errors(helpers_module) -> list:
    """Extract validation error text from common patterns."""
    res = helpers_module.js("""
(() => {
  const sel = '[class*="error"], [class*="Error"], [role="alert"], [class*="invalid"], [class*="field-error"]';
  const errs = [...document.querySelectorAll(sel)]
    .map(e => (e.innerText||'').trim())
    .filter(t => t && t.length < 400);
  return JSON.stringify(errs);
})()
""")
    return json.loads(res or "[]")


def parse_missing_fields(errors: list) -> list:
    """Heuristic: 'X — This field is required' → 'X' is the missing field."""
    out = []
    for e in errors:
        if 'required' in e.lower():
            # field name usually before the error sentence
            parts = e.split('\n')
            if parts and parts[0].strip():
                name = parts[0].strip().rstrip('*').strip()
                if name and name.lower() not in ('this field is required.', '​'):
                    out.append(name)
    return list(dict.fromkeys(out))  # de-dup, preserve order


def rsvp_form(helpers_module, field_map: dict, submit_text: str = 'register') -> dict:
    """Fill all fields per field_map, click submit, collect post-state."""
    install_helpers(helpers_module)

    filled = 0
    fill_log = []
    for idx, spec in field_map.items():
        ftype = spec.get('type', 'text')
        val = spec.get('value')
        if ftype == 'text':
            r = fill_text_input(helpers_module, idx, val)
            fill_log.append((idx, 'text', r))
            if r == 'ok':
                filled += 1
        elif ftype == 'combobox':
            r = select_combobox_option(helpers_module, idx, val)
            fill_log.append((idx, 'combobox', r))
            if r.get('ok'):
                filled += 1
        elif ftype == 'checkbox':
            r = set_checkbox(helpers_module, idx, bool(val))
            fill_log.append((idx, 'checkbox', r))
            if r == 'ok':
                filled += 1

    time.sleep(0.5)

    # Submit
    submit_res = click_submit(helpers_module, submit_text)
    time.sleep(3.5)

    # Validation errors?
    errors = read_validation_errors(helpers_module)
    missing = parse_missing_fields(errors)

    body = helpers_module.js("document.body.innerText.slice(0, 2000)")

    # Heuristic verify — confirmation phrases
    verified = False
    body_lower = (body or '').lower()
    for phrase in ['request received', 'request sent', "you're going", 'pending approval',
                   'thanks for registering', 'thank you for registering', 'we got your',
                   'enter the code', 'verify your phone', 'check your phone', 'check your email']:
        if phrase in body_lower:
            verified = True
            break

    return {
        "ok": not errors,
        "verified": verified,
        "filled_count": filled,
        "submit": submit_res,
        "validation_errors": errors,
        "missing_fields": missing,
        "fill_log": fill_log,
        "post_body_excerpt": body[:600] if body else "",
    }
