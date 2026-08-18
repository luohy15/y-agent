---
title: Self-host
category: Operations
order: 3
---

# Self-host

**Server page.** This is the server side: you run the API + worker yourself, either locally for development or deployed to AWS. If you only want to use a hosted instance like `yovy.app` from the CLI or web GUI, you don't need any of this — see [cli.md](cli.md) and [getting-started.md](getting-started.md) instead.

## Prerequisites

- Python 3.11+
- Node 20+
- [UV](https://docs.astral.sh/uv/) package manager
- PostgreSQL (any reachable instance — local or RDS)
- An AWS account if you intend to deploy (Lambda, SQS, S3, CloudFront, EventBridge, DynamoDB)

## Install

UV workspace; everything is one repo.

```bash
git clone https://github.com/luohy15/y-agent.git
cd y-agent

# Install the CLI (also wires the workspace into a tool venv)
uv tool install --force -e ./cli

# Configure (see "Config keys" below)
mkdir -p ~/.y-agent
$EDITOR ~/.y-agent/config.toml

# Init schema once against the database in DATABASE_URL
cd admin && uv run python -c "from handler import lambda_handler; lambda_handler({'action':'init_db'}, None)"
```

## Run (local dev)

Three processes in three terminals:

```bash
# API (port 8001)
cd api && uv run uvicorn api.app:app --reload --port 8001

# Web (port 5174+, auto-selects next free port per worktree)
cd web && npm install && npm run dev

# Worker (Celery filesystem broker locally; SQS in prod)
cd worker && uv run celery -A worker.celery_app worker --loglevel=info
```

## Deploy (AWS)

```bash
./scripts/deploy.sh          # SAM build + deploy backend (Lambda + SQS + EventBridge)
./scripts/deploy-web.sh      # Vite build + S3 sync + CloudFront invalidation
```

SAM stack name and region live in `samconfig.toml` (`y-agent` / `us-east-1` by default). Edit before the first deploy if you want a different name or region.

## Config keys

The full set the API + worker consume. CLI-only keys (e.g. `Y_AGENT_WEB_URL`) live in [cli.md](cli.md).

| Key | Purpose |
|-----|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | HS256 signing key for auth |
| `SQS_QUEUE_URL` | Chat task queue (dev: Celery filesystem broker instead) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Telegram bot surface |
| `GOOGLE_CLIENT_ID` | Google Sign-In on the web frontend |
| `Y_AGENT_S3_BUCKET` | Link / RSS / agent artifact storage |
| `Y_AGENT_CLOUDFRONT_DISTRIBUTION_ID` | CDN invalidation after asset upload |
| `Y_AGENT_TIMEZONE` | IANA tz for calendar / journal / display |
| `FETCHER_URL` | Optional upstream fetcher for link downloads |

## Agent backends

Worker chats run through a configured bot backend. `claude_code` is the only agentic CLI backend: the worker expects `claude` to be installed on the target VM, starts headless runs with `claude -p --output-format stream-json ...`, resumes with `-r <session_id>`, and passes `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` (from the bot config) plus y-agent trace env vars into the subprocess. Different models are different bot configs on the same backend:

```bash
y bot add opus --backend claude_code --model "$MODEL_ID" --base-url "$RELAY_URL" --api-key "$RELAY_KEY" --tier tier1 --yes
```

Non-agentic inline backends also exist, for one-shot request/response features rather than coding sessions: `perplexity` (web fact-check via `y chat --bot px --wait`), `openai` (`POST /api/inline` artifact rewrites, `POST /api/link/tldr` summaries), and `xai_web` / `xai_x` (xAI Responses API search, via `y chat --bot grok-web --wait` / `--bot grok-x --wait`; needs an `xai-…` API key and `--base-url https://api.x.ai/v1`, since the search tools are not reachable through OpenRouter). They run inside the worker with no VM subprocess, no session, and no steer, and a failed call now reports itself as an assistant message instead of leaving the chat silent.

Recurring jobs may pin the backend with `y routine add --backend claude_code ...` / `y routine update --backend claude_code ...`, though leaving it unset is equivalent.

The `codex`, `gemini_cli`, `grok_build`, and `pi_cli` agentic backends were removed (todo 2930). A chat pinned to one of them fails its next launch with an explicit unsupported-backend error; run `migration/2930_drop_non_claude_code_backends.sql` to repoint those rows to `claude_code` (it also nulls `external_id`, since a foreign CLI's session id is not resumable by `claude -p -r`).
