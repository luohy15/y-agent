# Agent Operating Rules

These rules are loaded by **every** session in the tree. Skill-specific rules live in
`skills/<name>/SKILL.md` and are loaded only when that skill is active.

Paths written as `$Y_AGENT_HOME/...` refer to your workspace root (the `Y_AGENT_HOME`
config key, see `docs/cli.md`). Nothing below assumes a particular machine or user.

## Task management (`y todo`)

Every session operates the todo CLI directly. There is no separate task-management skill.

> **Todo content is always English**: `name` / `desc` / progress notes (`--progress`). Even
> when the conversation is in another language, translate before writing.

Full reference: `y todo --help` / `y note --help` / `y assoc --help`.

**Association covers both what you wrote and what you read.** A pre-existing note you only
read or referenced still gets `y assoc note <path_or_id> --todo <todo_id>`, not just the
notes you created.

**Notes have one home**: plan / review / decision / design notes are written with the
absolute path `$Y_AGENT_HOME/pages/<name>.{md,html}`, even when `--work-dir` points at a
project or worktree. `y assoc note` takes the path relative to `$Y_AGENT_HOME`, so
`pages/<name>.md`.

Priority: `high` / `medium` / `low` / `none`
Status: `pending` → `active` → `completed` (`deleted` is a soft delete)

### Todo creation is authorized, not self-selected

**Creating a todo is not an agent's discretionary move.** Outside the exceptions below, no
session may run `y todo add` on its own: follow-ups discovered mid-task, nits, tech debt,
"while we're here" cleanups, out-of-scope findings from a review, sub-items a plan ruled
out of scope. All of those are **reported, never queued**. Where to report:

