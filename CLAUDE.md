# y-agent

Personal AI agent platform: React web UI + FastAPI backend + async worker, deployed as
AWS Lambda (SAM). Runs Claude Code / Codex subprocesses remotely on EC2 over SSH, with
a Telegram bot surface and cross-skill orchestration via trace context.

## Architecture

```
Web (React)  ─┐                                ┌─→ Claude Code / Codex subprocess (EC2, SSH)
Telegram Bot ─┼─→ API (FastAPI/Lambda) → SQS → Worker (Lambda) ─┤
CLI (y)      ─┘                                                 └─→ Post-hooks (trace, telegram, todo)

Storage (SQLAlchemy / PostgreSQL) is shared by API / Worker / CLI / admin.
```

## Packages

UV workspace with Python members + one React frontend:

| Package | Purpose | Entry |
|---------|---------|-------|
| **storage** | ORM models, repos, services, DTOs, celery config, global config loader | `src/storage/` |
| **agent** | Claude Code / Codex runners, SSH/EC2 pool, tool shims, skills discovery | `src/agent/claude_code.py`, `src/agent/codex.py` |
| **api** | FastAPI REST + SSE, JWT auth, controllers for each feature | `src/api/app.py` (port 8001) |
| **worker** | Celery/SQS task consumer, runs agent subprocesses, post-hooks, RSS pipeline | `src/worker/runner.py` |
| **cli** | Click CLI (`y` command), all feature subcommands | `src/yagent/command_option.py` |
| **admin** | Lambda handler for DB init + scheduled jobs (reminders, RSS) | `handler.py` |
| **web** | React 19 + Vite + TailwindCSS SPA | `src/main.tsx` (port 5174) |

Other top-level dirs: `scripts/` (deploy, DNS, IAM), `template.yaml` / `samconfig.toml`
(SAM), `worktree/post-create.sh` (symlink shared files into new dev worktrees).

## Tech Stack

- **Python 3.11+**, UV workspace, Hatchling build
- **FastAPI** + Uvicorn + SSE (sse-starlette) + Lambda Web Adapter (response streaming)
- **SQLAlchemy 2.0** + PostgreSQL (psycopg v3), DynamoDB (per-process lease cache)
- **Celery 5.3** (filesystem broker local, SQS in prod)
- **React 19** + React Router 7 + Vite 7 + TailwindCSS 4 + SWR
- **AWS SAM**: Lambda (API / Worker / Admin), SQS, S3 + CloudFront (web + link/RSS content),
  EventBridge schedules (reminders, RSS), DynamoDB
- **Integrations**: Telegram Bot API, Google OAuth, SSH/Paramiko, EC2 lifecycle (boto3),
  opencli (Twitter/X, Bilibili), oxylabs (WeChat)

## Notable Subsystems

These are the cross-cutting features to be aware of before touching the code. Each has
entity + controller + service + CLI slices, and most have a web panel.

- **Trace** — every notify / chat / worker step carries a `trace_id` and optional
  `from_chat` / `from_topic`. Participants are registered in `run_chat`; TraceView renders
  the waterfall. `trace_share` makes a trace publicly viewable (optionally with a password).
- **Notify (cross-skill)** — `/api/chat/notify` and `y chat -m "..."` (fire-and-forget,
  default top-level mode) dispatch a message to a topic (skill). Default target is
  the DM (manager). Trace/from meta is attached on send; short-circuited callbacks
  back to root topics never invoke the LLM.
- **Topic** — every chat has an optional `topic` (named persistent address). The
  conventional root topic is `manager`; the API rejects notify callbacks aimed at
  root topics (they are conversations, not function calls).
- **Note** — `note` + `note_todo_relation` tables. A note has a `content_key` file
  pointer (relative to Y_AGENT_HOME) plus JSON `front_matter`; used for plan /
  requirement / decision / journal context tied to todos.
- **Entity (knowledge graph)** — `entity` + `entity_note_relation` + `entity_rss_relation`.
  Web sidebar exposes entities as a first-class panel.
- **RSS** — two-stage pipeline: admin schedules feed jobs → worker scrapes feed XML →
  downloader fetches each item's content → storage on S3 (per-activity key). `y rss` CLI
  for feeds + items.
- **Link archive** — Chrome bookmark sync, Twitter/X and Bilibili downloads, WeChat via
  oxylabs. Each link becomes an `activity_id` with content stored on S3; the FileViewer
  handles raw/preview toggling and "Add to link" from `pages/`.
- **Reminder** — `reminder` table, `/api/reminder`, `y reminder` CLI. Admin Lambda runs
  `check_reminders` on a schedule and pushes matches to Telegram.
