---
title: Self-host
category: Operations
order: 3
---

# Self-host

This page is for running your own y-agent API + worker, either locally for development or deployed to AWS. If you only want to use the CLI against an existing instance like `yovy.app`, you don't need any of this — see [cli.md](cli.md) instead.

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

# Branch previews
./scripts/deploy-preview.sh
./scripts/list-previews.sh
./scripts/delete-preview.sh <branch>
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

## Internals

For how the worker hands off long-running chats across Lambda invocations, see [lambda-detached-mode.md](lambda-detached-mode.md).
