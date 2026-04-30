# y-agent

A personal AI agent system built on top of coding agents.

> Renamed from [y-cli](https://luohy15.com/y-cli-introduction). y-cli wrapped model APIs; y-agent wraps coding agents.

## Demo

![y-agent TraceView](https://cdn.luohy15.com/y-agent-demo-4.png)

A real trace: https://yovy.app/t/6fc5c4

---

Coding agents like Claude Code / Codex are great for code, but code is only part of my daily life. I also have ledgers, calendars, todos, notes, emails. I want the agent to handle those too.

Three things came up while extending a coding agent into a personal agent system:

1. How to give the agent context
2. How to keep the agent always-on
3. How to orchestrate multiple agents

### Context

Same data for me and for the agent. Files go through `read` / `write` / `edit`. Anything I'd reach for a GUI to do, the agent reaches for a CLI — it's already happy in Bash. Rule: whatever I can do in the GUI, the agent can do via CLI. The underlying file or DB row is the same.

### Always-on

I don't want to carry a laptop or open a terminal to use it. Coding agents run on a remote VM (EC2) inside `tmux`; a tail process parses their output into the database, so the web UI can chat with them directly. A Telegram bot covers mobile input. EC2 auto-hibernates when idle, so cost is near zero when nothing is running.

### Orchestration

One session usually can't handle the whole thing — requests have to be routed to the right session. Claude Code ships sub-agents, but I wanted that layer outside, so sub-agent chats stay in my own DB and I can steer them mid-run.

```
   user        ┌──────────────────┐
   input ────► │  skill: manager  │   dispatch only,
        │     └────────┬──────────┘   no execution
        │              │   y chat --skill dev -m "..."
        │              ▼
        │     ┌──────────────────┐
        ├───► │  skill: dev      │   coordinator,
        │     │                  │   runs lower-level skill sessions
        │     └──┬──────┬──────┬─┘
        │        │      │      │   y chat --skill {plan,impl,review}
        │        ▼      ▼      ▼
        │     ┌──────┐ ┌──────┐ ┌────────┐
        └───► │ plan │ │ impl │ │ review │   anonymous, ephemeral;
              └──────┘ └──────┘ └────────┘   skill loaded per dispatch
```

A `trace_id` (= `todo_id` when the task is tracked) threads the whole tree, so [TraceView](https://yovy.app/t/6fc5c4) renders the chain as a waterfall.

## Docs

Two paths, depending on whether you want to run your own instance:

**Use the hosted instance** — `y login` against `yovy.app` and go.

- [docs/cli.md](docs/cli.md) — install the CLI, sign in, common commands.
- [docs/getting-started.md](docs/getting-started.md) — what the web UI looks like after sign-in.
- [docs/capabilities.md](docs/capabilities.md) — what subsystems ship in a running deployment.

**Self-host** — run the API + worker yourself.

- [docs/self-host.md](docs/self-host.md) — prerequisites, install, run, deploy, config keys.
- [docs/lambda-detached-mode.md](docs/lambda-detached-mode.md) — how long chats hand off across Lambda invocations.

## Blog Post

Longer write-up, design rationale, and comparisons: [full blog post](https://luohy15.com/y-agent-introduction).

[CHANGELOG](CHANGELOG.md) tracks weekly updates.
