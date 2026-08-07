# CLI contract

The rules in `AGENTS.md` and `skills/*/SKILL.md` are written against the `y` CLI. This page
lists **the entire command surface those rules depend on**, so you can either run them as
written (install the CLI, see `../docs/cli.md`) or rebind them to your own tooling.

There are only four groups. Everything else in `y` is unrelated to orchestration.

## 1. Dispatch: `y chat` (top level, no subcommand)

The one primitive the whole model rests on: hand a task to another agent session.

```bash
y chat -m "<message>" \
  [--topic <name> | --skill <name> | --chat-id <id>] \
  [--work-dir <path>] [--new] \
  [--trace-id <id>] [--from-topic <name>] \
  [--tier tier0|tier1|tier2|tier3] [--bot <name>] \
  [--wait]
```

| Flag | Meaning |
|------|---------|
| `-m, --message` | The message. One line by convention; details live in notes. |
| `--topic` | Address a **named persistent session**. Resumes that topic's latest chat unless `--new`. |
| `--skill` | Address an **anonymous session** that loads this skill. Combined with `--topic`, it sets the skill on the topic's chat. |
| `--chat-id` | Address **one specific existing chat** (this is how a callback is sent). |
| `--work-dir` | Working directory for the target session. **Immutable once the chat exists**: a later send with a different value is rejected. |
| `--new` | Force a new chat instead of resuming. Required on the first dispatch of a trace. |
| `--trace-id` | Threads the session tree. Set to the todo id when the task is tracked. |
| `--from-topic` | Names the caller, so the receiver can tell whether its parent is the root. |
| `--tier` | Quality band for backend selection. Empty or no match resolves to `tier2`. |
| `--bot` | Pin one specific backend. Reserved for capability pins and for tasks where the bot *is* the object. |
| `--wait` | Block until the reply is ready and print it. The **only** sanctioned synchronous wait. |

Two more pieces of the contract are not flags:

**Message prefix.** A dispatched session receives its message prefixed with

```
[trace:<trace_id> from:<topic> to:<topic> from_chat:<chat_id> to_chat:<chat_id>]
```

Sessions read the trace id and `from_chat` straight out of this prefix. Without it, callbacks
and trace isolation do not work.

**Injected environment.** Each session gets `Y_TRACE_ID`, `Y_TOPIC`, and `Y_CHAT_ID` as
read-only variables. `Y_CHAT_ID` in particular is what makes the dev claim protocol possible.

**Rejecting callbacks to the root.** A callback addressed to the top-level dispatcher topic is
rejected by the CLI. That rejection is load-bearing: it is what stops a root session from being
treated as a function call.

Lookup form used by the rules:

```bash
y chat list --trace-id <todo_id>     # which chats belong to this trace
```

## 2. Task state: `y todo`

The trace id is a todo id, so the todo table doubles as the trace registry and the durable
handoff surface between sessions.

```bash
y todo add "<name>" -d "<desc>" -p <priority> -t <tags>
y todo get <id>                         # desc, notes, progress, linked notes
y todo activate <id>
y todo update <id> --progress "<line>"  # append-only progress channel
y todo finish <id>
y todo list [filters]
```

What the rules require of this surface:

- **`--progress` is append-only and readable back.** Handoff state, sub-task claims, and the
  `[dev-claim]` lock all live here. If your equivalent overwrites instead of appending, the dev
  ownership protocol breaks.
- **`y todo get` surfaces the latest `[dev-claim]` and `[dev-handoff]` markers** as compact
  `Dev-claim:` / `Dev-handoff:` lines, so a coordinator does not have to page through full
  history to learn ownership.
- Status vocabulary: `pending` → `active` → `completed`, plus `deleted` as a soft delete.

## 3. Artifacts: `y note` / `y assoc`

Plan, review, and decision notes are files under `$Y_AGENT_HOME/pages/`. The association is
what lets a downstream session rebuild context from the todo alone.

```bash
y assoc note <path_relative_to_Y_AGENT_HOME> --todo <todo_id>
y note list / get                       # browse
```

The rule that matters: **`y todo get` must list the associated notes**, because every "the note
is the deliverable, the callback is a pointer" convention depends on the receiver being able to
find the note from the todo id.

## 4. Worktrees: `y dev`

Only the `dev` skill uses this. It is a thin convenience wrapper over `git worktree`.

```bash
y dev wt add <project_path> <name>   # create worktree + branch off current HEAD
y dev wt list                        # authoritative paths
y dev wt rm <name>                   # remove worktree + branch
y dev commit <name> [-m "<msg>"]     # commit, rebase onto the target branch, fast-forward merge
```

Two behaviors the rules rely on: `wt add` branches off the repo's **current HEAD** (hence "set
the target branch first"), and `wt list` prints the **authoritative** path (hence "never
hand-construct worktree paths").

Plain `git worktree` plus a two-line shell function substitutes for this entirely.

## 5. Backend registry: `y bot`

Used only to look up which backend sits in which tier.

```bash
y bot list
y bot update <name> -t <tier>
```

The rule is that **config never names a bot for quality reasons**, only a tier. This registry is
what makes tiers reassignable data instead of a constant frozen into prose.

---

## Rebinding to other tooling

If you are not running `y`, these are the capabilities you must supply. Nothing here is exotic;
the rules assume this shape, not this implementation.

| Capability | Minimum you need |
|------------|------------------|
| **Dispatch** | Start (or resume) another agent session with a message, a working directory, and a chosen backend. Return immediately. |
| **Addressing** | Three ways to name a target: a stable name, a fresh anonymous session, and a specific existing session. |
| **Trace threading** | An id that travels with every dispatch and is visible to the receiver. |
| **Caller identity** | The receiver must be able to tell *who* dispatched it and whether that caller is the root. |
| **Callback** | Send a message into a specific existing session. Reject callbacks to the root. |
| **Task record** | A record per trace with a description and an append-only progress log both sides can read. |
| **Artifact linking** | Attach file paths to that record, retrievable by trace id. |
| **Backend tiers** | A way to request a quality band rather than a named model. |

The two capabilities that are easy to under-build, and where the model degrades quietly if you
do:

1. **An append-only progress log the receiver can read.** Without it, every handoff has to go
   through the message channel, and context handoff, sub-task claiming, and the dev lock all
   stop working.
2. **Caller identity in the received message.** Without it, a session cannot tell a callback
   from a fresh dispatch, cannot detect a cross-trace message, and cannot decide whether to call
   back or report in place.

Things you can safely skip when rebinding: topics (use ids), tiers (use one model), and the
worktree wrapper (use `git worktree` directly).
