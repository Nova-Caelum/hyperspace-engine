---
name: acing-hyperspace
description: Use at the start of every session — cold, resumed, cleared, or compacted — before the first response or action of any kind, including a clarifying question. Establishes that skills are how work is done here, that invoking one is mandatory before answering, and which loop node the work in front of you enters.
derives_from: using-superpowers
license: MIT
author: Nova Caelum
version: 1.0
---

<SUBAGENT-STOP>
If you were dispatched as a subagent with a brief, the brief governs. Ignore this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If the odds that a skill applies to what you are about to do are one in a hundred, invoke it. This is not negotiable, and no reason you give yourself makes it so.

The pair that makes this survivable: invoking is cheap and reversible. If the skill turns out to be wrong for the situation, you do not have to follow it. The demand is absolute so the check always happens; the escape exists so a miss costs nothing.
</EXTREMELY-IMPORTANT>

## The Rule

Invoke the relevant or requested skill BEFORE any response or action — a clarifying question, a file read, a search, a plan. Then say what fired — "Using <skill> to <purpose>" — and follow it as written. If it carries a checklist, one todo per item.

## Skill Priority

Process before implementation. When the work has a shape the loop recognizes, the loop node fires FIRST and sets the approach; domain skills execute inside it. The node is the only way in — the demi documents behind it are not doors.

<!-- ROUTING BLOCK — the only node-coupled section. A stage change REPLACES this block; touch nothing else. -->

| The work in front of you | Enter |
|---|---|
| A goal nobody has framed — a feature, subsystem, tool, a "should we"; Daniel says "let's figure out what we're building", "spec this out", "is this worth doing"; no `loop.state.json` for it, or one reading `current_node: framing` | `gear2-understand` |
| Tests frozen, design open — "what are our options", "sketch the architecture", "cut this to v1"; the run reads `current_node: understanding`, gate passed | `gear3-decide` |
| Decision frozen, nothing filed — "write the PRD", "write the plan", "file the rows"; the run reads `current_node: deciding`, gate passed | `gear4-draft` |
| Rows filed, software owed — "build it", "execute the plan", "run the rows"; the run reads `current_node: specifying`, gate passed, or a `BUILD_LEDGER.md` has rows not yet `complete` | `gear5-build` |
| Build finished, Daniel's test owed — the run reads `status: live`, or the Build gate just exited 0 | `gear6-live` |

Between two nodes, enter the earlier one: hidden complexity upgrades forward; nothing downgrades mid-task. Route by the work's own run, never another run's banner line; there, `status: live` outranks every row above it: a finished run never re-enters Build. Ceremony scales with the task; the gate never does. A failure whose cause is known is debugging, not a node; a value inside a filed row belongs to Build, not to a new run.

<!-- END ROUTING BLOCK -->

## Red Flags

These thoughts mean STOP — you are rationalizing:

| Thought | Reality |
|---|---|
| "This is still conversation, not a task." | Questions and clarifications are tasks. The check comes before the reply. |
| "One small dial — a skill is overkill here." | Five loaded skills slept through five dials. "Overkill" is the tell. |
| "One more attempt first; I'll invoke it if this fails." | The retry is where the skill was needed. Invoke before the attempt. |
| "I'd have noticed if a trigger applied." | A row in a table is not a firing. The work's shape decides, not your noticing. |
| "I'll just draft it first." | Gates keyed on your own intent die. The moment is now, before the first action. |
| "I remember what that skill says." | The one-row summary is what fired last time, not the body. Read the one on disk. |
| "The table told me what to do; I did it." | The table names doors, never steps. Enter the node; the node has the steps. |

## Daniel's Instructions

Daniel's instructions — the standing rules, CLAUDE.md, what he says in the session — override skills; skills override default behavior. Skip a skill's workflow only when he says so explicitly.
