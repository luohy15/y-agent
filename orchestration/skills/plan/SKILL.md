---
name: plan
description: Plan - read code, audit, scope, and produce a plan note at pages/plan-{id}.md. Use when a coding task needs research, audit, or sub-task breakdown before implementation.
license: MIT
metadata:
  version: "1.0"
---

# Plan Skill

Leaf skill for the planning phase of dev work. Reads code, scopes the requirements, and
produces a plan note. **Does not open worktrees, change code, or commit.**

Loaded via `y chat --skill plan`, usually dispatched by the dev coordinator, but it can also be
invoked directly for a standalone audit.

## Working mode

Runs in the **project main directory** (no worktree needed, since it is read-only). The caller
passes `--work-dir <project_path>`.

## Workflow

1. `y todo get <todo_id>`: read the todo desc plus linked notes.
2. `y todo activate <todo_id>`: mark in progress (skip if already active).
3. Read code, understand the requirements, identify sub-tasks.
4. **Write the plan to `$Y_AGENT_HOME/pages/plan-<todo_id>-<slug>.md`** (mandatory,
   **absolute path**: `--work-dir` is the project dir, but the plan file must land in the
   top-level `pages/`, not `<work-dir>/pages/`). Include:
   - Requirements recap
   - Design decisions
   - **Assumptions**: everything the plan takes for granted (input shape, library behavior,
     deploy target). If an assumption is load-bearing and unverified, flag it for the caller
     rather than picking silently.
   - Sub-task breakdown. Every sub-task gets a concrete **verify** step: the smallest check
     that proves it is done (a command, a test, an observable behavior). No "make it work"
     success criteria.
     ```markdown
     ## Sub-tasks
     - [ ] Sub-task 1: brief description — verify: <command / test / observation>
     - [ ] Sub-task 2: brief description — verify: <command / test / observation>
     ```
   - **Length budget and keep/drop rule**: target **100 to 200 lines** for the whole note;
     **250 lines is a hard cap**. Within that, keep only (a) a 1 to 3 sentence scope recap,
     (b) binding decisions and load-bearing assumptions, (c) the current sub-task breakdown
     with one concise verify step each, and (d) a concise out-of-scope / follow-up list.
     Requirements recap, decisions, assumptions, and out-of-scope are each normally **10
     bullets or fewer**; each sub-task is normally **one bullet plus its verify line**. If
     genuinely independent workstreams cannot fit under 250 lines, split them into separately
     linked plan notes rather than making one note encyclopedic.
   - **Drop aggressively**: do not restate todo background; do not inventory every file or
     completed deliverable; do not preserve superseded options, audit chronology, status
     diaries, or completed-task narratives; do not paste code, config, or log excerpts; no
     reference-implementation tours; no surveying options after a decision is binding; no
     repeating rationale across sections; no speculative edge cases, defensive caveats,
     operational telemetry, capacity arithmetic, or rollback detail unless it changes an
     implementation task or is required for a hard-to-reverse step. Prefer a pointer to the
     durable source over copied detail. A plan is a forward-looking execution index, not a
     design archive, runbook, or incident record.
   - **On every update, prune before adding**: remove completed and superseded material,
     collapse settled rationale to the binding decision, and keep only current work. The budget
     applies to the resulting whole note, not merely the newly added section. If an existing
     note exceeds 250 lines, condense it as part of the planning task before the callback.
5. **Link the plan to the todo**: `y assoc note pages/plan-<todo_id>-<slug>.md --todo <todo_id>`
   (this CLI takes the path relative to `$Y_AGENT_HOME`).
6. **Trim the todo desc**: keep 1 to 3 sentences of the core requirement; do not dump plan
   content into desc. If the existing desc is bloated, slim it down now.
7. Call back to the caller, then **stop**. No closing summary of the plan in this chat
   (AGENTS.md "Callback rules"): the note is the deliverable and the caller reports it to the
   user.
   ```bash
   y chat --chat-id <from_chat> -m "plan done, plan at $Y_AGENT_HOME/pages/plan-<todo_id>-<slug>.md" \
     ${Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id <todo_id>
   ```
   Unresolved choices and blockers get one clause each in the callback ("2 open questions in
   the note"), not a restatement. Their full text lives in the note.

## Context handoff (running low on context)

Plan is a dispatched leaf, so per AGENTS.md "Context handoff" it **calls back to the caller and
never restarts itself**. Do not spawn a successor plan session. The caller decides whether the
remaining audit needs a fresh plan dispatch or is enough to go to impl.

On a handoff reminder (or an obviously long audit):

1. **Write and link the plan note now, partial**, at the normal path. A plan note covering
   three of five areas plus an explicit `## Not yet audited` section is worth far more to the
   successor than an unwritten complete one.
2. Mark clearly inside the note what is settled and what is still open: which files and areas
   were read, which sub-tasks are fully specified (with verify steps), and what remains to
   scope.
3. `y assoc note pages/plan-<todo_id>-<slug>.md --todo <todo_id>` so the successor finds it via
   `y todo get`.
4. **Call back** saying this is a context handoff, naming the note path and what is left to
   audit.
5. Stop. Do not keep reading code past the handoff point.

## Notes

- **Read-only**: no code changes, no worktrees, no commits.
- **All plan and design notes live under `$Y_AGENT_HOME/pages/`** (absolute path), filename
  `plan-<todo_id>-<slug>.md`. **Never** write to `<work-dir>/pages/`, a worktree's `pages/`, or
  anywhere else. Common pitfall: when `--work-dir` is a project dir, a relative `pages/foo.md`
  silently lands at `<project>/pages/foo.md`. Always use the absolute path.
- **Plan files must be linked to a todo** via `y assoc note <path> --todo <todo_id>`.
- **The todo desc stays concise (1 to 3 sentences)**: plans, design decisions, and sub-task
  checklists belong in the linked plan file, never in desc. A bloated desc makes
  `y todo get/list` unreadable.
- **Do not expand scope**: scope is set by the todo plus caller intent. If you find related
  issues out of scope, note them in the plan under "out of scope / follow-up"; do not pull them
  in.
- **Never `y todo add`**: out-of-scope items and follow-ups stay as text in the plan note and
  the callback. Do not create todos for them, not even obviously needed ones. The user decides
  what gets queued (AGENTS.md "Todo creation is authorized, not self-selected"). You may only
  `y todo update --progress` on the todo you were given.
- **Surface ambiguity instead of guessing**: if the requirement has multiple reasonable
  interpretations, list them in the plan with a recommendation and call out the unresolved
  choice in the callback. Do not pick one silently and proceed.
