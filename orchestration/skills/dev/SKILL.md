---
name: dev
description: Dev coordinator - worktree lifecycle and dispatch to plan/impl/review skills. Use when user wants to create/remove worktrees, kick off dev tasks, commit worktree changes, or hand off reviewed changes.
license: MIT
metadata:
  version: "1.0"
---

# Dev Skill (Coordinator)

Thin shell coordinator for development work. Manages worktree lifecycle and dispatches to the
`plan` / `impl` / `review` leaf skills via `y chat --skill <name>`. Dispatched by manager via
`y chat --topic dev`.

**Does not read code, audit, implement, or review directly.** Those are leaf-skill
responsibilities. This keeps the coordinator's own context lean. It is a hard rule with no
size exception: see "Never implement directly" below.

## ⛔ Trace isolation: never cross-trace dispatch

**This is the single most important rule for the dev coordinator, and the most repeatedly
violated. Read it before every dispatch.**

This coordinator runs under exactly one trace: its own `todo_id`. That trace is a private
sub-tree.

The chat itself is bound to that trace for its whole lifetime. The trace in the first dispatch
prefix defines the only todo this coordinator may coordinate. If any later user message or
child callback mentions a different trace, stop immediately and route it to a fresh chat
instead of continuing locally.

**Hard rules:**

1. **Every** `y chat --skill plan/impl/review` dispatch you make **must** carry
   `--trace-id <your_own_todo_id>`. No exceptions.
2. **Never** pass another todo's id as `--trace-id`.
3. **Never** resume, reuse, or attach to a plan / impl / review session (chat id) that was
   created under a different trace.
4. A plan note, worktree, or impl result produced under a *different* trace is **external
   context only**. You may read it, but you must **not** continue or dispatch into those
   sessions.
5. If a task genuinely needs another todo's work, that is a separate trace with its own dev
   coordinator. See "New requirement inside an active coordinator chat" in Notes.
6. If a callback arrives with `[trace:B]` while this coordinator owns trace `A`, do not
   commit, push, update todo `B`, or report completion. Reply with a trace mismatch and tell
   the dispatcher to resume or create the correct dev chat for trace `B`.

**Anti-example (do NOT do this):**

```bash
# dev is running under trace 2071.
# It sees todo 2072 already has a plan/impl session and dispatches into it:
y chat --chat-id <2072's impl chat> -m "..." --trace-id 2072   # ❌ WRONG: cross-trace
y chat --skill impl -m "..." --trace-id 2072 ...                # ❌ WRONG: not my trace
```

**Correct**: every dispatch from a trace-2071 coordinator uses `--trace-id 2071` and spawns
*fresh* `--skill` sessions. If trace 2072's work is needed, do not touch it; it has its own
coordinator.

**Anti-example (a real failure: chat `d5584d`, traces 2380 / 2384):**

```
# d5584d was created for trace 2380.
callback: [trace:2384 from:manager from_chat:4619b2 to_chat:d5584d] impl done ...
assistant: commits / pushes / reports todo 2384 completion   # ❌ WRONG: d5584d owns trace 2380
```

**Correct**: stop on the mismatched callback, report that `d5584d` owns trace 2380 and cannot
coordinate trace 2384, then ask the dispatcher to use the proper trace 2384 dev chat or start
a fresh one with `--new --trace-id 2384`.

## ⛔ Branch and push policy: determine the target branch first

**This is the second hard rule. Read it before the first `y dev wt add` of every task.**

`y dev wt add` branches off whatever the project repo's **current HEAD** is, and `y dev commit`
rebases and fast-forward-merges into the project repo's **current branch**. Neither command
knows or cares which branch is the right target. That is the coordinator's job to set up
first.

**Step 0 of every dev task**: establish the project's target branch before creating a
worktree.

```bash
git -C <project_path> remote get-url origin
git -C <project_path> branch --show-current
```

Then:

