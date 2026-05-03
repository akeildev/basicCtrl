# Install bootstrap (`scripts/install.sh`)

> Lessons from building the one-command zero-touch installer. Read
> before touching install/upgrade flows or other shell-based bootstrap.
> The install spec lives in `scripts/install/PROMPT.md`.

## Lessons learned (auto-recorded)

### structlog INFO lines pollute stdout when capturing with `2>&1` — 2026-05-03

What was surprising. Smoke-testing the 5 framework MCP tools by importing
each `register_*` and capturing the python output with `2>&1` and then
`[[ "$out" == "OK" ]]` always failed — even though the test ran cleanly.

Why. `structlog.get_logger().info("tool.registered", ...)` fires inside
each `register_*` function and writes NDJSON to stderr (configured in
`basicctrl/log.py`). Merging stderr into stdout means the captured
string is `{"...":"...registered"...}\n... × 5\nOK`, never `"OK"`.

How to apply. When capturing python output to compare for an exact
sentinel, redirect stderr to a tempfile separately:

```bash
err="$(mktemp)"
out="$(uv run python … 2>"$err" <<'PY'
…
print("OK")
PY
)"
if [[ "$out" == "OK" ]]; then ok; else cat "$err"; fail; fi
rm -f "$err"
```

The win: stderr is preserved for debugging on failure but doesn't
break the success path. Only show stderr if the test fails.

### Idempotent JSON merge — back up on mutation, never on no-op — 2026-05-03

What was surprising. The obvious shape (`cp $f $f.bak; merge; write`)
clobbers the previous .bak on every run, hiding what changed last time
and bumping mtimes even on no-op runs.

Why. A `.bak` is most useful as "last known good before *this*
installer made a change," not "snapshot from the most recent run."
Re-running on an already-configured machine should be observably a
no-op — same mtime, same sha256.

How to apply. Move the `cp` inside the python merge block, after the
"already-correct" early-return:

```python
existing = proj["mcpServers"].get("basicCtrl")
if existing == desired:
    print("ALREADY")
    sys.exit(0)
shutil.copy2(path, path + ".bak")  # only NOW, because we will mutate
proj["mcpServers"]["basicCtrl"] = desired
…
```

Verifying idempotence: re-run the installer and `sha256sum` both
config files. Hash should match the prior run.

### Dedup hook entries by an embedded `_basicCtrl` tag, not by command path — 2026-05-03

What was surprising. The Stop hook entry's `command:` field changes
when the repo path changes (e.g. user clones to `~/dev/basicCtrl`
instead of `~/Developer/basicCtrl`). Deduping by command-path alone
means a user who moves the repo gets a duplicate entry every install.

Why. Settings.json hook entries are arrays; Claude Code re-runs every
matching entry. Two `learn_reminder.py` entries means the reminder
fires twice per Stop event — and one points at a stale path that errors.

How to apply. Embed an arbitrary `_basicCtrl: learn-reminder` key
inside the hook entry — Claude Code ignores unknown keys but our
installer can use it as a stable lookup tag, then *update the
command path in place* if the repo moved:

```python
for entry in stop_list:
    for h in entry.get("hooks", []):
        if h.get("_basicCtrl") == "learn-reminder":
            if h.get("command") != hook:
                # repo moved — patch the path, keep one entry
                h["command"] = hook
            return  # found, no append
stop_list.append(desired_outer)  # genuinely new
```

This pattern generalizes: any time you write into a host-owned config
where you'll need to find your own entry later, embed an
`_<your-tool>: <slot-name>` sentinel.

### `curl --max-time 1 --silent --fail` for the Chrome remote-debug probe — 2026-05-03

What was surprising. `curl -s http://127.0.0.1:9222/json/version`
returns exit 0 even when something else (e.g. a stale loopback
listener or a lan service) responds with HTML / 404. Without the
right flags, the probe lies — installer thinks Chrome is wired when
it isn't.

Why. By default curl only fails on transport errors. HTTP errors
(4xx/5xx) and arbitrary response bodies are "successful from curl's
perspective." `--fail` flips that — non-2xx becomes exit 22.
`--max-time 1` keeps the probe under a second so the installer
doesn't hang on a black-hole port.

How to apply.

```bash
curl --max-time 1 --silent --fail "http://127.0.0.1:9222/json/version" \
  >/dev/null 2>&1 \
  && echo "Chrome wired" \
  || echo "needs setup"
```

Pair with a `[[ -d "/Applications/Google Chrome.app" ]]` check before
prompting the user to walk through `chrome://inspect` — pointless to
prompt if Chrome isn't installed.

### Non-interactive prompts: detect with `[[ -t 0 ]]`, take the documented default silently — 2026-05-03

What was surprising. Running `bash install.sh < /dev/null` (or piped
from CI) hangs at the first `read -r` because stdin is closed but the
script still tries to read.

Why. `read -r` on a closed stdin returns immediately with an empty
value, but if there's no surrounding `if` / default fallback, the
script continues with that empty answer (which then fails the y/Y
regex and the user effectively chose "no" with no signal).

How to apply. Wrap each interactive prompt in a tty check + fall
back to the documented default. Make the default "no" for any
optional install (don't surprise CI with brew installs):

```bash
prompt_yn() {
  local def="$2"
  if [[ ! -t 0 ]]; then
    [[ "$def" == "y" ]] && return 0 || return 1
  fi
  …interactive read…
}
```

The `[[ -t 0 ]]` test is the canonical "is stdin a tty" check on
both bash and zsh.
