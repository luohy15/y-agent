# y-agent

[![GitHub stars](https://img.shields.io/github/stars/luohy15/y-agent?style=flat-square)](https://github.com/luohy15/y-agent/stargazers)
[![License: MIT](https://img.shields.io/github/license/luohy15/y-agent?style=flat-square)](https://github.com/luohy15/y-agent/blob/main/LICENSE)
[![Last commit](https://img.shields.io/github/last-commit/luohy15/y-agent?style=flat-square)](https://github.com/luohy15/y-agent/commits/main)

A personal AI agent system built on coding agents. It combines a CLI, web UI, API layer, worker processes, and remote coding-agent execution so one person can run a daily-use agent stack with near-zero idle infra cost.

> Renamed from [y-cli](https://luohy15.com/y-cli-introduction). y-cli wrapped model APIs, while y-agent focuses on coding-agent workflows.

## Table of Contents

- [Why y-agent](#why-y-agent)
- [Demo](#demo)
- [Architecture](#architecture)
- [Core features](#core-features)
- [Quick start](#quick-start)
- [Project structure](#project-structure)
- [Deployment](#deployment)
- [Related docs](#related-docs)
- [License](#license)

## Why y-agent

Most agent demos stop at a prompt box. y-agent is opinionated about the full operating loop: task management, long-running execution, trace visibility, remote runtimes, and asynchronous coordination between specialized agents.

## Demo

![y-agent TraceView](https://cdn.luohy15.com/y-agent-demo-1.png)

- Live trace example: <https://yovy.app/t/341d4a>
- Full introduction: <https://luohy15.com/y-agent-introduction>

## Architecture

The system is split into a few focused parts:

- **CLI (`y`)** for todos, notifications, linking, and operator workflows.
- **Web UI** for viewing traces and managing tasks.
- **API + worker services** for orchestration and background processing.
- **Remote coding agents on EC2** for long-running sessions without keeping Lambda alive.
- **Telegram trigger path** for sending work into the system from chat.

## Core features

- **Task management** with shared state between humans and agents.
- **Remote coding agents** that can run on EC2 and hibernate when idle.
- **Session persistence and visualization** through TraceView-style streaming output.
- **Multi-agent collaboration** using skills plus async notifications.
- **Long-running jobs** that keep running outside Lambda time limits.
- **Telegram bot integration** for chat-driven task dispatch.

## Quick start

### Prerequisites

- Python with `uv`
- Node.js and npm
- AWS SAM CLI for backend deployment
- An EC2 host if you want remote coding-agent execution

### Install the CLI

```bash
uv tool install --force -e ./cli
```

### Run the web app locally

```bash
cd web
npm install
npm run dev
```

The Vite app runs on port `5174`.

### Run or deploy the backend

```bash
./scripts/deploy.sh
```

For a preview environment:

```bash
./scripts/deploy-preview.sh <branch-name>
```

## Project structure

```text
admin/      Admin-side service code
agent/      Coding-agent runtime integration
api/        API service
cli/        y-agent CLI
storage/    Storage package
web/        Frontend app
worker/     Async/background worker
scripts/    Deploy and operational scripts
```

## Deployment

- Backend deploy: `./scripts/deploy.sh`
- Web deploy: `./scripts/deploy-web.sh`
- Preview deploy: `./scripts/deploy-preview.sh <branch-name>`
- Preview cleanup: `./scripts/delete-preview.sh <branch-name>`

## Related docs

- [`CLAUDE.md`](./CLAUDE.md) for architecture and contributor notes
- [`docs/lambda-detached-mode.md`](./docs/lambda-detached-mode.md) for detached execution details
- Blog post: <https://luohy15.com/y-agent-introduction>

## License

MIT. See [LICENSE](./LICENSE).
