# Orchestration config

The agent configuration that runs this system: one always-loaded rules file plus five skills.
Everything here is prose. There is no code in this directory.

It is a distilled, personal-content-free core of a config that has been in daily use for
months. The rules are opinionated because they were each written after something went wrong.

## The model

One idea, applied recursively: **a session is a tree node**.

```
   user        ┌──────────────────┐
   input ────► │  skill: manager  │   dispatch only,
        │      └────────┬─────────┘   never executes
        │               │   y chat --skill dev -m "..."
        │               ▼
        │      ┌──────────────────┐
        ├────► │  skill: dev      │   coordinator,
        │      │                  │   owns worktrees, dispatches phases
        │      └──┬──────┬──────┬─┘
        │         │      │      │   y chat --skill {plan,impl,review}
        │         ▼      ▼      ▼
        │      ┌──────┐ ┌──────┐ ┌────────┐
        └────► │ plan │ │ impl │ │ review │   anonymous, ephemeral;
               └──────┘ └──────┘ └────────┘   skill loaded per dispatch
```

Six properties do the work:

1. **Sessions are homogeneous.** Every node is the same kind of thing: load some skills, do a
   task, spawn children if needed. "Coordinator" and "leaf" are runtime positions, not types.
   The same skill can be a leaf today and carry a sub-tree tomorrow.

2. **Coordinating is a capability, not a role.** Whether a session dispatches is decided by the
   task's complexity, not declared in advance. Simple task, one session. Complex task, a
   sub-tree grows.

3. **A trace id threads the tree.** One trace is one root-to-leaf path. When the task is tracked
   by a todo, the trace id *is* the todo id, so the task record and the trace registry are the
   same object. Multiple traces coexist as a forest.

4. **Dispatch is a one-way handoff, not a function call.** The parent hands work to a child and
   stops at a natural boundary. A callback is optional and the parent never polls for one. The
   root accepts no callback at all: it is a conversation, not a call site.

5. **The note is the deliverable; the message is a pointer.** A leaf writes its output to a
   linked note and calls back with one line. Nobody reads sub-session chats, so a closing
   summary there has no reader. Only the session facing the user writes prose for the user.

6. **Skills are session-local capability bundles, loaded per dispatch** and not bound to any
   topic. A topic is just a stable address plus a chat binding; anonymous sessions are equally
   valid.

Two consequences are worth stating on their own, because they are where most of the value is
and where most of the drift happens:

**A coordinating session does not do the work.** The moment it thinks "this is quick, I'll just
do it", the tree flattens, its context fills with detail it should never have seen, and it stops
being able to coordinate. Manager may not read code at all. The dev coordinator may not edit a
single line, not even a one-character fix. There is no size carve-out, deliberately: a size
carve-out reintroduces a judgment call on every task, which is exactly what kept going wrong.

**Nobody polls.** After dispatching, a session ends its turn. It does not sleep and re-check,
does not loop on a status query, does not keep itself alive to watch a child finish. Results
arrive as real messages that resume the session. This is what keeps a deep tree affordable.

## What is here

```
AGENTS.md              Always loaded by every session
cli-contract.md        The CLI surface the rules depend on, and how to rebind it
skills/
  manager/SKILL.md     Root dispatcher: intent -> todo -> dispatch -> report
  dev/SKILL.md         Coordinator: worktrees, phase dispatch, ownership, branch policy
  plan/SKILL.md        Leaf: read code, scope, write a plan note with verify steps
  impl/SKILL.md        Leaf: implement one sub-task in one worktree
  review/SKILL.md      Leaf: effect-first review against the plan note, approve or request changes
```

The partition rule between the two kinds of file: **AGENTS.md holds what every session needs**
(the tree model, dispatch, trace rules, callback and handoff rules, shared conventions);
**a SKILL.md holds what only that skill needs**. A SKILL.md may tighten an AGENTS.md rule, but
never repeats one.

## Running it

The rules are written against the `y` CLI from this repository, which is what makes them
executable rather than aspirational.

```bash
uv tool install y-agent-cli          # or from source: uv tool install --force -e ./cli
y login                              # a hosted instance, or self-host: ../docs/self-host.md
```

Then put the config in your workspace root (`Y_AGENT_HOME`, see `../docs/cli.md`) and point
the harness at it:

```bash
cp    orchestration/AGENTS.md $Y_AGENT_HOME/AGENTS.md
cp -r orchestration/skills    $Y_AGENT_HOME/.agents/skills

ln -sfn $Y_AGENT_HOME/.agents        ~/.agents          # agent runtime skill discovery
ln -sfn $Y_AGENT_HOME/AGENTS.md      ~/.claude/CLAUDE.md
ln -sfn $Y_AGENT_HOME/.agents/skills ~/.claude/skills
```

The last two lines are Claude Code specific. Any harness that loads one global instructions
file plus per-skill instruction files works the same way; only the paths change.

You also need backends registered with a tier each (`y bot list`), since the rules select a
quality band rather than a model name.

**Not running `y`?** `cli-contract.md` lists the whole surface the rules assume (it is small:
dispatch, task records with an append-only progress log, note association, and a worktree
wrapper) along with what to supply instead. Most of the config survives rebinding unchanged.

## Adapting it

Read these before your first real task:

- **Branch policy** (`skills/dev/SKILL.md`): the shipped version says "determine the target
  branch before creating a worktree, and ask if you cannot tell". If your repos have a fixed
  convention, encode it there so it is settled once.
- **Dispatch targets** (`skills/manager/SKILL.md`): the topic table lists what manager can
  address. Add your own topics as you grow the system.
- **Deployment** (`skills/dev/SKILL.md`): the shipped version pushes and watches a CI gate
  inline. Once that grows past a few commands, split it into a `deploy` leaf skill and dispatch
  it like the others.
- **Timezone**: replace every `<TZ>` placeholder with your IANA zone (`Europe/Berlin`). The
  rules ban bare `date` because the runtime clock is usually UTC and silently writes wrong
  timestamps. Use a literal, not a variable: `Y_AGENT_TIMEZONE` is a CLI config key and does
  not exist in the shell.

## Why the rules read the way they do

Several are stated as hard prohibitions with anti-examples attached. That is deliberate. Each
one marks a failure that actually happened and recurred: a coordinator editing source because
the change looked trivial, two coordinators silently working the same task in parallel, a
session dispatching into another task's trace, an agent filling the queue with follow-up todos
nobody asked for, a chat resumed against a worktree that had already been deleted.

Softly-worded rules did not hold. A flat prohibition plus the concrete failure it came from
does, and it also tells the next reader why the rule exists, which is the part that survives
being copied into someone else's system.

## License

MIT, same as the rest of this repository.
