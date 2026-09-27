---
name: hyperspace-setup
description: Use when a new project needs Hyperspace Engine turned on — the user says "set up hyperspace", "install hyperspace", "get started", "onboard me", or the `hyperspace` MCP failed to connect. One-time provisioning: isolated environment, database, judge, door, browser, launcher.
derives_from: technical-cofounder-setup
license: MIT
author: Nova Caelum
version: 1.0
---

# Hyperspace Setup

The only conversational surface for turning a project on. Runs once per
project; every later session just uses what this leaves behind.

Ask one question at a time. Wait for each answer before asking the next.
Never edit `~/.claude/settings.json`. Never ask for a key's value in this
chat — if a key is needed, tell the user the environment variable name and
let them set it themselves.

## 1. Check Python

Run `python3 --version` (this is BEFORE the isolated environment exists —
the plugin's own bundled interpreter isn't provisioned yet, so this has to
be whatever `python3` the user's shell finds). Hyperspace requires >= 3.11.
If it refuses, tell the user their version and the requirement, and stop —
nothing past this point can run on an older interpreter.

## 2. Provision the isolated environment

Run, from whatever `python3` just passed step 1 (the `hyperspace` console
script does not exist yet — it lives INSIDE the environment this command
creates, so the first call can never be `hyperspace` itself, and it cannot
be `python3 -m hyperspace.cli` either: that module imports this project's
PyPI dependencies at import time, which are not installed anywhere until
this exact command finishes — found and verified empirically, not assumed.
`hyperspace.setup` is the one part of this plugin with no such dependency,
by design, for this one moment):

```
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m hyperspace.setup --dir "<project-dir>" --provision
```

(`${CLAUDE_PLUGIN_ROOT}` resolves in skill content, same as every other
plugin script call, and points at the plugin's own source tree — the same
`import hyperspace` this uses.) Add `--judge <name>` if step 3 already has an
answer; otherwise this call probes for you and reports what it found. From
here on every command in this skill runs `.hyperspace/env/bin/hyperspace
...` — the freshly provisioned copy, never the bare `python3` used above.

This single call does steps (a)-(d) below without any further prompting
from you if you already know the judge (skip to step 3's question first if
you don't):

- (a) creates `.hyperspace/env` with `uv` if `uv` is on PATH, `python -m venv`
  + `pip` otherwise — report which one ran;
- (b) installs the plugin's own dependency tree into that env — never the
  system Python (register A9: Claude Code does not install a plugin's
  Python dependencies for you);
- (c) initialises `.hyperspace/graph.db`;
- (d) writes `.hyperspace/config.toml` and the launcher (step 6 below).

## 3. Ask which judge to use

Before running the provisioning call (or right after, if you ran it with no
`--judge` and it probed for you — either order is fine, but do this
conversationally rather than silently), tell the user what was detected and
recommend the path of least resistance:

- An `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` already in the environment
  → recommend that one; nothing else to do.
- `claude` on PATH and a live `claude -p ping` → recommend `claude-code` (uses
  their Claude Code subscription, no key).
- `codex` on PATH → recommend `codex`.
- None of the above → `none` is always available and always works — the
  path of least resistance. Deterministic acceptance criteria (`file_state`,
  `command_check`) still verify with `none`; only LLM judging (criteria-
  quality and evidence review) is off until a runner exists.

Whatever the user picks, the skill probes it (or, for `none`, doesn't need
to) and says the result out loud — the verifier never silently switches
judge. If a working `claude -p` probe fails, say why in one line and offer
the fix:

```
npm install -g @anthropic-ai/claude-code
```

along with the note that it may just need a fresh `claude login` — then
fall back to `none` for now; nothing else breaks.

## 4. Start the door and open the browser

```
"<project-dir>/.hyperspace/env/bin/hyperspace" serve --open --dir "<project-dir>"
```

This binds the loopback door (127.0.0.1 only), opens the user's browser at
the printed URL, and blocks in the foreground — run it the way you'd run
any other long-lived dev server, and tell the user the URL even though the
browser should already be there.

## 5. Write the launcher and say where it is

Provisioning in step 2 already wrote the double-clickable launcher:
`.hyperspace/Open Hyperspace.command` on macOS, `.hyperspace/Open Hyperspace.bat`
on Windows, `.hyperspace/open-hyperspace.sh` on Linux. Tell the user exactly
where it is and that double-clicking it (or running it, on Linux) reopens
the console without needing this chat — it execs
`.hyperspace/env/bin/hyperspace serve --open` directly.

## 6. Tell the user to restart the session

The `hyperspace` MCP server (`.mcp.json`'s `hyperspace` entry) execs
`.hyperspace/env/bin/python -m hyperspace.mcp` — an interpreter that did not
exist when this Claude Code session started. Tell the user to restart the
session (or run `/reload-plugins` / `claude mcp list` to check) so the MCP
connects against the environment this skill just created.

## If the MCP shows "failed to connect"

Run `hyperspace doctor` from the isolated environment
(`.hyperspace/env/bin/hyperspace doctor --dir "<project-dir>"`) — it re-runs
this skill's check phase (python, env, store, config/judge, door port
free-or-ours) and prints one `OK`/`FAIL` line per check. Whatever it names
as `FAIL` is exactly what step to re-run from this skill.

Source: Nova Caelum (MIT). Modeled on technical-cofounder's `setup` and
`super-setup` skills (one question at a time; never edit
`~/.claude/settings.json`; offer commands the user runs) — see PRD `Decisions
inherited` for the source citations.