- **Telegram** — forum topic binding (`tg_topic`), webhook secret verification,
  markdown → HTML conversion, per-topic routing, root-topic callbacks short-circuited
  at the API layer.
- **Dev worktrees** — `dev_worktree` tracks active coding sessions. `y dev wt add/rm` +
  `y dev commit` handle worktree lifecycle; PID and session state live under
  `/tmp/dev-sessions/<name>/` so multiple worktrees coexist.
- **Finance / Email / Calendar** — beancount balance sheet / income statement /
  portfolio tracker; Gmail sync; full-stack calendar events with timezone-aware filtering.

## Agent Runtime

The repo no longer contains an in-process agent loop — the worker shells out.

- **Backends** — `agent/src/agent/claude_code.py` (Claude Code) and
  `agent/src/agent/codex.py` (Codex CLI). `y chat --backend codex|claude_code -m "..."`
  picks one; default is `claude_code`. The chat's `backend` field is persisted and
  displayed.
- **Detached execution on EC2** — subprocesses run inside `tmux` on the VM. The worker
  SSHes in, tails stdout, and streams JSON events back. `agent/ssh_pool.py` reuses SSH
  connections across monitor passes; `agent/ec2_wake.py` auto-wakes the instance.
- **Lambda hand-off** — since Lambda caps at ~15 min, the worker releases its lease
  before the deadline and re-enqueues itself via SQS; the next invocation picks up the
  existing tail offset. `poll_loop.py` unifies the steer / interrupt polling cadence.
- **Steer** — mid-conversation user messages are delivered to a running session. In
  detach mode they go through a `tail -f` stdin pipe. `y chat stop` is the explicit
  interrupt path; an interrupt watchdog thread also fires during LLM waits.
- **Context monitor** — per-chat token usage is tracked; when a root-topic session
  crosses 50% context or 50 turns, it auto-restarts in a fresh chat with a short
  summary.
- **Tools** — `agent/tools/` holds shims for `bash`, `file_read/write/edit`, `local_exec`,
  `ssh_exec`. These are surfaced to Claude Code as JSON tool descriptors.
- **Skills** — discovered from `~/.agents/skills/`; each skill is a directory with
  `SKILL.md`.

## Key Files

### Data Models (`storage/src/storage/entity/`)

By category (all entities get a Repository in `repository/` and a Service in `service/`;
exceptions noted):

- **Identity / chat**: `user`, `chat`, `tg_topic`
- **Tasks / time**: `todo`, `calendar_event`, `reminder`
- **Notes / knowledge graph**: `note`, `note_todo_relation`, `entity`,
  `entity_note_relation`, `entity_rss_relation`
- **Link / RSS**: `link`, `link_todo_relation`, `rss_feed`, `pipeline_lock` (RSS scrape
  coordination, no service)
- **Dev / trace**: `dev_worktree`, `trace_share`
- **Configuration**: `bot_config`, `vm_config`
- **Email**: `email`
- **Base / DTO**: `base.py`, `dto.py` (Message, BotConfig, VmConfig structures)

### API Routes (`api/src/api/controller/`)

Grouped by feature area:

- **Auth / core**: `auth.py` (Google OAuth → JWT), `chat.py` (CRUD + SSE streaming +
  share + stop + steer + cross-skill notify dispatch), `trace.py` (listing,
  share, lookup by chat_id), `file.py` (list/read/search/upload, local + SSH),
  `git.py` (status/diff/discard), `terminal.py` (shell exec)
- **Tasks / notes**: `todo.py`, `reminder.py`, `calendar_event.py`, `note.py`,
  `note_todo_relation.py`, `entity.py`, `entity_note_relation.py`, `entity_rss_relation.py`
- **Content pipelines**: `link.py`, `link_todo_relation.py`, `rss_feed.py`, `email.py`,
  `finance.py`
- **Infrastructure**: `telegram.py` (webhook, bind/unbind, routing), `vm_config.py`,
  `bot_config.py`, `dev_worktree.py`, `tg_topic.py`

### Agent (`agent/src/agent/`)
- `claude_code.py` — spawn `claude -p`, stream-json parser
- `codex.py` — spawn Codex CLI
- `config.py` — provider factory, bot/vm config resolution
- `ssh_pool.py`, `ec2_wake.py` — SSH connection reuse, EC2 wake-on-demand
- `poll_loop.py` — steer / interrupt polling
- `tool_base.py`, `tools/` — tool descriptors (bash, file_{read,write,edit}, local_exec,
  ssh_exec)
- `skills.py` (if present under agent root) — discover local skills

