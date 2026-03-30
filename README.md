# y-agent

A personal AI agent platform with multi-skill orchestration, task management, and parallel execution.

## Core Features

- **Agent Communication** — `y notify` enables cross-skill message passing and task dispatch. Skills communicate asynchronously with full trace context propagation, so you can chain workflows across multiple agents while keeping a clear execution trail.

- **Task Management** — `y todo` CLI provides a complete task lifecycle: create, prioritize, activate, and finish tasks. Track progress across parallel workstreams with status transitions (`pending → active → completed`) and priority levels.

- **Parallel Execution** — Multiple skills run concurrently on independent tasks. A dev-manager can spin up several worktrees and dispatch work to separate dev agents simultaneously, each with its own context and trace lineage.

- **Remote Development** — Connect to Claude Code running on AWS EC2 as a frontend for remote cloud-based development.

- **Multi-LLM Support** — Pluggable providers for Anthropic and OpenAI models with a unified internal message format.

- **Web UI + CLI** — React SPA with real-time SSE streaming, file browser, and trace timeline; plus a full-featured CLI (`y`) for terminal-first workflows.

