# Run-folder schema — where each file goes

**Author:** cto · 2026-09-20 · **Daniel reviewed:** no
**Why this exists:** Daniel, 2026-09-20 — by the Build node the run folder "was such a hot mess. I literally couldn't find anything." One run reached 54 loose files at its root.
**Single source:** the folder list lives in `_agentOS/system/bin/drive_map.py` (`ROOT_FILES`, `FOLDERS`) and is printed at the top of every `DRIVE_MAP.md`. This page covers only the calls the list cannot make for you.

## The layout

Open the run's `DRIVE_MAP.md` — its **Where things go** table is the layout, printed from the script, so it cannot drift from what the engine enforces. The run root holds only what the engine itself puts there; nothing else, ever. `handoffs/`, `notes/` and `misc/` exist from `init`; each node folder is created by its own gear.

## The calls

- **Written for another agent or another session to act on → `handoffs/`.** Written to understand something → `notes/`. If you cannot say which, it is a note.
- **A node's own working drafts live in that node's folder**, beside the artifact they fed — not in `notes/`.
- **Name a file for what it holds and when:** `<What>_<Agent>_<YYYY-MM-DD>.md`. A second version is a new date, not `_v2_final`.
- **Subfolders are free inside any folder** once it passes about ten files. New top-level folders are not — the map will list one under **Outside the schema**.
- **`misc/` is a real answer.** A file in `misc/` is findable; a file loose at the root is what this page exists to stop.
- **Never move a frozen artifact.** Once a gate has passed, the files it froze are tracked by path and hash in `loop.state.json`; moving one reads as a double-back. File things before the gate, not after.

## The drive map

`DRIVE_MAP.md` is generated from the disk — never type a path into it. `loop_state.py` rewrites it at `init`, at every `set-node` and at every passing `gate-pass`, so it matches the folder at both ends of every node. Mid-node, after a burst of new files: `python3 $AGENTOS_ROOT/system/bin/drive_map.py write <run-dir>`. To ask whether it is current: `drive_map.py check <run-dir>` (exit 0 = matches exactly).

The words after the dash on a line under **Full map** are yours. Write them once — what the file is, in a few words — and every regeneration keeps them. The engine's own files come pre-described.

Anything outside this schema is listed in the map under **Outside the schema** and printed at the gate. It is reported, not refused.
