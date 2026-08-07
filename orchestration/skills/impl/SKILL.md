---
name: impl
description: Impl - implement code changes inside an existing worktree, also handles dev server. Use when a sub-task is ready to be coded (worktree already created) or when running a dev server.
license: MIT
metadata:
  version: "1.0"
---

# Impl Skill

Leaf skill for the implementation phase of dev work. Codes inside an existing worktree. **Does
not create worktrees** (the caller already created one) and **does not commit or push** (the
dev coordinator runs `y dev commit` after the impl callback).

Loaded via `y chat --skill impl`, usually dispatched by the dev coordinator after a plan, or
directly when the sub-tasks are already known.

## Working mode

Runs inside an **existing worktree**; the caller passes `--work-dir <worktree_path>`.

## Workflow

1. `y todo get <todo_id>`: read the todo desc plus the linked plan note, and locate the
   sub-task you are assigned.
2. `y todo activate <todo_id>`: mark in progress (skip if already active).
3. **Claim the sub-task** (when parallel sub-tasks exist):
   `y todo update <todo_id> --progress "Claim sub-task X: brief description (chat:<to_chat> wt:<worktree_name>)"`.
   Recording the chat id and worktree lets the coordinator match commit and cleanup callbacks.
4. Read code, implement.
5. `y todo update <todo_id> --progress "Finished sub-task X: brief description"`. What changed,
   what was verified, and anything the coordinator must know goes **here**, not in the callback.
6. Call back to the caller, then **stop**. No closing walkthrough of the change in this chat
   (AGENTS.md "Callback rules"): the coordinator reads the progress note and reports to the
   user.
   ```bash
   y chat --chat-id <from_chat> -m "impl done" \
     ${Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id <todo_id>
   ```
   Anything that would block the coordinator (a blocker, an unresolved choice, a follow-up it
   must decide on) gets one clause appended to that line; the details stay in the progress
   note.

## Context handoff (running low on context)

Impl is a dispatched leaf, so per AGENTS.md "Context handoff" it **calls back to the
coordinator and never restarts itself**. Do not spawn a successor impl
(`y chat --skill impl ... --new`) and do not pick up further sub-tasks. The dev coordinator
decides who continues, in which worktree, at which tier.

On a handoff reminder (or an obviously long session):

1. **Stop at a clean boundary**: finish the edit in hand, leave no half-written file or broken
   build, and run the sub-task's verify step if it is within reach. Uncommitted changes stay in
   the worktree; that is normal, the coordinator commits.
2. **Record durable state** (the successor reads this, not your callback):
   ```bash
   y todo update <todo_id> --progress "Handoff (context): sub-task X done=<what works> remaining=<what's left> wt:<worktree_name> chat:<to_chat> files:<paths touched> verify:<run / not run>"
   ```
3. **Call back** with the same summary in one line, saying explicitly that this is a context
   handoff and the remaining work needs a fresh impl session.
4. Stop. Do not start the remaining work "just a bit further".

## Dev server

**Do not auto-start** the dev server. Only start one when the user explicitly asks, or when the
task itself is "run the app". Starting a dev server and driving a browser to inspect the UI is
**not** a default verification step (AGENTS.md: agent-driven UI runtime checks are opt-in).
Default UI verification is static checks only.

When you do run one, keep each worktree's instance isolated so parallel sub-tasks do not
collide: allocate ports from a per-worktree range, track PIDs in a per-worktree file, and clean
up when the check is done.

## Notes

- **No worktree creation here**: the dev coordinator creates the worktree and passes it via
  `--work-dir`.
- **No commit or push here**: the coordinator runs `y dev commit <worktree_name>` on the impl
  callback. Just leave the changes uncommitted in the worktree.
- **No large audits**: if scope is unclear, call back and ask for a plan dispatch first. Do not
  quietly expand scope.
- **Surgical changes**: every changed line should trace to the assigned sub-task. Do not
  refactor adjacent code, reformat unrelated regions, or "improve" comments and naming you
  happened to read. Match the surrounding style even if you would write it differently. If you
  spot unrelated dead code or follow-up issues, mention them in the progress note instead of
  editing them.
- **Never `y todo add`**: follow-ups, nits, and tech debt you find go in the progress note and
  the callback, never into a new todo. The user decides what gets queued (AGENTS.md "Todo
  creation is authorized, not self-selected"). You may only `y todo update --progress` on the
  todo you were given.
- **Clean up only your own orphans**: remove imports, variables, and helpers that *your*
  changes made unused. Do not delete pre-existing dead code.
- **Surface ambiguity, do not guess**: if the plan or todo leaves a real choice undecided
  (multiple reasonable interpretations, a missing API contract, an unclear edge case), call
  back with the options and your recommendation before coding. Silent guesses cause rework.
- **Verify before the callback**: run the verify step from the plan's sub-task (test, command,
  manual check). If there is no verify step, propose one in the progress note. "I think it
  works" is not done.
- **Record durable decisions once**: if implementation reveals a lasting decision the plan does
  not cover, write `pages/decision-<todo_id>-<slug>.md`, associate it to the todo, and report it
  to the coordinator. Do not duplicate requirements or routine implementation details.
- **UI / visual-delta changes: static checks by default; browser inspection and screenshots
  only if the user asks.** For a change with an **observable visual delta**, default
  verification is the AGENTS.md static gate (typecheck or build, lint if present, non-browser
  unit/integration tests). Do **not** auto-start a dev server, drive a browser to inspect the
  UI, or screenshot as routine self-verification. Cheap non-browser runtime checks (curl an
  API, run the test suite) remain fine.
- **Never write automatic DB migration logic**: only generate the SQL. The user applies it.
- **No foreground-blocking commands** (`npm run dev`, `uvicorn ...`, a tunnel): long-running
  processes run in the background with `nohup ... &`. That stays the right form for dev servers
  (unattended, no input, safe to kill and restart). If a process instead needs input mid-run
  (an interactive login) or would run past the Bash tool's cap, use `tmux` per AGENTS.md
  "Long-running / interactive processes". A command that finishes in seconds stays a plain
  foreground call even when it mutates something.
- **Never create `pages/` inside the worktree.** To record a design decision, requirement, or
  follow-up note, write it to `$Y_AGENT_HOME/pages/<name>.md` (absolute path) and
  `y assoc note pages/<name>.md --todo <todo_id>`. **Never** write to `<worktree>/pages/`;
  `pages/` exists only at `$Y_AGENT_HOME`.