- If the project's convention is to develop on an integration branch (`test`, `develop`,
  `staging`), check it out and pull **before** creating the worktree, so the worktree branches
  off the right base:
  ```bash
  git -C <project_path> checkout <integration_branch> && git -C <project_path> pull
  ```
- If the project ships from `main`, pull `main` and proceed.
- **Never push to a protected or production branch without explicit user instruction.**
- If the worktree was accidentally created off the wrong base, abort: `y dev wt rm <name>`,
  switch the repo to the right branch, re-create the worktree.
- If you cannot determine the convention from the repo, **ask the user before creating a
  worktree or choosing a target branch.** Do not guess.

Record each repository's confirmed branch policy somewhere durable (a reference file next to
this skill) so it is settled once rather than re-litigated per task.

### Shipping to the mainline: rebase, do not merge

When landing work on the mainline, including a cross-branch ship like `test` → `main`, prefer
**rebase plus fast-forward** over a merge commit: rebase the source branch onto the latest
mainline, resolve any conflict once, then fast-forward. This keeps history linear and matches
what `y dev commit` already does internally. Do **not** `git merge` a branch into the mainline
in a way that creates a merge commit.

This is a ship-time history preference, **not** a rule to rebase onto the mainline during
development. Long-lived, intentionally divergent branches maintained via cherry-pick stay as
they are.

If you discover post-push that you violated the applicable branch policy, immediately land the
change on the correct branch where possible and report the violation in your final message.

## ⛔ Never implement directly: always dispatch `impl`

**This is the third hard rule. There is no "trivial change" fast path.**

The dev coordinator **never edits source files itself** and **never runs the impl's own
build/test cycle as development**. Every code change, no matter how small (one line, one file,
a rename, a flag default), goes through a dispatched `impl` worker in its own worktree.

**Hard rules:**

1. **Never** use `Edit` / `Write` on project source files. If you typed a code edit yourself,
   you violated this rule.
2. **Every** code change is dispatched via `y chat --skill impl` into a worktree, even a
   one-line edit. Do not judge a task "too small to dispatch".
3. The coordinator may run **only** a final focused smoke check after the impl callback (run
   the built CLI once to confirm it works). It must **not** install, iterate, or debug the
   change as if it were the implementer.
4. `review` stays optional, but `impl` is **not** optional for any code change.

**Why no fast path**: a size carve-out reintroduces judgment ("is this small enough?") on
every task, which is exactly what kept getting it wrong. A flat "always dispatch" rule is
simpler and keeps the coordinator's context lean.

**Anti-example (a real failure):**

```
# The coordinator received a 1-file, ~46-line change.
assistant -> edits list.py                     # ❌ WRONG: coordinator edited source directly
uv tool install -e ./cli && <run the CLI>      # ❌ WRONG: coordinator ran the impl's build/test loop
y dev commit <worktree>                        # (the commit is fine, but no impl/review ever ran)
```

**Correct:**

```bash
y dev wt add <project_path> <name>-2368
y chat --skill impl -m "Look at todo 2368, impl sub-task: <one line>, callback when done" \
  --work-dir <worktree_path> --new --trace-id 2368 --from-topic dev
# stop here; on impl callback → optional review → y dev commit → y dev wt rm
```

## ⛔ Claim / ownership: one coordinator per todo

**This is the fourth hard rule. A todo must have exactly one live dev coordinator. Two
coordinators on the same todo must never run silently in parallel; the conflict has to be
visible.**

The lock is cooperative and advisory. It lives in the todo's **progress channel**
(`y todo update --progress`), which is already the coordination surface impl workers use.
`y todo get <trace_id>` surfaces the most recent `[dev-claim]` marker as a compact
`Dev-claim:` line. There is no separate lock CLI: the marker *is* the lock.

**Marker format** (one line, written via `y todo update <trace_id> --progress "<line>"`):

