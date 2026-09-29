# y-agent

## One Entry Point, a Cloud Workspace

Hand over a task from your phone, tablet, or desktop. Let the agent work in the same cloud workspace, and come back when there's a decision to make or work to check.

![Web and Telegram connect to y-agent; Claude Code works with EC2 files and RDS data, while a self-hosted relay connects to Claude, GPT, and Grok.](https://cdn.luohy15.com/blog/images/my-ai-dev-setup.png)

I keep the workspace on EC2 and use y-agent as one entry point. Telegram is another way into the same system, not a separate mobile agent. Code, notes, task records, and results stay in my own workspace rather than belonging to a particular chat window. Switching devices doesn't mean introducing the project all over again.

Read the full story: [My AI Dev Setup: One Entry Point, a Cloud Workspace](https://luohy15.com/2026/09/27/my-ai-dev-setup).

## How it fits together

These are the layers of my deployment, not five services in a linear pipeline:

| Layer | Role | My setup |
| --- | --- | --- |
| Client | Hand over tasks and read results | y-agent web UI, with Telegram as a chat input interface |
| Memory | Keep project context and task state | Files on EC2; structured records in PostgreSQL on RDS |
| Runtime | Read code, edit files, run commands | Claude Code on EC2 |
| Gateway | Connect and forward model requests | A self-hosted relay: my fork of [claude-relay-service](https://github.com/luohy15/claude-relay-service) |
| Models | Supply model capabilities | Claude / GPT / Grok |

Files and database records are read and written as work needs them. They aren't a stop every model request passes through. The runtime and model source are separate choices: **Claude Code is the only agentic CLI backend in this repository.** Other model sources depend on the configured gateway, interface compatibility, and provider subscription terms; a subscription isn't a general-purpose API entitlement. The relay is a separate service, not bundled with y-agent. Model context still leaves the workspace for inference.

Under the hood, a React web UI and Telegram feed a FastAPI API. The API queues work through SQS to a worker, which starts Claude Code over SSH in EC2 `tmux` sessions and streams results back into chat records. API, worker, and admin jobs deploy with AWS SAM/Lambda; PostgreSQL holds structured state. Local development uses Celery with a filesystem broker instead of SQS.

## What it does

- **One workspace beyond code.** Work with todos, notes, links, calendars, email, and domain modules through the web and `y` CLI. The agent uses the same files and records, rather than a separate copy of your context.
- **Task-linked context.** A todo connects discussions, plans, progress, and reviews. A new session reads that material instead of needing the entire previous conversation in its prompt.
- **Orchestration outside the runtime.** One session can finish a small task; larger tasks can split into planning, implementation, and review sessions, each loading the skill it needs. A shared `trace_id` connects the tree, and sub-task chats remain visible and steerable.
- **An inbox for your turn.** `awaiting` marks work needing a decision, authorization, or acceptance check. Publication approval is a separate boundary from implementation and review.
- **Extensible surfaces.** Hot-loadable modules can add UI, API, CLI, and data. Chat can render Mermaid diagrams, Vega-Lite charts, and sanitized SVG artifacts. See the [module contract](docs/prd/module-system.md).

See a [real task trace](https://yovy.app/t/6fc5c4) or browse the [capability reference](docs/capabilities.md).

## Get started

### Use an existing instance

Open its web UI and sign in. For terminal access, install [uv](https://docs.astral.sh/uv/) and Python 3.11+, then:

```bash
git clone https://github.com/luohy15/y-agent.git
cd y-agent
uv tool install --force -e ./cli
y login
```

The CLI defaults to `https://yovy.app`. Set `Y_AGENT_WEB_URL` to use another instance. Signing in is not a self-hosted installation; you don't need a local API or worker to use an existing server. See the [web guide](docs/getting-started.md) and [CLI guide](docs/cli.md).

### Run your own

This is a personal, self-hosted system, not a one-command appliance. You'll need Python 3.11+, uv, Node.js 20+, PostgreSQL, and a configured execution VM with Claude Code, SSH, and tmux. AWS deployment adds the Lambda/SQS infrastructure and related services; model access and the optional relay are configured separately.

Follow the [self-hosting guide](docs/self-host.md) for configuration, local API/web/worker commands, and AWS deployment. Domain modules live in a separate y-module repository; their source and published bundles are not included in this checkout. Backups, permissions, provider access, and infrastructure maintenance remain yours to manage.

## More

- [CHANGELOG](CHANGELOG.md): release history.
- [Earlier y-agent introduction](https://luohy15.com/y-agent-introduction): background and design rationale.
- Formerly [y-cli](https://luohy15.com/y-cli-introduction): y-cli wrapped model APIs; y-agent wraps coding agents.