- in the current todo's progress note (`y todo update <id> --progress "follow-up: ..."`)
- in the artifact you are producing (a plan note's "out of scope / follow-up" section, a
  review note's nits section)
- by name in your callback or in your own chat, so the user decides whether to queue it

**The only three exceptions:**

1. **The top-level dispatcher creating a todo from an explicit user request** (its "no todo,
   no dispatch" rule: user states a requirement → create todo → dispatch).
2. **The user, in the current chat, explicitly asks for a todo** ("make a todo for that").
   A brand-new requirement raised by the user in a non-dispatcher chat also counts, but say
   so in your reply ("created todo `<id>` for that"); never create one silently.
3. **Todos a routine's own mechanism needs** (a scheduled routine's run record).

**Why**: the todo list is the user's work queue. Agent-invented entries bury the tasks they
actually want. Finding a problem is valuable; deciding it is work is theirs.

### Todo completion needs confirmation

For todos the user created or owns, do not run `y todo finish <id>` on your own. Record the
outcome with `y todo update <id> --progress "..."` and state in your reply or callback that
it is ready for user verification. Only run `finish` when the user explicitly asks in the
current context, or when the todo/dispatch explicitly authorizes the agent to complete it.

Routine-owned todos (exception 3 above) may auto-finish per their own workflow. When in
doubt about the owner, default to requiring confirmation.

## Workflow evolution

1. **Natural language first, code second**: a new process starts as prose in a `SKILL.md`
   and runs on the agent's understanding.
2. **Repetition is the signal**: once a process has stabilized and run many times, it should
   become code (a CLI subcommand, a hook, a script).
3. **What codifying buys**: fewer tokens, faster execution, deterministic results.
4. **Propose it proactively**: when you notice a natural-language workflow has stabilized,
   tell the user it is ready to be codified. Do not wait to be asked.

## Software engineering philosophy

Default principles for every session writing code, designing a process, or making a change:

1. **DRY**: one authoritative source per piece of knowledge or logic. Extract on repetition,
   do not copy-paste.
2. **KISS**: pick the simplest thing that works. No abstraction layers for imagined needs.
   Three similar lines beat one premature abstraction.
3. **YAGNI**: implement only what the current task needs. No unused error handling,
   fallbacks, feature flags, or backward-compatibility shims.

This is a default bias, not dogma. When a task genuinely calls for it (a real extension
point, boundary input validation), do it.

## Architecture: recursive session tree

The system is a tree of sessions. Every node is homogeneous and spawns children on demand.

### 1. A session is a tree node

Every session is the same kind of thing: a runtime unit that loads some skills, executes a
task, and spawns sub-tasks as needed. Whether it has children, and whether it sits at the
top, are runtime facts about the current task, not design-time types.

### 2. Coordinating is a capability, not a type

Every session can coordinate (dispatch sub-tasks via `y chat`). **Whether it does is decided
by task complexity**, not by design:

- simple task → one session closes the loop
- complex task → a sub-tree grows naturally

No role needs to be pre-declared "coordinate only" or "execute only". The same session may
do the work itself this time and dispatch it next time.

### 3. Skills are session-local capability bundles

Skills are loaded per task and **are not bound to a topic**. The same topic can load
different skill combinations for different tasks.

### 4. Topics are sugar, not architecture

A topic provides two independent things:

- **a named persistent address**: a long-lived name for a session, instead of a chat id
- **a chat binding**: lets a user participate in that long-lived chat from a messaging client

Anonymous ephemeral sessions are equally valid. Address them by chat id; no topic needed.

### 5. The trace id (= todo id) is the spine

A trace is one root-to-leaf path through the tree, threading every session the task passed
through. Multiple traces coexist as a forest. When a task is tracked by a todo, the
**trace id is the todo id**.

### 6. Dispatch is a parent → child handoff

`y chat` (top level, no subcommand) is the one-way edge from parent to child:

- **one-way**: parent → child
- **callback optional**: a child may message its parent back (`--chat-id <from_chat>`), or
  be fire-and-forget
- **top-level nodes accept no callback**: the root session has no parent to return to. It is
  a conversation, not a function call.

## Cross-session dispatch (`y chat`)

Dispatch sub-tasks to other sessions with `y chat` (top level, no subcommand). Fire-and-forget
by default.

**Note**: `y chat` is also the history query entry point (`y chat list / get / search`). Only
the dispatch form is described here.

**Important**: dispatching a sub-task must go through `y chat`, never a direct in-process
skill invocation. When the user says "have dev do it", that means a child session, not
loading the dev skill here. Invoking the skill directly loses the trace context and flattens
the session tree.

**⚠️ A coordinating session does not do the work itself.** Once the current session is in a
coordinating role, do not drift into executing the sub-task (reading code, researching,
root-causing, writing the artifact). When you catch yourself thinking "this is quick, I'll
just do it", stop and dispatch instead.

```bash
# The two common forms: dispatch to a topic with a trace, and force a new chat
y chat --topic <topic_name> -m "message" --work-dir <path> --new ${=Y_TOPIC:+--from-topic $Y_TOPIC} ${=Y_TRACE_ID:+--trace-id $Y_TRACE_ID}

# Anonymous session with an explicit skill (no topic)
y chat --skill <skill_name> -m "message" --work-dir <path> --new ${=Y_TOPIC:+--from-topic $Y_TOPIC} ${=Y_TRACE_ID:+--trace-id $Y_TRACE_ID}
```

Remaining flags (`--bot`, `--wait`, ...): `y chat --help`.

**Target resolution**: `--topic` / `--skill` / `--chat-id` are three independent optional
flags; whichever you pass is how the target is addressed. Most common is by topic (a
persistent named address). By chat id addresses one specific session (a callback). By skill
addresses an anonymous session. With none of them (bare `y chat -m ...`), an anonymous
content session is created.

### Tier selection

Do not pass `--bot` / `--tier` by default; a dispatch then resolves at `--tier tier2` (the
system default). **Never hard-bind a skill or topic to a bot or a tier**: the tier is decided
by the shape of *this* task. Tier roles: tier1 (explicit, judgment-heavy work) and tier2
(default, everyday work) are the daily band; tier0 (explicit user escalation) and tier3
(cheap routines / one-shots) are the low-frequency band.

- **Judgment-dense sessions** (planning, review, architecture decisions, root-cause analysis,
  complex coding, multi-phase coordination): pass `--tier tier1` explicitly. What these
  sessions produce (a plan note, a verdict, a decision) is the quality lever for the whole
  trace, so the strong model pays off most here.
- **Coordinating sessions are always in the tier1 band**: if the dispatched session will
  itself break down sub-tasks and make a tier decision per dispatch (a dev coordinator, a
  dispatcher restarting itself), pass `--tier tier1` even when the requirement sounds like a
  one-line change.
- **Mechanical leaf executors with a clear upstream plan** (implementing an approved plan,
  config text edits, data entry, routine maintenance): omit the flag and let it resolve at
  the tier2 default. Quality is carried by the upstream plan artifact; the executor does not
  need a stronger model. **This band is for leaf sessions only** (sessions that finish the
  work themselves and dispatch nothing further). A coordinating session never lands here,
  however mechanical this particular task looks.
- **Tasks that are hard at every step** (no clean plan/execute split, deep debugging): run
  the whole session at `--tier tier1`. Do not expect one plan note to front-load the
  difficulty away.
- **tier0 is for explicit user escalation only**; an agent never selects it. The typical case
  is tier1 underperforming on a task and the user asking for a rerun. There is no
  "judgment-heavy auto-escalates to tier0" rule.
- **tier3 is for cheap, low-frequency or low-risk work**: routines, simple one-shots. Pass
  `--tier tier3` explicitly.
- A user's explicit bot / tier always wins. When unsure of the difficulty, treat it as tier1
  (a weak backend botching a hard task costs more than a strong backend doing an easy one).
- Tier membership is data, not memory: when you need an explicit bot name, look it up with
  `y bot list`. Rate a new bot by actually testing it, then `y bot update <name> -t <tier>`.
  Do not go by impression.

**⚠️ Rules bind to tiers, not to bot names.** Any **quality-band** requirement written into
config (this file, a `SKILL.md`, a skill script) uses `--tier`, never a specific bot name:
a bot's tier membership is data that changes (`y bot update <name> -t <tier>`), and a rule
naming a bot will eventually point at one that has been re-rated or retired. The single
exception is a **capability pin**: the dispatch needs something only one bot can do (say,
web-grounded search) that a tier cannot express. Annotate a capability pin in place as such,
otherwise nobody can tell it apart from a stale quality-band pin. A separate legitimate use
of a bot name is as a **parameter**: when the bot itself is the object of the task (testing a
bot), pass `--bot <name>` normally, but write it as a placeholder supplied by the caller
rather than freezing one name into config.

**⚠️ Assessing the tier is a mandatory step of every dispatch, done before writing the
command**: dispatching to a coordinator → always `--tier tier1`; judgment-heavy or unsure →
`--tier tier1`; mechanical leaf execution → omit the flag; routine / low-stakes →
`--tier tier3`; user asked → pass what they asked. Dispatching judgment-heavy work bare, or
selecting `--tier tier0` yourself, is a violation on par with dropping the trace id.

**Fire-and-forget vs interactive**: a successful send means the task was handed to a child
session, not that it is done. After sending, stop at a natural boundary and continue when a
callback or resume arrives. `--wait` blocks until the reply is ready and prints it; use it
for genuine one-shot question/answer.

**⚠️ Never watch a child session for completion (no-poll).** After dispatching, the current
session **must not** wait around for the child by any means, including:

- `sleep N; y chat get <chat_id>` (sleep, then grab the child's state: the classic violation,
  **forbidden**)
- `sleep` loops or `while` polling of anything
- repeated `y chat list` / `y chat get` checking for new messages
- polling `y todo get` progress for the sub-task's status
- any construction that keeps the turn alive to observe a child finish

Dispatch is a one-way handoff: when and whether a result comes back is the child's decision.
**The only legitimate synchronous wait is `--wait`.** Do not hand-roll `sleep; y chat get`.

### New todo = new chat

Each new todo is a new trace and **must** get a new chat. Reusing another todo's chat injects
this trace's messages into that one and corrupts the trace tree.

**One chat serves exactly one trace.** If the current chat already carries `[trace:<old>]`
and the user raises a new requirement needing a new todo / trace, this chat may only create
or dispatch an entirely new chat and then stop. Do not keep executing, coordinating,
receiving callbacks, or reporting another trace's results here.

**Rules before dispatching:**

1. **First dispatch of a todo: `--new` is mandatory.** Without it, `y chat --topic <name>`
   resumes that topic's most recent chat, which usually belongs to a different todo.
2. **To send again to a chat that already belongs to this trace, look it up first** with
   `y chat list --trace-id <todo_id>`, then address it explicitly with `--chat-id <id>`. Do
   not rely on the topic's default resume.
3. **Same before a callback**: confirm `from_chat` belongs to the current trace with
   `y chat list --trace-id <todo_id>`.
4. **Check the prefix on an incoming callback**: if its `[trace:<id>]` does not match the
   trace this chat is bound to, stop and report a trace mismatch. Do not commit, push, update
   the other todo, or report completion.

```bash
# First dispatch for todo 1900 (force a new chat, reuse nothing)
y chat --topic dev -m "Look at todo 1900" --work-dir <path> --new ${=Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id 1900

# Sending again within this trace: look up, then address explicitly
y chat list --trace-id 1900
y chat --chat-id <id_from_list> -m "..." ${=Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id 1900
```

### One-off bulk fan-out: dispatch in a script loop

When a session faces a **one-off, large batch of fan-out sub-tasks** (fixed steps, many
independent items to dispatch in parallel: one session per file, per row, per symbol),
**write a small script that loops `y chat` and dispatches them all at once** rather than
having the live session dispatch them one turn at a time.

```bash
# Right: a script loop dispatches every item deterministically
for item in $(cat items.txt); do
  y chat --skill <skill_name> -m "Process $item" --work-dir <path> --new \
    ${=Y_TOPIC:+--from-topic $Y_TOPIC} ${=Y_TRACE_ID:+--trace-id $Y_TRACE_ID}
done
```

**Why put it in code**: it avoids agentic laziness (turn-by-turn dispatch tends to stop
halfway), keeps intermediate results out of the coordinator's context, and guarantees every
item actually gets dispatched.

**Scope**: one-off bulk fan-out only. Ordinary small dispatches (one or two sub-tasks,
multi-phase orchestration where each callback informs the next step) stay as individual
`y chat` calls. Do not wrap those in a script.

### Trace context

The `y chat` CLI **does not** read environment variables implicitly; pass them explicitly.
Print them first to confirm, then pass them:

```bash
echo "Y_TRACE_ID=$Y_TRACE_ID Y_TOPIC=$Y_TOPIC"

y chat --topic <topic_name> -m "message" ${=Y_TOPIC:+--from-topic $Y_TOPIC} ${=Y_TRACE_ID:+--trace-id $Y_TRACE_ID}
```

**Flag rules:**
- `--trace-id` (optional): pass it only when there is a real trace (`$Y_TRACE_ID` non-empty,
  or an associated todo id). Otherwise omit it; do not fall back to `$Y_CHAT_ID`. Form:
  `${=Y_TRACE_ID:+--trace-id $Y_TRACE_ID}`
- `--from-topic` (optional): pass only when `$Y_TOPIC` is non-empty. Form:
  `${=Y_TOPIC:+--from-topic $Y_TOPIC}`

Injected read-only environment variables:
- `Y_TRACE_ID`: the current trace id (may be empty)
- `Y_TOPIC`: the current topic name (may be empty)
- `Y_CHAT_ID`: this session's own chat id

When the task is tied to a todo, **set the trace id to the todo id** (overriding the
environment value). `-m` then carries only the todo id plus a short hint, never the
requirement text:

```bash
# Right: reference the todo, the receiver reads the details itself
y chat --topic <topic_name> -m "Look at todo 1710, implement the note feature" --work-dir <path> ${=Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id <todo_id>

# Wrong: restating the requirement in -m
y chat --topic <topic_name> -m "We need: 1) a new note table 2) a content_key column 3) ..." --work-dir <path> ...
```

**Receiver convention**: on a message carrying a trace id, run `y todo get <trace_id>` first
and read the todo's desc / notes / progress before starting.

### Trace propagation

An incoming message is prefixed
`[trace:<trace_id> from:<topic_name> to:<topic_name> from_chat:<chat_id> to_chat:<chat_id>]`:
- `from_chat`: the sender's chat id
- `to_chat`: the receiver's chat id (this session)

Take the trace id straight from the `[trace:xxx]` prefix (no lookup needed) and pass it
explicitly when dispatching downstream or calling back, to keep the chain intact.

### Callback rules

A callback is optional; the agent decides whether one is warranted.

- **Top-level nodes accept no callback**: the root session has no parent, and is a
  conversation rather than a function call. The CLI rejects a callback addressed to it.
- **How to tell whether the parent is top-level (check before every callback)**: read
  `from:<topic>` in the dispatch prefix. **`from:<top-level dispatcher topic>` means the
  parent is the root, so do not attempt a callback**: report in your own chat instead, where
  the user is reading. Only call back with `--chat-id <from_chat>` when `from:` names a
  non-top-level intermediate session (for example `from:dev`) that has a real blocking
  dependency.
- **Calling back to `from_chat` (optional)**: when the result matters to the parent (it
  cannot continue without it), address the target chat directly (no `--topic` needed):
  ```bash
  y chat --chat-id <from_chat> -m "<result>" ${=Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id <trace_id>
  ```
- **No callback needed when**: the parent is the root, the result does not affect the
  parent's next step, or the task was fire-and-forget.
- **A callback is needed when** the parent has a real blocking dependency (an impl dispatch
  that can only happen after the plan lands). Even then the parent does not sleep-poll: it
  stops at a natural boundary after dispatching and continues on a real callback or resume.
- **A dispatched session does not write a long closing summary in its own chat**: the
  authoritative copy of its output is the note plus `y todo update --progress`, and the
  callback is a one-line pointer. Nobody reads these sub-session chats; the parent reads the
  note and reports to the user. The closing sequence is: write note → assoc → one-line
  callback → stop. A root session is the opposite: nothing else will read its notes for the
  user, so it reports results directly in its own chat. **Exception**: a session whose whole
  job is conversing with the user in its own chat answers normally. This rule only forbids
  closing summaries with no reader.

### `-m` message conventions

**Important**: `-m` carries message content only. Do **not** write the
`[trace:... from:...]` prefix into `-m`; trace context travels via `--trace-id` and
`--from-topic`, and duplicating it in the body is noise.

**⚠️ `-m` is always English.** Dispatch and callback messages are shared across sessions and
retained as trace records; mixed languages pollute the trace tree and `y chat` search. Even
when the originating conversation is in another language, translate for `-m`.

**⚠️ `-m` is one line; details belong in the note.** Dispatching: "Look at todo `<id>` +
one-line sub-task description". Calling back: "done / verdict + note path". Do not paste
requirement blocks, diff summaries, finding lists, or per-item status reports into `-m`: the
authoritative copy already lives in the plan note / review note / todo progress, and a second
copy in the message is one more thing to drift while inflating both sides' context. The
receiver takes the pointer and reads the todo plus linked notes itself.

```bash
# Right
y chat --topic <topic> -m "Update done" ${=Y_TOPIC:+--from-topic $Y_TOPIC} ${=Y_TRACE_ID:+--trace-id $Y_TRACE_ID}

# Wrong: duplicated trace info
y chat --topic <topic> -m "[trace:bc5062 from:dev] Update done"
```

## Context handoff

A session's context window is finite; once full it loses context and repeats work. Triggers:
a system handoff reminder, or the session judging the conversation has gotten long. Hand off
per the playbook below.

**How you hand off is decided by your position in the tree, not by your skill name.** The
same skill may be a leaf this time and carry a sub-tree next time. The only test:
**is there a parent waiting on my result** (a `from_chat` in the dispatch prefix, with `from:`
naming a non-root session)? Yes → call back. No → restart yourself.

### Leaf / dispatched executor: call back, do not restart yourself

For plan / impl / review style sessions dispatched by a parent:

1. **Do not spawn a same-role successor yourself** (no `y chat --skill impl ... --new` to hand
   off to yourself). Who to dispatch, how many, at which tier, in which worktree, is the
   parent's scheduling job. A self-made successor bypasses the parent and leaves it waiting
   on a chat that has stopped working.
2. First close down to a **handoff-able boundary**: finish the change in hand (no half edit,
   no half file), run the verification you can, start no new sub-tasks.
3. Write the durable state into the todo (`y todo update <todo_id> --progress "..."`) and the
   note, **not** just the callback message: what is done, what remains, where the worktree /
   branch / files are, where to pick up.
4. Call back to the parent, saying this is a context handoff and what remains, so the parent
   dispatches a fresh session for the rest:
   ```bash
   y chat --chat-id <from_chat> -m "handing off (context limit): done <X>; remaining <Y>; state in todo progress" \
     ${=Y_TOPIC:+--from-topic $Y_TOPIC} --trace-id <todo_id>
   ```
5. Then stop. Start no new work.

### Coordinator / long-lived session: restart yourself

For coordinating sessions (the root itself, or one whose parent is the root, with nobody
waiting on a callback): spawn a fresh same-role session to take over, and retire. Role-specific
details live in each `SKILL.md`. Common points:

- **Hand off at a quiet point**: no child running that will call back into this chat. If one
  is in flight, stop and wait for its callback (waiting costs no context), handle it, then
  hand off. Retiring early leaves the child's callback landing on a dead chat and stalls the
  trace.
- **State goes into the todo / notes, not into the message**: the successor rebuilds context
  from `y todo get <todo_id>` plus linked notes. `-m` only says "this is a context handoff,
  continue from step X".
- **The successor uses `--new` with the same `--trace-id <todo_id>`**: a handoff changes
  neither the trace nor the todo.
- **Tell the successor explicitly not to call back to you**: you are retiring, and it should
  report in its own chat per the top-level rule.

## Time handling

**Never use a bare `date` for time judgments.** The runtime clock is often UTC while the user
is not, which silently writes wrong dates and times into files, notes, and todos.

Always name the zone explicitly, as a literal IANA zone. Substitute yours everywhere `<TZ>`
appears in this config:

```bash
TZ=<TZ> date +'%H:%M'                # current local time
TZ=<TZ> date +'%Y-%m-%d'             # current local date (filenames, logs)
TZ=<TZ> date +'%Y-%m-%d %H:%M:%S'    # full timestamp
```

Write the literal zone (`TZ=Europe/Berlin date ...`), not a variable. In particular
`Y_AGENT_TIMEZONE` is a CLI **config key**, not an exported shell variable: `TZ=$Y_AGENT_TIMEZONE`
expands to empty in a shell and silently gives you UTC, which is the exact failure this rule
exists to prevent.

This applies to anything involving "today" or "right now": note and log filenames, calendar
times, and every timestamp written into a file, note, or todo.

## Long-running / interactive processes (tmux)

The agent's Bash tool has a timeout (600s max here), and a foreground process is killed when
the turn ends. Long or interactive processes do not belong in a foreground Bash call.

### Which one (foreground / nohup / tmux)

| Process shape | How to run it |
|---------------|---------------|
| Seconds to minutes, returns when done (build, test, typecheck, a single CLI call) | Plain foreground call (the default; do not over-engineer) |
| **Non-interactive** long-lived background service (dev server, tunnel, tail) | `nohup <cmd> > <logfile> 2>&1 &` plus a log file and a PID file |
| **Interactive**: you must read output and respond mid-run (device-code login, a confirmation prompt, a passphrase) | **tmux** |
| Expected to run **10+ minutes**: a manual production deploy, a long CI watch, a remote restart chain | **tmux** |

Only two tests: (1) does the running process need input or reading; (2) will it exceed the
Bash tool's cap (raise `timeout` to `600000` when running in the foreground). Either one →
tmux. Neither, but it must persist (a dev server) → `nohup`. Otherwise → plain foreground.

**The name of the operation is not a reason.** "Migration" / "deploy" / "production" / "has
side effects" do not justify tmux: a migration, schema upgrade, or single mutating CLI call
that takes seconds or minutes runs in the foreground. The safety net for side effects is
confirming the target before executing, not wrapping the command in tmux. When unsure of the
duration, measure first (dry run, past timings) and default to foreground.

### Standard usage

```bash
session=<purpose>-<todo_id>        # e.g. deploy-2897, so any successor can find it by todo
tmux has-session -t "$session" 2>/dev/null || tmux new-session -d -s "$session"
tmux set-option -t "$session" remain-on-exit on          # keep the pane after exit to read final output
tmux send-keys -t "$session" '<command>; echo "EXIT=$?"; y chat --chat-id <current_chat_id> -m "tmux <session> finished; inspect pane" --from-topic <current_topic> --trace-id <todo_id> || true' C-m
y todo update <todo_id> --progress "tmux=$session step=<step> state=running; completion will wake this chat"
```

After launching, end the turn at a natural stopping point. When the task completes, the
trailing `y chat` sends an async message to the current chat and resumes the session. On
resume, read the pane **once** (`tmux capture-pane -p -t "$session"`), confirm `EXIT=<code>`,
update the todo progress, then decide the next step. When a run needs human input or a
mid-way judgment, have the command or a helper script send a message at that checkpoint too,
rather than checking the pane on a timer.

Rules:

- **Name it `<purpose>-<todo_id>`** so any successor session can find it from the todo.
- **Carry the exit code out yourself**: `tmux send-keys` returns no exit code, so append
  `echo "EXIT=$?"` and read it from the pane. Do not write `status=$?`: in zsh `status` is a
  read-only alias for `$?`, the assignment fails, and everything after it (the EXIT line, the
  `y chat` wake-up) never runs.
- **Never send secrets through send-keys**: the content lands in the pane's shell history, in
  `capture-pane` output, and from there into notes and callbacks. Put secrets in a gitignored
  file and reference the file in the command.
- **Never poll tmux**: no `sleep N; tmux capture-pane`, no capture loops, no keeping a turn
  alive to wait. Even for "just a moment". Set an async wake-up and end the turn.
- **Do not wrap fast commands, or messages arrive out of order**: if a tmux-wrapped command
  finishes instantly, its trailing `y chat` wake-up is delivered before the current turn ends
  and the message order scrambles. The fix is the table above: keep fast commands in the
  foreground. If you only discover it after wrapping, read `EXIT=` with one `capture-pane`,
  `kill-session`, report normally in this turn, and ignore the wake-up when it arrives.
- **When you cannot set a wake-up**: write `tmux=<session> step=<step> state=running` into the
  todo progress, end the turn, and read the pane once when a real external message arrives.
  Do not fall back to polling.
- **Write the session name into todo progress before handing off**
  (`y todo update <id> --progress "... tmux=<session> state=<running|exited EXIT=0>"`). This
  is the critical part for deploys with side effects: the successor must re-attach and read
  state, not run `./deploy.sh` a second time.
- **Clean up** with `tmux kill-session -t "$session"` once the process has ended and the
  output has been read. If you are unsure whether it is still running, do not kill it.

## Output conventions

- **File paths must be complete**: reference full paths (the way `git diff` prints them), not
  truncated directories or relative fragments.
- **Screenshots and visual artifacts go to `$Y_AGENT_HOME/assets/screenshots/`, never `/tmp`.**
  Name them with context, e.g. `<context>-<todo_id>-<before|after>.png`, and report the full
  path.
- **Agent-driven UI runtime checks (starting a dev server and driving a browser, taking
  screenshots) are off by default; do them only when the user explicitly asks.** Default
  verification is static: a clean typecheck/build, lint if present, and unit/integration
  tests that need no browser. That is enough to report ready for user verification. Still
  allowed: (1) the user asked; (2) the task itself is "run the app"; (3) cheap scriptable
  non-browser checks (`curl` an API, run the test suite, a CLI smoke test). This is a
  deliberate speed-over-verification tradeoff: runtime UI acceptance belongs to the user.
- **When a screenshot is genuinely wanted, use headless Playwright (Chromium)**: reliable
  auto-waiting, hover and clipping support, actively maintained. Install with
  `npx playwright install chromium` if the project lacks it.
  ```js
  // shot.mjs — run: URL=<url> OUT=<abs.png> [SEL=<css>] [FULL=1] node shot.mjs
  import { chromium } from 'playwright';
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  await p.goto(process.env.URL, { waitUntil: 'networkidle' });
  if (process.env.SEL) await p.hover(process.env.SEL);   // optional: reach a hover / specific state first
  await p.screenshot({ path: process.env.OUT, fullPage: process.env.FULL === '1' });
  await b.close();
  ```
  `OUT` is an absolute path under `assets/screenshots/`; report the full path.
- **English for commit-related output**: commit messages and commit-worthy progress notes are
  always English, to keep the commit history in one language.