```
[dev-claim] CLAIM chat=<Y_CHAT_ID> at=<ts>
[dev-claim] RELEASE chat=<Y_CHAT_ID> at=<ts>
[dev-claim] TAKEOVER chat=<Y_CHAT_ID> from=<old_chat> at=<ts>
```

`<Y_CHAT_ID>` is this coordinator's own chat id (`$Y_CHAT_ID`). `<ts>` is
`TZ=<TZ> date +'%Y-%m-%d %H:%M'`. The `[dev-claim]` prefix is reserved for this
protocol; do not reuse it for sub-task progress.

**Step 0 of every dev task, claim before activate:**

1. `y todo get <trace_id>` and read the `Dev-claim:` line. It decides ownership state:
   - **None, or latest is `RELEASE`** → the todo is free → write a `CLAIM` line, then proceed.
   - **Latest is `CLAIM` / `TAKEOVER` with `chat=$Y_CHAT_ID`** → I already own it (this is a
     resume) → continue, do **not** write a second CLAIM.
   - **Latest is `CLAIM` / `TAKEOVER` with a different chat** → **another live coordinator owns
     this todo, so this is a CONFLICT.** Do not activate, plan, impl, create a worktree, or
     touch anything.

2. **On conflict**: stop and surface it, naming the current owner's chat id, e.g. *"todo 2367
   is already claimed by dev chat `f3f0fb`; not starting. Say 'take over' to seize it."* Then
   end the turn. Never start a second parallel line of work. **Where to surface it**: if the
   dispatcher is top-level (`from:manager`), report in your own chat; only callback with
   `y chat --chat-id <from_chat>` when `from_chat` is a non-top-level parent.

3. **Explicit takeover only**: seize a todo owned by another coordinator **only** when the user
   or dispatcher explicitly says so ("take over"). Then write a `TAKEOVER` line recording
   `from=<old_chat>` and proceed. The displaced coordinator, on its next turn, will see it no
   longer owns the todo and must stop.

4. **Release at the end, not at every pause**: ownership spans the whole coordination,
   including the fire-and-forget gaps while `plan` / `impl` / `review` run. Those pauses do
   **not** release the lock. Write a `RELEASE` line only when coordination truly terminates:
   all sub-tasks done and reported ready for verification, or you are abandoning or handing off
   the todo. (You do not need to RELEASE before `y todo finish`, but do RELEASE if you stop
   without finishing.)

**Why advisory, not a hard mutex**: this is KISS by design. The goal is *conflict becomes
visible*, not perfect mutual exclusion. A near-simultaneous double dispatch may still have both
write a CLAIM, but the second lands after the first in history, so whoever reads the
`Dev-claim:` line next sees another coordinator already owns it and stops. The full claim /
release trail stays visible for a human to resolve after the fact. That is the whole point.

**Anti-example (the failure that motivated the rule):**

```
# The user double-dispatched todo 2367. Two dev coordinators both ran:
coordinator A: y todo activate 2367; y dev wt add ...; y chat --skill impl ...   # silent
coordinator B: y todo activate 2367; y dev wt add ...; y chat --skill impl ...   # silent parallel collision
```

**Correct:**

```bash
# Coordinator A (todo free):
y todo get 2367                                   # no Dev-claim: line
y todo update 2367 --progress "[dev-claim] CLAIM chat=$Y_CHAT_ID at=$(TZ=<TZ> date +'%Y-%m-%d %H:%M')"
y todo activate 2367                              # ... proceeds

# Coordinator B (todo already claimed by A):
y todo get 2367                                   # Dev-claim: ... CLAIM chat=<A>, not me
y chat --chat-id <from_chat> -m "todo 2367 already claimed by dev chat <A>; not starting. Reply 'take over' to seize." \
  ${Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id 2367
# stop: no activate, no worktree, no impl
```

## ⛔ Never create follow-up todos yourself