### Worker (`worker/src/worker/`)
- `runner.py` — `run_chat()` is the main entry: loads chat, resolves config, starts
  detached subprocess, runs post-hooks (telegram reply, plan → todo note, trace
  registration). `_start_detached` handles Lambda lease + handoff.
- `tasks.py` — Celery task `process_chat()`
- `monitor.py` — tails detached process stdout, flushes to DB
- `steps/` — RSS feed fetch, link batch download
- `downloaders/` — HTTP (httpx), oxylabs, SSH (opencli)
- `link_downloader.py`, `process_manager.py`
- `handler.py` — Lambda SQS event handler (in worker root)

### Web Frontend (`web/src/`)
- `App.tsx` — multi-panel layout (sidebar / file viewer / chat / terminal / trace)
- `components/ChatView.tsx` — SSE-based real-time chat with tool call display, steer,
  context usage tooltip
- `components/TraceView.tsx`, `ShareTraceView.tsx` — waterfall, share page
- `components/FileTree.tsx`, `FileViewer.tsx` — lazy tree + edit mode (syntax
  highlighting, line numbers)
- `components/TodoList.tsx`, `TodoViewer.tsx` — kanban + pagination + pin
- `components/NoteList.tsx`, `LinkList.tsx`, `EntityList.tsx`, `RssFeedList.tsx` —
  subsystem panels
- `components/DiffViewer.tsx`, `GitPanel.tsx` — git status + diff
- `components/CommandPalette.tsx` — ⌘K palette
- `api.ts` — `authFetch()` wrapper, base URL from `VITE_API_URL`
- `hooks/useAuth.ts` — Google Sign-In + JWT

### CLI (`cli/src/yagent/`)
- `command_option.py` — root `y` command group
- `commands/` subcommand groups: `chat`, `todo`, `calendar`, `note`, `entity`,
  `reminder`, `rss`, `link`, `email`, `dev`, `beancount`, `image`, `bot`, `trace`,
  `assoc` / `unassoc`, plus `init` / `login` / `logout`

### Infrastructure
- `template.yaml` — SAM template (SQS, Lambda × 3, S3 + CloudFront, DynamoDB,
  EventBridge schedules for reminders + RSS)
- `samconfig.toml` — deploy config (stack `y-agent`, region `us-east-1`)
- `scripts/deploy.sh`, `deploy-web.sh`, `deploy-preview.sh`, `list-previews.sh`,
  `delete-preview.sh`

## Auth Flow

Google OAuth → `POST /api/auth/google` (id_token) → JWT (HS256) stored in localStorage.
Middleware validates Bearer token on all routes except `/api/auth/*`, `/api/telegram/*`,
and public share routes (`/api/chat/share/*`, `/api/trace/share/*`).

## Message Flow

1. User enters prompt via web, CLI, or Telegram → `POST /api/chat` (or a variant).
2. API persists the user message, marks `chat.running=True`, and enqueues to SQS
   (Celery filesystem broker in dev).
3. Worker `process_chat` → `run_chat` resolves the target backend
   (`claude_code` / `codex`), sets up trace participants, and either:
   - starts a detached subprocess on EC2 (long tasks), or
   - runs the subprocess inline with streaming output.
4. Subprocess stdout is streamed JSON; monitor writes each chunk as a `Message` to DB.
5. Steer messages (mid-conversation) and interrupts are polled from the chat row.
6. On completion, worker runs post-hooks: Telegram reply, plan-to-note hook, trace
   registration. If a Lambda deadline is near, the worker hands off via SQS to continue.
7. Frontend loads the initial snapshot via REST and then subscribes to SSE
   (`GET /api/chat/messages?chat_id=&last_index=`).

## Commands

```bash
# Install CLI (links the workspace into a tool venv)
uv tool install --force -e ./cli

# Dev API server
cd api && uv run uvicorn api.app:app --reload --port 8001

# Dev web
cd web && npm install && npm run dev   # port 5174+, picks the next free port per worktree

# Dev worker (Celery filesystem broker)
cd worker && uv run celery -A worker.celery_app worker --loglevel=info

# Deploy backend (main or preview by branch)
./scripts/deploy.sh

# Deploy web
./scripts/deploy-web.sh

# Branch preview deploys
./scripts/deploy-preview.sh
./scripts/list-previews.sh
./scripts/delete-preview.sh <branch>

# Build web
cd web && npm run build

# Cross-skill notify (--topic / --skill / --chat-id are all independently optional)
y chat -m "..." [--topic <name>] [--skill <name>] [--chat-id <id>] [--backend claude_code|codex] [--trace-id ...] [--from-topic ...]
# Interactive REPL — same `y chat` command with -i
y chat -i [-c <id>] [-l] [-b <bot>] [-p "one-off prompt"]

# Dev worktree lifecycle
y dev wt add <project_path> <name>
y dev wt rm <name>
y dev commit <name> [-m "msg"]
```

