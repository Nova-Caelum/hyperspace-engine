---
name: hyperspace-setup
description: Use when a new project needs Hyperspace Engine turned on — the user says "set up hyperspace", "install hyperspace", "get started", "onboard me", or the `hyperspace` MCP failed to connect. One-time provisioning: isolated environment, database, judge, door, browser, launcher.
derives_from: technical-cofounder-setup
license: MIT
author: Nova Caelum
version: 1.1
---

# Hyperspace Setup

The only conversational surface for turning a project on. Runs once per
project; every later session just uses what this leaves behind. Works the
same on macOS, Linux and Windows.

Ask one question at a time. Wait for each answer before asking the next.
Never edit `~/.claude/settings.json`. Never ask for a key's value in this
chat — if a key is needed, tell the user the environment variable name and
let them set it themselves.

Run every command below from the project root. Each one is written to work
unchanged in bash, zsh, Git Bash and PowerShell (5.1 and 7).

## 1. Find a Python

The isolated environment does not exist yet, so this step uses whatever
Python the machine has. Hyperspace requires >= 3.11. Try, in order, and use
the first that prints 3.11 or newer — call it `<python>` below:

1. `python3 --version` (macOS, Linux)
2. `py -3 --version` (Windows: the launcher python.org's installer adds)
3. `python --version`
4. `uv --version` — if `uv` exists but none of the above is >= 3.11,
   `<python>` is `uv run --no-project --python ">=3.11"` (uv fetches a
   managed Python the first time).

On Windows, a `python` or `python3` that prints "Python was not found" and
offers the Microsoft Store is a placeholder, not a Python — treat it as
absent. If nothing qualifies, tell the user what was found and the
requirement (Python 3.11+ from python.org, or `uv`), and stop.

**Windows also needs Git for Windows.** Claude Code runs this plugin's
SessionStart hook through Git Bash; without it the hook cannot run. If
`git --version` fails, say so and point the user to git-scm.com before going
on.

## 2. Provision the isolated environment

```
<python> "${CLAUDE_PLUGIN_ROOT}/bin/hyperspace_setup.py" --dir "<project-dir>" --provision
```

(`${CLAUDE_PLUGIN_ROOT}` resolves in skill content and points at the
plugin's own tree. The `hyperspace` command itself lives INSIDE the
environment this creates, so the first call can never be `hyperspace`; this
bootstrap script imports only the standard library, by design, for this one
moment.) Add `--judge <name>` if step 3 already has an answer; otherwise the
call probes for you and reports what it found.

This single call:

- (a) creates `.hyperspace/env` with `uv` if `uv` is on PATH, `python -m venv`
  + `pip` otherwise — report which one ran;
- (b) installs the plugin's own dependency tree into that env — never the
  system Python (register A9: Claude Code does not install a plugin's
  Python dependencies for you);
- (c) on Windows, links `.hyperspace/env/bin` to the environment's
  `Scripts` folder, so `.hyperspace/env/bin/...` works on every OS;
- (d) initialises `.hyperspace/graph.db`;
- (e) writes `.hyperspace/config.toml` and the launcher (step 5 below).

From here on every command runs from the environment, always spelled
`.hyperspace/env/bin/<name>` — on Windows that resolves to `<name>.exe`.

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
.hyperspace/env/bin/hyperspace serve --open
```

This binds the loopback door (127.0.0.1 only), opens the user's browser at
the printed URL, and blocks in the foreground — run it the way you'd run
any other long-lived dev server, and tell the user the URL even though the
browser should already be there.

## 5. Say where the launcher is

Provisioning in step 2 already wrote the double-clickable launcher:
`.hyperspace/Open Hyperspace.command` on macOS, `.hyperspace/Open Hyperspace.bat`
on Windows, `.hyperspace/open-hyperspace.sh` on Linux. Tell the user exactly
where it is and that double-clicking it (or running it, on Linux) reopens
the console without needing this chat.

## 6. Tell the user to restart the session

The `hyperspace` MCP server (`.mcp.json`'s `hyperspace` entry) runs
`.hyperspace/env/bin/python -m hyperspace.mcp` — an interpreter that did not
exist when this Claude Code session started. Tell the user to restart the
session (or run `/reload-plugins` / `claude mcp list` to check) so the MCP
connects against the environment this skill just created.

## If the MCP shows "failed to connect"

Run `.hyperspace/env/bin/hyperspace doctor` — it re-runs this skill's check
phase (python, env, store, config/judge, door port free-or-ours) and prints
one `OK`/`FAIL` line per check. Whatever it names as `FAIL` is exactly what
step to re-run from this skill. If `.hyperspace/env` does not exist at all,
doctor cannot run either: start again from step 1.

Source: Nova Caelum (MIT). Modeled on technical-cofounder's `setup` and
`super-setup` skills (one question at a time; never edit
`~/.claude/settings.json`; offer commands the user runs) — see PRD `Decisions
inherited` for the source citations.