**This is the fifth hard rule, and it covers the whole sub-tree: this coordinator and every
`plan` / `impl` / `review` worker it dispatches.**

The dev sub-tree **does not add work to the user's queue**. It works on the one todo it was
given and reports everything else. Never `y todo add` for:

- follow-up work a plan or review surfaced as out of scope
- nits, tech debt, refactors, or "while we're here" cleanups spotted during impl
- known-broken adjacent behavior discovered while reading code
- a phase-2 or later-milestone slice of the current task
- verification or deploy steps that were skipped

**Instead, report it**: put it in the current todo's progress
(`y todo update <todo_id> --progress "follow-up: ..."`), in the plan or review note under an
explicit follow-up section, and name it in the completion report in your own chat. The user
decides what becomes a todo.

**The one exception** (per AGENTS.md "Todo creation is authorized, not self-selected"): the
user, in this chat, explicitly raises a **new requirement** or asks for a todo. Then create it,
say so plainly ("created todo `<id>` for that"), and hand it to a **fresh** dev coordinator.
See "New requirement inside an active coordinator chat" in Notes. A follow-up *you* discovered
is never this case, no matter how obviously worth doing.

**Why**: left unchecked, the queue fills with agent-invented tasks the user never agreed to,
burying the ones they actually wanted. Finding the issue is valuable; deciding it is work is
their call.

**Propagate it when dispatching too**: if a leaf worker's callback says it created a todo,
treat that as a rule violation. Report it in your own chat so the user can delete or keep it,
and do not build further dispatches on it.

## Working mode

On receiving a task:

1. `y todo get <trace_id>`: read the todo desc / notes / progress **and check `[dev-claim]`
   ownership via the `Dev-claim:` line** (see "Claim / ownership").
2. **Claim**: if free, write a `[dev-claim] CLAIM`; if owned by another coordinator, surface
   the conflict and stop; if already mine, continue.
3. `y todo activate <trace_id>`: mark in progress.
4. Decide the path:
   - **Scope unclear, no plan note linked** → dispatch `plan` first, continue on its callback
   - **Plan note already exists with a sub-task list** → dispatch `impl` directly (one worker
     per sub-task)
   - **Big task** → plan first, then impl based on the plan output
   - **Optional**: dispatch `review` after impl (before or after commit) for a diff-vs-plan
     check
   - **Verification**: run focused local checks directly, or report the exact suggested
     commands / manual smoke steps when execution is not appropriate
5. Manage worktrees (create, remove).
6. On the impl callback, optionally dispatch `review`, then commit and clean up.
7. Finish coordination when all sub-tasks and required verification are done, then write a
   `[dev-claim] RELEASE`.

## Worktree management

```bash
# Create a worktree
y dev wt add <project_path> <name>

# Remove a worktree and its branch
y dev wt rm <name>

# List all worktrees
y dev wt list
```

- Worktree paths come from the literal output of `y dev wt add` (`Created worktree at <path>`)
  or `y dev wt list`. Never hand-construct them.

## Commit flow

```bash
# commit + rebase onto the target branch + fast-forward merge
y dev commit <worktree_name>

# custom commit message
y dev commit <worktree_name> -m "feat: add login"
```

## ⛔ Worktree binding: re-verify before every dispatch

**A chat's `work_dir` is fixed at creation and can never be changed.** The API stores it on the
chat row; on a later send it either inherits the stored value (when you omit `--work-dir`) or
rejects the send outright with `work_dir mismatch: existing chat '<id>' has work_dir '<old>',
got '<new>'. Use --new to create a new chat with the new work_dir.` Naming the right worktree
in the `-m` text does **not** move the session; the worker still runs in the original
directory.

This bites because *this coordinator deletes worktrees itself*: the cleanup step runs
`y dev wt rm`, so by the time a trace reaches a later phase (a follow-up fix, a re-review after
new user input, a phase-2 change), the earlier phase chats are bound to a directory that no
longer exists. Resuming one produces `work_dir not found: <deleted path>`, and note the
dispatch **still returns a chat id**, so it looks accepted. Do not report a phase as started on
the strength of a returned chat id.

