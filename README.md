# y-agent

A personal AI agent system built on coding agents. One person + a coding agent can maintain a complete, daily-use agent system with near-zero infra cost.

> Renamed from [y-cli](https://luohy15.com/y-cli-introduction). y-cli was a wrapper around model APIs; y-agent is a wrapper around coding agents.

## Demo

![y-agent TraceView](https://cdn.luohy15.com/y-agent-demo-1.png)

[Live trace example](https://yovy.app/t/341d4a) — every cross-skill call chain is a shareable, public trace.

## Core Features

- **Task Management** — `y todo` CLI for creating, updating, and tracking tasks. Humans use the GUI, agents use the CLI, both operate on the same data.

- **Remote Coding Agents** — Run Claude Code (or Codex) directly on AWS EC2. A Lambda SSHes into EC2 to execute commands. EC2 auto-hibernates when idle — no cost when nothing is running.

- **Session Persistence & Visualization** — Claude Code output is streamed via stream-json. A Lambda monitors output, writes to DB, and a web interface displays everything in real time.

- **Multi-Agent Collaboration** — Skills define each agent's role and responsibilities. Agents communicate via async fire-and-forget messaging (`y notify`) with a hub-and-spoke topology — the manager dispatches tasks to specialized skills (dev, blog, finance, etc.). Sessions are linked by trace IDs for full-chain visibility in [TraceView](https://yovy.app/t/341d4a).

- **Long-Running Tasks** — Agents run inside tmux detached sessions on EC2. The monitoring layer only tails stdout and writes to DB, so agents can run for hours without hitting Lambda's 15-minute timeout. When a Lambda deadline is near, the worker hands off via SQS to continue seamlessly.

- **Telegram Bot** — A Telegram bot listens for messages, triggers Lambda, and Lambda invokes Claude Code via SSH. Forum topics route each skill to its own channel.

## Capabilities

A running y-agent deployment ships these user-facing features out of the box:

- **Todo** — full-stack CRUD, kanban board, pagination, pin, search, history.
- **Note** — structured notes with `content_key` file pointers and JSON front-matter; Journals + Pages sidebar panels.
- **Entity (knowledge graph)** — link notes and RSS feeds to people, projects, or any concept; browse from a dedicated sidebar.
- **Calendar** — timezone-aware events, current-time ticker, week-aware persistence.
- **Reminder** — time-based reminders delivered via Telegram, optionally attached to a todo or event.
- **Link archive** — Chrome bookmark sync; Twitter / X, Bilibili, WeChat article download; in-app markdown preview.
- **RSS** — feed subscription with a two-stage scrape pipeline; per-item content stored on S3; unified viewer.
- **Finance** — beancount balance sheet, income statement, portfolio tracker.
- **Email** — Gmail sync for lightweight inbox review inside the UI.
- **Trace + Share** — every cross-skill call chain has a waterfall TraceView, shareable as a public page (optionally with password).
- **Dev worktrees** — `y dev` CLI + web panel to create/remove worktrees per task, auto-commit, dynamic merge target.
- **Telegram bot** — webhook with secret verification, forum topic routing, markdown → HTML conversion, DM callback short-circuit.
- **Web terminal** — shell access scoped to the current VM / work_dir.
- **Git panel** — file-level status, diff viewer with change markers, per-file discard.
- **File viewer / editor** — syntax highlighting, line numbers, unsaved-edits preview, click-to-open relative links.

## Install / Run

y-agent is a UV workspace. You need Python 3.11+, Node 20+, the UV package manager, and an AWS account for the deployed version. Local dev runs entirely on your machine.

```bash
# Install the CLI (wires the workspace into a tool venv)
uv tool install --force -e ./cli

# Configure
mkdir -p ~/.y-agent
$EDITOR ~/.y-agent/config.toml        # DATABASE_URL, JWT_SECRET_KEY, TELEGRAM_BOT_TOKEN,
                                       # GOOGLE_CLIENT_ID, SQS_QUEUE_URL, Y_AGENT_S3_BUCKET,
                                       # Y_AGENT_TIMEZONE, FETCHER_URL, ...

# Init schema (once)
cd admin && uv run python -c "from handler import lambda_handler; lambda_handler({'action':'init_db'}, None)"

# Dev API server (port 8001)
cd api && uv run uvicorn api.app:app --reload --port 8001

# Dev web (port 5174+, auto-selects next free port per worktree)
cd web && npm install && npm run dev

# Dev worker (Celery filesystem broker)
cd worker && uv run celery -A worker.celery_app worker --loglevel=info
```

### Deploy (AWS)

```bash
./scripts/deploy.sh          # SAM build + deploy backend (Lambda + SQS + EventBridge)
./scripts/deploy-web.sh      # Vite build + S3 sync + CloudFront invalidation

# Branch previews
./scripts/deploy-preview.sh
./scripts/list-previews.sh
./scripts/delete-preview.sh <branch>
```

### Minimal config keys

| Key | Purpose |
|-----|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | HS256 signing key for auth |
| `SQS_QUEUE_URL` | Chat task queue (dev: Celery filesystem broker instead) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Telegram bot surface |
| `GOOGLE_CLIENT_ID` | Google Sign-In |
| `Y_AGENT_S3_BUCKET` | Link + RSS content storage |
| `Y_AGENT_TIMEZONE` | IANA tz for calendar/journal/display |
| `FETCHER_URL` | Optional upstream fetcher for link downloads |

## Design Principles

- **Shared context** — Everything lives in one directory on EC2. Humans and agents share the same view via CLI tools and skills.
- **Thin abstraction** — A minimal wrapper on top of coding agents. If something can be wrapped, don't rebuild it.
- **Decoupled execution** — Agent subprocesses run on EC2; the monitoring layer (Lambda) only tails and records, and can disconnect/reconnect freely.

## Blog Post

For a detailed introduction, design rationale, and comparisons with other agent orchestration projects, see the [full blog post](https://luohy15.com/y-agent-introduction).
