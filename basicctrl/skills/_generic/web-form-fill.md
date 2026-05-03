# Web form fill — cross-app generic recipe

> Field-tested 2026-05-03 against lu.ma RSVP forms. Pattern is generic
> — applies to Partiful, Eventbrite, Typeform, Google Forms, anything
> that uses standard `<input>`/`<textarea>` for text + click-to-open
> dropdowns for combobox/select.

## When to use this skill

Any task where the framework needs to fill a multi-field web form and
submit it. Typical triggers:
- Event RSVP (lu.ma, Partiful, Eventbrite)
- Lead-gen / contact forms
- Sign-up / onboarding forms
- Survey / Typeform / Google Forms
- Job applications
- Newsletter signups w/ custom questions

## Mental model — three field classes

```
1. TEXT INPUT          <input type="text|email|tel"> or <textarea>
                       → fill with React-friendly value setter
                       → fires: 'input', 'change', 'blur'

2. COMBOBOX / SELECT   <input role="combobox"> styled as text, OR
                       click opens a dropdown with [role="option"] items
                       → must CLICK input first → wait for dropdown
                       → CLICK the matching option (NOT type a value)

3. CHECKBOX            <input type="checkbox">
                       → click only if state needs to flip
                       → don't .click() on already-correct state
```

## The race trap

React inputs IGNORE direct `el.value = "x"` assignment — onChange
listener doesn't fire. You must use the prototype-descriptor setter:

```js
const setter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value'
).set;
setter.call(el, value);
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
```

Codified in `basicctrl/browser/form_fill.py:fill_text_input`.

## The combobox trap

Lu.ma's "Select an option" dropdowns LOOK like text inputs but are
combobox. Naive flow fails:

```
WRONG:
  fill_text_input(idx, "yes")
  → submits "yes" as text, validation rejects: "This field is required"

RIGHT:
  click input → dropdown opens → find option matching label → click it
```

Codified in `select_combobox_option`. Returns `available_options` list
on miss so caller can self-heal by retrying with a label that matches.

## The validation-error self-heal pattern

Submit a form. If lu.ma/etc rejects, the page renders error text near
each invalid field. Generic CSS selectors that catch them:

```
[class*="error"], [class*="Error"], [role="alert"],
[class*="invalid"], [class*="field-error"]
```

Walk those, extract text, parse "X — This field is required" → X is
the missing field name. Re-fill that field, resubmit. Codified in
`read_validation_errors` + `parse_missing_fields`.

## Recipe — full RSVP loop

```python
from basicctrl.browser import helpers
from basicctrl.browser.form_fill import rsvp_form

# 1. Navigate to the form
helpers.goto_url("https://luma.com/<event_slug>")

# 2. Click "Register" / "Request to Join" / "Sign Up" to open form
helpers.js('''[...document.querySelectorAll("button, a")]
  .find(el => /register|request to join|sign up/i.test(el.innerText||""))?.click()''')

# 3. Inspect the form to learn field indices + labels
#    (use the inspect_form snippet from form_fill module docstring)

# 4. Build field_map by matching labels to profile data
field_map = {
    0: {"type": "text",     "value": "Akeil Smith"},
    1: {"type": "text",     "value": "asmithsrs04@gmail.com"},
    2: {"type": "text",     "value": "https://www.linkedin.com/in/akeilsmith"},
    7: {"type": "combobox", "value": "Yes"},   # lu.ma "Join Discord" agreement
}

# 5. Fill + submit + capture validation errors
result = rsvp_form(helpers, field_map, submit_text="register|request|join")

# 6. Self-heal on missing combobox values
if not result["ok"]:
    for missing in result["missing_fields"]:
        # combobox didn't match — find input idx, retry with another label
        ...
```

## Strict-verify rules

After submit, MUST observe at least one of:
- Title flipped away from "RSVP to X" / "Register for X" form-state
- Submit button GONE from the modal
- Confirmation phrase: "Request received", "You're going", "Pending
  approval", "Thanks for registering", "Check your email/phone"
- Page navigated to /confirmation /thanks /success URL

DO NOT trust:
- Body text containing the same words as the form labels (e.g. "going"
  appears in body because of "110 Going" attendee count)
- Modal closing without a confirmation phrase (could be cancel)
- 2xx HTTP without DOM change (some sites use silent failure)

## Per-platform quirks

### Lu.ma

- Sign-in via SMS. Without active session, RSVP form requires phone
  number → SMS code → submit. Code interception is impossible from
  agent — ASK USER to sign in once at lu.ma/signin first.
- Combobox fields styled as text inputs with placeholder "Select an
  option". Values are pre-defined; can't type a custom answer.
- "verify token ownership with your wallet" copy appears as
  fallback for unauthenticated users — usually means SMS sign-in is
  the path, not a literal wallet requirement.
- Past events stay live. Verify date is future before clicking RSVP.
- Custom questions (registration_answers.0..N) vary per event. Fill
  with profile data when label matches; skip with empty for optional
  (no asterisk).

### Partiful

- Even more SMS-heavy than lu.ma. Multi-step modal: SMS verify FIRST,
  THEN host-questions modal AFTER. Skill warns — see top-level
  SKILL.md "MANDATORY: strict-verify every submit-class action".
- "Get on the list" CTA is a substring trap — appears in body even
  after RSVP succeeds.

### Eventbrite

- Lighter validation but heavier captcha. May need user to solve
  captcha manually.

### Typeform / Google Forms

- One field at a time, "Next" between each. Don't try to fill all at
  once — they hide future fields until current is valid.

## Lessons learned (cross-app)

```
LESSON                                       WHY
─────────────────────────────────────        ───────────────────────────
React value-setter must use prototype        Direct .value assignment
descriptor + dispatch input/change           bypasses React's controlled-
events                                       input listener; onChange
                                             never fires; submit treats
                                             field as empty.

Combobox/select fields don't accept          Lu.ma + Typeform + many
typed values — must click input + click      others use [role="combobox"]
option from dropdown                         where typing is filtered to
                                             match-or-clear, not free-form

Always read validation errors AFTER          Otherwise you ship "submitted
submit; if errors, fix specific fields       OK" when actually nothing
named in errors and resubmit                 went through (the exact
                                             false-positive the top-level
                                             skill warns about)

Strict-verify by confirmation PHRASE         Body innerText match on form
not by body substring                        labels = false positive every
                                             time (saw "going" matching
                                             "110 Going" attendee count)
```

## Where this is wired

```
basicctrl/browser/form_fill.py        — the primitives + orchestrator
basicctrl/skills/_generic/web-form-   — this file (cross-app pattern)
  fill.md
basicctrl/skills/<bundle_id>/         — per-platform .md files document
  <topic>.md                            specific quirks (lu.ma SMS,
                                        Partiful host-questions, etc)
```

## Next time I see a web form

1. Open page
2. Click the primary CTA (Register / Sign Up / Submit / RSVP)
3. Inspect modal: get input labels, types, placeholders
4. Build field_map — match labels to profile or task context
5. For each "Select an option" placeholder → mark as combobox
6. Run rsvp_form(helpers, field_map)
7. If validation errors → re-fill named fields → resubmit
8. Strict-verify by confirmation phrase (not substring)
9. If success → register_task_complete with lessons