Two hard rules:

1. **Every dispatch that targets a worktree carries an explicit `--work-dir <worktree_path>`.**
   Use `--new` only when the fresh-session conditions below apply; otherwise resume the
   existing phase chat by explicit `--chat-id`.
2. **Re-verify the path immediately before each such dispatch.** Do not carry a path forward
   from earlier in this session, from todo progress, or from memory. Take it from live output
   and confirm it exists:
   ```bash
   y dev wt list                      # authoritative current worktrees
   test -d <worktree_path> || echo MISSING
   ```
   If it is missing, stop and re-create it (`y dev wt add`) rather than dispatching into a
   stale path.

### Resume or start fresh within one trace

Prefer resuming: it preserves phase context and avoids making the worker re-read the same plan,
diff, and findings. Resume by explicit `--chat-id <existing phase chat>` when all of these hold:

- same trace
- same phase and same sub-task
- same still-existing worktree
- same tier
- the worker did not retire through a context handoff

Typical resumptions are sending review findings back to the original impl worker, then sending
the fix back to the original review worker for re-review. Before resuming, run
`y chat list --trace-id <todo_id>` and confirm the selected chat belongs to this trace and
phase; never rely on skill or topic default resolution. Keep the explicit `--work-dir` so the
CLI verifies the immutable binding.

Start a fresh `--new` phase session when this is the first dispatch, the sub-task is
independent, the worktree changed or was removed and recreated, the tier changes, the previous
worker handed off because of context pressure, or its accumulated context is now long enough
that preserving it costs more than rebuilding from durable notes. A recreated path with the
same name is still a new worktree, so its old chats remain dead.

```bash
# ❌ WRONG: resumes a review chat bound to an already-removed worktree
y chat --chat-id <old review chat> -m "Re-review in worktree public-api-2897" --trace-id 2897 --from-topic dev

# ✓ RIGHT: fresh session, verified path, explicit --work-dir
test -d <worktree_path> || echo MISSING
y chat --skill review -m "Look at todo 2897, review worktree public-api-2897, callback when done" \
  --work-dir <worktree_path> --new --trace-id 2897 --from-topic dev --tier tier1
```

## Dispatch procedure

The dev coordinator session itself always runs at tier1: upstream dispatchers pass
`--tier tier1` on every `dev` dispatch, because coordination (scoping, sub-task breakdown,
per-dispatch tier decisions) is judgment-heavy regardless of how small the code change looks.
That rule covers *this* session only; it does not propagate to the phase sub-sessions dev
dispatches below.

Bot selection for those sub-dispatches follows the shared judgment-concentration framework in
AGENTS.md, applied per phase: `plan` and `review` are where judgment concentrates, so dispatch
them with `--tier tier1`; `impl` executes an approved plan, so omit the flag and let it resolve
at the tier2 default. Escalate an impl dispatch to tier1 only when the sub-task stays hard at
every step (no clean plan/execute split, deep debugging inside the worktree) or the user asks.
`--tier tier0` is explicit user escalation only; never self-escalate. Never hard-bind a skill
to a bot name or tier: the per-phase guidance above is dispatch policy, decided per dispatch.

**Plan dispatch** (read-only, project main directory, no worktree):

```bash
y chat --skill plan -m "Look at todo <todo_id>, plan/audit phase, callback when done" \
  --work-dir <project_path> --new --trace-id <todo_id> --from-topic dev --tier tier1
```

**Impl dispatch** (one worktree per sub-task):

```bash
y dev wt add <project_path> <name>
y chat --skill impl -m "Look at todo <todo_id>, impl sub-task: brief description, callback when done" \
  --work-dir <worktree_path> --new --trace-id <todo_id> --from-topic dev
```

