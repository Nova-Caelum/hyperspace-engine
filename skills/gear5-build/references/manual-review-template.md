# Manual review guide — template

Written by the Build driver to `<run-dir>/REVIEW.md` whenever a row needs Daniel: an undischarged `manual` criterion, or an `unverifiable` verdict. One file per stop, every such row in it. The chat message carries the file's path and the row count — nothing else. The response word budget binds the chat, never this file.

Rules for every entry: the task's **name, never an id** · every path **full and absolute** · every command **one line, or a script file** — a multi-line command dies on paste · say what he is looking for in plain English, not what an agent would grep.

---

# Review — [run name] · [date] · [N] task(s) need you

## 1. [Task name, as written on the Task Graph]

- **Where it sits:** [project] → [module]
- **What was done:** [two or three sentences — what changed, in plain English]
- **What you are checking:** [the criterion, quoted verbatim] — in practice: [what a pass looks like to a person looking at it]
- **Files to look at:**
  - `$VAULT_ROOT/[full path]` — [what to look for in it]
- **Command to run** (code only; omit for documents):
  `[one line]` → a pass prints: `[the exact line or number to expect]`
- **To close it, say:** "[task name] — confirmed" (your words go into the attestation verbatim)

## 2. [Next task name]

[same seven lines]

---

**When you have been through the list:** say which passed. Anything that did not pass gets one line on what you saw — it is not fixed here.
