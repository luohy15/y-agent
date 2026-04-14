# y-agent

A personal AI agent system built on coding agents. One person + a coding agent can maintain a complete, daily-use agent system with near-zero infra cost.

> Renamed from [y-cli](https://luohy15.com/y-cli-introduction). y-cli was a wrapper around model APIs; y-agent is a wrapper around coding agents.

## Demo

![y-agent TraceView](https://cdn.luohy15.com/y-agent-demo-1.png)

[Live trace example](https://yovy.app/t/341d4a)

## Core Features

- **Task Management** — `y todo` CLI for creating, updating, and tracking tasks. Humans use the GUI, agents use the CLI, both operate on the same data.

- **Remote Coding Agents** — Run Claude Code directly on AWS EC2. A Lambda SSHes into EC2 to execute commands. EC2 auto-hibernates when idle — no cost when nothing is running.

- **Session Persistence & Visualization** — Claude Code output is streamed via stream-json. A Lambda monitors output, writes to DB, and a web interface displays everything in real time.

- **Multi-Agent Collaboration** — Skills define each agent's role and responsibilities. Agents communicate via async fire-and-forget messaging (`y notify`) with a hub-and-spoke topology — DM dispatches tasks to specialized skills (dev, blog, finance, etc.). Sessions are linked by trace IDs for full-chain visibility in [TraceView](https://yovy.app/t/341d4a).

- **Long-Running Tasks** — Agents run inside tmux detached sessions on EC2. The monitoring layer only tails stdout and writes to DB, so agents can run for hours without hitting Lambda's 15-minute timeout.

- **Telegram Bot** — A Telegram bot listens for messages, triggers Lambda, and Lambda invokes Claude Code via SSH.

## Design Principles

- **Shared context** — Everything lives in one directory on EC2. Humans and agents share the same view via CLI tools and skills.
- **Thin abstraction** — A minimal wrapper on top of coding agents. If something can be wrapped, don't rebuild it.
- **Decoupled execution** — Agent loop runs on EC2; monitoring layer (Lambda) only tails and records, can disconnect/reconnect freely.

## Blog Post

For a detailed introduction, design rationale, and comparisons with other agent orchestration projects, see the [full blog post](https://luohy15.com/y-agent-introduction).