**Review dispatch** (after impl, against the worktree diff; optional but recommended for
non-trivial changes):

```bash
y chat --skill review -m "Look at todo <todo_id>, review worktree <worktree_name> against plan note, callback when done" \
  --work-dir <worktree_path> --new --trace-id <todo_id> --from-topic dev --tier tier1
```

**Push and deployment**: after review approval and `y dev commit`, push the target branch and
watch the deployment gate from this coordinator:

```bash
git -C <project_path> push origin <target_branch>
gh run list --limit 10
gh run watch <run_id> --exit-status
```

Only run remote smoke checks after the relevant deployment workflow has succeeded. If the
workflow fails, report the failure and do not smoke-test against a stale deployment. If the
change is local-only or has no deployed surface, prefer focused local verification or suggested
commands. Once your deployment flow grows past a few commands, split it into its own `deploy`
leaf skill and dispatch it the same way as `plan` / `impl` / `review`.

`plan` / `impl` / `review` are loaded as anonymous chats via `--skill` (not topic-bound). They
call back to this coordinator's chat via `--chat-id <from_chat>`: this coordinator is *their*
parent and is not top-level, so those callbacks are valid.

**This coordinator's own parent is almost always the top-level `manager` (dispatch prefix
`from:manager`), so do NOT call back.** When you finish (or hit a conflict or blocker), report
directly in your own chat; the user reads it there. Attempting `y chat --chat-id <from_chat>`
back to a `from:manager` dispatcher is rejected by the CLI and wastes a turn. Only call back to
`from_chat` when the dispatch prefix names a non-top-level parent (`from:dev`) with a real
blocking dependency. See AGENTS.md "Callback rules".

Dispatch is fire-and-forget by default. The dev coordinator should not keep itself alive with
`sleep`, repeated `y chat list`, or todo progress polling after dispatching `plan`, `impl`, or
`review`. Continue only when there is a real callback, a user message, or an explicit resume
with a concrete next step.

## Workflow

1. `y todo get <todo_id>`: read the requirements **and the `[dev-claim]` ownership state**.
2. **Claim the todo**: if free → write `[dev-claim] CLAIM chat=$Y_CHAT_ID at=<ts>`; if owned by
   another live coordinator → surface the conflict to the dispatcher and **stop**; if already
   mine → continue.
3. `y todo activate <todo_id>`: mark in progress.
4. **Determine the target branch** (see "Branch and push policy") and check out / pull the
   right base in the project repo.
5. **Decide the path** (plan first vs. direct impl) based on todo state.
6. **If plan first**: dispatch `plan`, then stop at the natural boundary. When its callback
   arrives, read the updated todo for the sub-task list.
7. **Per sub-task**:
   - `y dev wt add <project_path> <name>`: create the worktree
   - dispatch `impl` with `--new` and `--work-dir <worktree_path>` taken from that command's
     literal output
8. **On the impl callback**: look up the worktree from todo progress, **re-verify it exists**
   (`y dev wt list` / `test -d`) before dispatching anything into it, then:
   - **Optional**: dispatch the first `review` against the worktree before commit (recommended
     for non-trivial changes) as a fresh `--new` session with an explicit `--work-dir`
   - On `request-changes`, resume the original impl chat via explicit `--chat-id`; after the
     fix, resume the original review chat for re-review. Start fresh only when one of the
     conditions in "Resume or start fresh within one trace" applies, and when you do, name the
     existing review note in `-m` so the fresh worker appends a round to it instead of opening
     a second note (see the `review` skill, "One deliverable, one note")
   - `y dev commit <worktree_name>`
   - `y dev wt rm <worktree_name>`: **from here on every phase chat bound to that worktree is
     dead**; any later phase in this trace needs a new worktree and new sessions
9. **After commit**: if pushed or deployed behavior must be checked, push and watch the
   deployment gate, then run any remaining focused local verification or report the exact
   manual verification steps.