## Conventions

- Python: no linter/formatter configured; follow existing style. Minimum 3.11.
- Frontend: TypeScript strict, TailwindCSS utility classes, Solarized dark theme.
- Storage pattern: Entity (ORM) → Repository (CRUD) → Service (business logic) →
  Controller (API). Do not call repos directly from controllers.
- All tool_calls use OpenAI format internally; providers convert to native format.
- Cross-skill communication: `y chat --topic <name> -m "..."` (fire-and-forget,
  the default top-level mode of `y chat`; all flags independently optional) with
  trace context auto-propagation via env vars (`Y_TRACE_ID`, `Y_TOPIC`).
- Global config: `~/.y-agent/config.toml` (preferred) or `.env` loaded from
  `Y_AGENT_HOME`. Key vars: `DATABASE_URL`, `JWT_SECRET_KEY`, `SQS_QUEUE_URL`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `GOOGLE_CLIENT_ID`,
  `Y_AGENT_S3_BUCKET`, `Y_AGENT_TIMEZONE`, `FETCHER_URL`.
- DB migrations: only generate the SQL — the maintainer runs it manually via `psql`.
  Do not wire up automatic migrations. Place new SQL under `migration/` (e.g.
  `migration/<todo_id>_<short_desc>.sql`). The directory is gitignored and shared
  across worktrees: the main repo owns the real `migration/`, and `worktree/post-create.sh`
  symlinks `migration` → `/Users/roy/luohy15/code/y-agent/migration` in each new
  worktree, so SQL written inside a worktree survives `y dev wt rm`. For an existing
  worktree that predates this setup, run
  `ln -sfn /Users/roy/luohy15/code/y-agent/migration migration` from the worktree
  root once.

### ID Convention

Every entity has two kinds of identifier:

| Kind | Type | Where to use |
|------|------|-------------|
| **Internal ID** | Integer (autoincrement PK) | DB foreign keys, ORM joins, internal queries only |
| **Public ID** | String/UUID (`chat_id`, `todo_id`, `user_id`, `activity_id`, `trace_id`, etc.) | API requests/responses, JWT payloads, S3 keys, cache keys, URLs, logs |

**Rules:**
- API controllers MUST NOT expose integer `id` or integer FK fields (e.g. `user_id` as int) in request/response payloads or URL path params.
- JWT tokens MUST use the string `user_id` (from `UserEntity.user_id`), not the integer PK.
- S3 keys and cache keys MUST use public string IDs (e.g. `links/<activity_id>/...`).
- DTOs returned to the API layer MUST omit internal integer IDs; use dedicated response dicts or filter fields in the controller.
- Entities without a public string ID (`BotConfig`, `VmConfig`, `TgTopic`, `PipelineLock`) should be addressed by their natural key (e.g. `name`, `group_id + topic_name`) rather than exposing the integer PK.

## Maintenance

These three docs drift fast. Baseline cadence since 2026-04-23:

- **CHANGELOG.md** — one `0.5.x` entry per ISO week (Mon–Sun), dated to that week's
  final day. Mid-week edits land under `## [Unreleased]`; on Sunday, swap that header
  for `## [<next version>] - <YYYY-MM-DD>` and start a fresh `[Unreleased]` block on
  the next edit. Run `git log --since="1 week ago" --no-merges --oneline`, pick 3–8
  user-facing highlights, group under Added / Changed / Fixed / Removed, commit as
  `docs(changelog): weekly update <YYYY-MM-DD>`. A weekly reminder handles the
  trigger.
- **CLAUDE.md** — update opportunistically when a PR introduces a new entity,
  controller, CLI subcommand group, or architectural convention. A quarterly audit
  reconciles the "Notable Subsystems", "Data Models", and "API Routes" sections with
  what's actually in `storage/entity/`, `api/controller/`, and `cli/commands/`. Keep
  numbers vague ("see the directory") to avoid stale counts.
- **README.md** — update when user-visible capability changes (new subsystem, changed
  install flow). Same quarterly audit window as CLAUDE.md.

Audit checklist (run quarterly):

- [ ] Entity list matches `storage/src/storage/entity/*.py`?
- [ ] Controller groupings match `api/src/api/controller/*.py`?
- [ ] CLI subcommand list matches `cli/src/yagent/commands/`?
- [ ] `Notable Subsystems` has an entry for every new cross-cutting feature?
- [ ] `Commands` section — every snippet still runs?
- [ ] README `Capabilities` and `Install / Run` still match reality?