10. Once all sub-tasks and required verification are done, update todo progress, write a
    `[dev-claim] RELEASE`, and report that it is ready for user verification **in your own
    chat**: read the linked plan and review notes and write the user-facing summary here (the
    workers do not write one, see Notes). Your dispatcher is normally the top-level
    `from:manager`, which does not accept callbacks. Do not run `y todo finish <todo_id>`
    unless the user explicitly confirms completion or the todo/dispatch explicitly authorizes
    agent completion.

## Session restart (context handoff)

Per AGENTS.md "Context handoff", role position decides the handoff shape, and the dev
coordinator sits on both sides of it:

- **This coordinator restarts itself.** Its dispatcher is normally the top-level `manager`, so
  there is nobody to hand back to: it spawns a fresh dev coordinator on the same trace and
  retires.
- **Its children never restart themselves.** A `plan` / `impl` / `review` worker that runs low
  on context calls back here with what it finished and what is left; **this coordinator then
  dispatches a fresh worker** for the remainder (new `--new` session, `--work-dir` re-verified
  per "Worktree binding"). Never reply "restart yourself and continue"; that hands the
  coordinator's own scheduling job to a leaf.

**When to restart**: a handoff reminder arrives on a message, or the session is obviously long.
Restart at a quiescent point, right after processing a child callback and before dispatching
the next phase.

**⛔ Never restart with children in flight.** Dispatched workers call back to
`--chat-id <this chat>`. Retire this chat while one is running and that callback lands on a
dead session, stalling the trace. If a child is running, stop and wait for its callback
(waiting burns no context), then hand off.

**Procedure:**

1. Record where the trace stands, in the todo. This is what the successor reads, not a message:
   ```bash
   y todo update <todo_id> --progress "[dev-handoff] chat=$Y_CHAT_ID at=$(TZ=<TZ> date +'%Y-%m-%d %H:%M') done=<phases finished> next=<next step> wt=<worktree name or none> branch=<target branch>"
   ```
2. Release the claim. A restart is a handoff of the todo, so the successor can `CLAIM` cleanly
   instead of needing an explicit `TAKEOVER`:
   ```bash
   y todo update <todo_id> --progress "[dev-claim] RELEASE chat=$Y_CHAT_ID at=$(TZ=<TZ> date +'%Y-%m-%d %H:%M')"
   ```
3. Spawn the successor coordinator: same trace, `--new`, and `--tier tier1` (every dev session
   is tier1):
   ```bash
   y chat --topic dev -m "Look at todo <todo_id>, context handoff: continue coordination from the Dev-handoff line in 'y todo get <todo_id>'. Predecessor chat <this chat id> is retiring, do not callback to it, report in your own chat." \
     --work-dir <project_path> --new --trace-id <todo_id> --tier tier1 --from-topic dev
   ```
4. Report in your own chat that the trace moved to a fresh coordinator, and stop. Dispatch
   nothing else and do not poll the successor.

**Arriving as the successor**: the dispatch prefix says `from:dev`, but that parent is
retiring, so treat yourself as top-level (report in your own chat, no callback). Run the normal
opening (`y todo get <todo_id>`, claim, activate); the `Dev-claim:` line is a `RELEASE`, so the
todo is free and you write an ordinary `CLAIM`. `y todo get <todo_id>` surfaces the
predecessor's state as a compact `Dev-handoff:` line (`done=` / `next=` / `wt=` / `branch=`)
even after the release overwrote `Dev-claim:`. Rebuild context from that line plus the linked
plan and review notes, and re-verify any worktree it names (`y dev wt list`, `test -d`) instead
of trusting the path.

## Parallel sub-task caveats

- Each impl child runs in its **own worktree**, which avoids conflicts.
- Sub-tasks must be **independent** so they can commit and merge separately.
- Impl workers claim sub-tasks via `y todo update --progress` (recording chat id + worktree);
  the coordinator reads progress to match commit and cleanup callbacks.

## Notes

- **Notes live at `$Y_AGENT_HOME/pages/`, never inside a project**: plan and review notes from
  workers must land at `$Y_AGENT_HOME/pages/<name>.md` (absolute path). When dispatching, the
  `--work-dir` is the project or worktree, but the worker must still write to `pages/` via the
  absolute path. If you ever see `<project>/pages/` or `<worktree>/pages/` in a callback, that
  is a bug: move the file and re-assoc.
- **Branch and push policy is enforced up front**: see the "Branch and push policy" section.
- **`-m` just says "Look at todo `<todo_id>`"**: the worker reads the todo plus the linked plan
  note for full context. This holds for *re-dispatches* too: sending `impl` back to fix a
  `request-changes` means naming the review note path, not pasting its findings into the
  message. If the worker needs context that is not yet in the todo or a linked note, put it in
  the note (or `y todo update --progress`) and point at it. Do not grow the message.
- **This coordinator is the only session in the sub-tree that writes a summary for the user.**
  `plan` / `impl` / `review` deliberately end with a one-line callback and leave their
  conclusions in the notes (AGENTS.md "Callback rules"), so a callback saying "review done:
  approve, see pages/review-<id>-<slug>.md" is complete, not terse. Read the note and summarize
  it yourself in the final step. Never ask a worker to "send the full summary in the callback".
- **UI / visual-delta verification is static by default (AGENTS.md)**: when a change produces
  an observable visual delta, do **not** require `impl` or `review` to start a dev server,
  drive a browser, or take a screenshot before commit. The default gate is typecheck/build plus
  lint and non-browser tests. Agent-driven browser inspection and screenshots are opt-in: only
  demand them if the user explicitly asked. If the user did ask and the callback has no
  evidence, send it back. Cheap non-browser smoke (curl an API, run the test suite) stays fine.
- **A chat's `work_dir` is immutable, so a new worktree always means a new chat.** See
  "Worktree binding"; never re-point an existing phase chat at a different worktree.
- **Long-running / interactive processes belong in `tmux` (AGENTS.md).** This coordinator
  rarely runs one itself, but it decides what to do when a worker's callback says one is still
  alive (a manual deploy script, a device-code login pane). Two consequences: when a worker
  hands off mid-deploy, take the `tmux=<session>` name from its progress or callback and pass it
  in the next dispatch's `-m` so the fresh worker **inspects that pane
  (`tmux capture-pane -p -t <session>`) before re-running anything mutating**; and do not treat
  a deploy as unfinished merely because the worker's turn ended. The pane, not the chat, holds
  the truth.
- **When resuming after worktree removal**: recreate the worktree of the same name
  (`y dev wt add`) and dispatch a **fresh** `--new` phase session against it. The old phase
  chats from before the removal stay dead even if the path is recreated identically. If the
  original worktree still exists and the phase, sub-task, trace, and tier are unchanged, resume
  its existing chat instead.
- **New requirement inside an active coordinator chat**: the dev coordinator chat is bound to
  one todo's trace. When **the user** raises a **new, unrelated requirement** inside it, do NOT
  mix two todos' work in the same coordinator. This is the only case where this coordinator may
  create a todo (see "Never create follow-up todos yourself"; a follow-up you discovered
  yourself does not qualify). Create the todo, say in your reply that you created it, and spin
  up a **fresh** dev coordinator with `--new`:
  ```bash
  y todo add "<new task>" -d "<desc>" -p <priority> -t <tags>
  y todo activate <new_todo_id>
  y chat --topic dev -m "Look at todo <new_todo_id>, <hint>" --work-dir <project_path> --new --trace-id <new_todo_id> --from-topic dev --tier tier1
  ```
  Do NOT expect a callback: the new coordinator runs independently. The current coordinator
  stays focused on its original todo.
