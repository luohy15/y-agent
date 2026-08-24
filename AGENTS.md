# y-agent

Personal AI agent platform: React web UI + FastAPI backend + async worker, deployed as
AWS Lambda (SAM). Runs Claude Code subprocesses remotely on EC2 over SSH, with
a Telegram bot surface and cross-skill orchestration via trace context.

## Architecture

```
Web (React)  ─┐                                ┌─→ Claude Code subprocess (EC2, SSH)
Telegram Bot ─┼─→ API (FastAPI/Lambda) → SQS → Worker (Lambda) ─┤
CLI (y)      ─┘                                                 └─→ Post-hooks (trace, telegram, todo)

Storage (SQLAlchemy / PostgreSQL) is shared by API / Worker / CLI / admin.
```

## Packages

UV workspace with Python members + one React frontend:

| Package | Purpose | Entry |
|---------|---------|-------|
| **storage** | ORM models, repos, services, DTOs, celery config, global config loader | `src/storage/` |
| **agent** | Claude Code runner, SSH/EC2 pool, tool shims, skills discovery | `src/agent/claude_code.py`, `src/agent/detach.py` |
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
  oxylabs (WeChat / generic pages), yt-dlp (YouTube), Jina AI reader (Twitter/X)

## Notable Subsystems

These are the cross-cutting features to be aware of before touching the code. Each has
entity + controller + service + CLI slices, and most have a web panel.

- **Trace** — every notify / chat / worker step carries a `trace_id` and optional
  `from_chat` / `from_topic`. Participants are registered in `run_chat`; TraceView renders
  the waterfall. `trace_share` makes a trace publicly viewable (optionally with a password).
- **Notify (cross-skill)** — `y chat -m "..."` (fire-and-forget, default top-level
  mode) dispatches a message to a topic (skill) via the single union route
  `POST /api/chat/message`. A request is dispatch-shaped when it carries any of
  `trace_id` / `from_topic` / `from_chat_id` / `topic` / `skill` / `force_new`;
  only dispatch-shaped requests get the `[trace:… to_chat:…]` prefix, root-topic
  rejection, and may create a chat without `chat_id`. Default target is the DM
  (manager). Trace/from meta is attached on send; short-circuited callbacks back
  to root topics never invoke the LLM. `POST /api/chat/notify` was removed
  outright (todo 3167): every CLI install upgrades in lockstep with the API, so
  no compatibility alias was kept.
- **Topic** — every chat has an optional `topic` (named persistent address). The
  conventional root topic is `manager`; the API rejects dispatch callbacks aimed at
  root topics (they are conversations, not function calls).
- **Note** — `note`, `note_todo_relation`, and `note_share` are host-kernel
  tables. A note has a `content_key` file pointer (relative to Y_AGENT_HOME) plus
  JSON `front_matter`; it is used for plan / requirement / decision / journal
  context tied to todos. The host retains all five share routes, the public
  trace-note renderer, `y assoc note`, and the todo 3041 content-path authority.
  Authenticated note browsing/CRUD is the `note` module; see
  `code/y-module/note/README.md`. File rename refuses a path while any live
  note's `content_key` still points at it (via the backend contract's
  `note_list_at_path`); `content_key` is never auto-fixed.
- **Entity (knowledge graph)** — `entity` + `entity_note_relation` + `entity_rss_relation`.
  Web sidebar exposes entities as a first-class panel.
- **English correction** — offline hourly loop over the user's own English chat prose.
  A disabled-by-default routine fires the `english-correction` skill, which reads
  eligible messages from `y english pending`, writes minimal corrections via
  `y english add`, and advances the scan watermark (`user_preference` key
  `english_correction_scan`) with `y english mark-scanned`. Eligibility is
  deterministic Python in `storage/service/english_correction.py` (user role, has an
  `id`, not a `[trace:...]` / `[routine:...]` / bootstrap message, prose, majority
  English); the live chat pipeline is untouched. The diff is computed at read time in
  the web `English` panel, never stored.
- **RSS** — two-stage pipeline: admin schedules feed jobs → worker scrapes feed XML →
  downloader fetches each item's content → storage on S3 (per-activity key). `y rss` CLI
  for feeds + items.
- **Link archive** — EC2 is the single source of truth: `~/luohy15/lifelog/link/<link_id>/{content,summary}.md` is canonical (legacy `links/` paths remain valid until data is moved), `content_key`/`summary_content_key` are paths relative to `~/luohy15/` on EC2, API reads via SSH-cat, and S3 is not used for links.
- **Browser cookies** — `y cookies sync` stores local browser cookies in the API/DB so remote `y link fetch` can pass them to `yt-dlp`.
- **Reminder** — `reminder` table, `/api/reminder`, `y reminder` CLI. Admin Lambda runs
  `check_reminders` on a schedule and pushes matches to Telegram.
- **Telegram** — forum topic binding (`tg_topic`), webhook secret verification,
  markdown → HTML conversion, per-topic routing, root-topic callbacks short-circuited
  at the API layer. Web-only artifact fences are stripped to `[chart]` / `[diagram]`
  / `[svg]` placeholders before Telegram delivery.
- **Artifacts** — assistant markdown fences tagged `mermaid`, `vega-lite`, or
  `artifact-svg` render inline via lazy Mermaid / Vega-Lite / sanitized SVG rendering.
  Plain `svg` fences remain code blocks. Fence dispatch lives in the chat module's
  bubble (and in host `HostMessageView` on public/fallback paths); the renderer
  itself is the host-owned `ArtifactView` / `ArtifactRenderer` leaf on `@y/host`.
- **Hot-loadable modules** — a user-owned, versioned domain with optional API/UI/
  CLI/data parts. Canonical source is only at fixed `code/y-module/<slug>/`
  (`/Users/roy/luohy15/code/y-module`, standalone, independent of `Y_AGENT_HOME`):
  `module.json`, import-free `__init__.py`, optional `api.py`/`cli.py`,
  `ui/index.tsx`, optional `entities/`/`repository/`/`migration/`/`tests/`.
  `y <slug>` loads local source lazily. `y module publish <slug>` builds API+UI
  together, verifies hashes and schema preflight, creates one immutable
  `module_version`, and moves the active pointer. API dispatches
  `/api/module/<slug>/*` via a lazy hash-verified per-version sub-app. Web loader
  keeps the `@y/host` browser contract (**v11**), integrity check, and error
  boundary, and mounts required `panel`, optional `detail`, and optional `shell`
  (centre column; one claimant, lowest slug wins). `module_version.ui_surfaces`
  records claims; only `shell` is enforced from the column. Publish is gated on
  `Y_AGENT_MODULE_MAINTAINER_USER_ID` (fail-closed when unset). Per-version
  `dispatch_scope` defaults to `maintainer`; `authenticated` serves any logged-in
  user. `ui_public` is published but inert (no anonymous backend dispatch). Module
  owns entities/repos/SQL/hand-applied migrations; host owns auth, sessions,
  dependencies, VM execution. `y module schema-sql` prints DDL only; migrations
  stay expand-only while older versions are rollback-reachable. Kernel tables may
  be referenced; another module's tables may not. Shared tables live in
  conventional `common` (vendored at publish). Rollback/activate change code only;
  delete removes deployed metadata/bytes, not source/tables. No worker half:
  deterministic work is `routine` `vm_command`; judgment stays chat dispatch.
  Backend host contract (`agent.module_host`) is **v12**. The tag module owns
  `/api/module/tag/*`, the lazy `y tag` CLI, and the `artifact:tag` panel; the
  host retains the `entity_tag` projection, normalization, carrier sync and
  cleanup, resolver hydration (todo rows carry `updated_at_unix` for client
  sorting), exact-tag filters, coordinated `tag_rename_plan` /
  `tag_rename_apply` (todo 3219), and the `tag.open` navigation adapter.
  Per-module ownership, routes, CLI, and rollback hazards:
  `code/y-module/<slug>/README.md`. Contract: `docs/prd/module-system.md`.
- **API latency monitoring** — an outer pure-ASGI middleware records one bounded,
  privacy-safe event per eligible API attempt, including final streaming duration and
  resolved module child-route identity. Host-owned raw/hourly/daily telemetry is
  rolled up and retained by the worker schedule. The `monitor` module reads it only
  through four configured-maintainer-only `api_latency_*` backend contract v10 queries.
- **Provider service health** — host-owned `provider_status_*` tables normalize
  upstream-reported component and incident state. The exact unauthenticated-but-secret
  Anthropic Statuspage webhook receiver validates the canonical page identity, writes a
  redacted bounded receipt before 2xx, and is reconciled from the official Status API on
  the worker schedule. Bot reads only four maintainer-bound v12 host-contract queries.
  Setup, privacy limits, and manual subscription steps: `docs/provider-status.md`.
- **Image transport** — API image ingestion stores bytes only under
  `/Users/roy/luohy15/assets/images/`: local writes when available, otherwise SSH-push
  to EC2. Workers SSH-fetch local EC2 paths before Telegram delivery. `Message.images`
  may contain EC2 asset paths or deliberate `http(s)://` pass-through URLs, never new
  `s3://` / CDN refs; legacy `s3://` entries from before 2026-05-17 are warning-skipped.
- **Dev worktrees** — `dev_worktree` tracks active coding sessions. `y dev wt add/rm` +
  `y dev commit` handle worktree lifecycle; PID and session state live under
  `/tmp/dev-sessions/<name>/` so multiple worktrees coexist. For a root uv project
  (root `pyproject.toml` + committed `uv.lock`), `y dev wt add` provisions a
  worktree-local `.venv` via `uv sync --locked` after the repository hook and
  refuses to keep a legacy shared `.venv` symlink. Repository hooks must share only
  non-environment assets (credentials, `node_modules`, `migration`, datasets); they
  must not link `.venv`. Existing worktrees created before this behavior need a
  one-time local repair (`rm .venv && uv sync --locked` in the worktree) or
  recreation.
- **Email / Calendar** — multi-account Gmail sync: per-account IMAP app passwords live
  in the `email_account` table (`y email account add/list/rm`), `y email sync-gmail`
  fans out over all registered accounts, and `email.account` tags each row with its
  source address (filterable via `?account=` / `--account` / the EmailList dropdown).
  Full-stack calendar events with timezone-aware filtering. Finance domain views and
  CLI live in the finance module (`code/y-module/finance/README.md`); legacy physical
  column `vm_config.finance_config` remains intentionally for a later contract.

## Agent Runtime

The repo no longer contains an in-process agent loop — the worker shells out.

- **Backends** — `claude_code` (`agent/src/agent/claude_code.py`) is the only agentic CLI
  backend. The other agentic backends (`codex`, `gemini_cli`, `grok_build`, `pi_cli`) were
  removed in todo 2930; `_start_detached` now rejects any backend other than `claude_code`
  with a launch error instead of falling through. The non-agentic inline backends stay:
  `perplexity` (`agent/src/agent/perplexity.py`, the `px` web fact-check), `openai`
  (`agent/src/agent/openai_chat.py`, `POST /api/inline` and `POST /api/link/tldr`), and
  the xAI search pair `xai_web` / `xai_x` (`agent/src/agent/xai_search.py`, the
  `grok-web` / `grok-x` bots) which call xAI's native Responses API with the server-side
  `web_search` / `x_search` tool and return `url_citation` sources as `Message.links`.
  All of them run through one shared `_run_inline` in `worker/runner.py`; the search
  mode is encoded in the backend value, not in a bot_config column. The chat's
  `backend` field is persisted and displayed.
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
- **English learning**: `english_correction`
- **Dev / trace**: `dev_worktree`, `trace_share`
- **API telemetry**: `api_latency_event`, `api_latency_rollup`
- **Provider status**: `provider_status_source`, `provider_status_component`,
  `provider_status_incident`, `provider_status_incident_update`, `provider_status_event`
- **Modules**: `module`, `module_version` (identity + immutable API/UI version rows;
  a version also carries its own `dispatch_scope`, `ui_surfaces`, and `ui_public`, so
  exposure and claimed host slots roll back with the code)
- **Configuration**: `bot_config`, `bot_route_state`, `vm_config` (legacy physical
  column `vm_config.finance_config` is intentionally retained for a later contract).
  `bot_config` and `bot_route_state` are runtime kernel tables on the worker
  dispatch path; bot *management* is module-owned (see `code/y-module/bot/README.md`).
- **Email**: `email`, `email_account`
- **Base / DTO**: `base.py`, `dto.py` (Message, BotConfig, VmConfig structures)

### API Routes (`api/src/api/controller/`)

Grouped by feature area:

- **Auth / core**: `auth.py` (Google OAuth → JWT), `chat.py` (create + SSE streaming +
  stop + steer + trace read-state + public share read + the union send/dispatch
  route `POST /api/chat/message` + host `GET /api/chat/bot-options`; browse
  `list` / `content` and share *creation* are module-owned), `trace.py`
  (listing, share, lookup by chat_id), `git.py` (status/diff/discard, VM
  execution via `agent.vm_command`), `terminal.py` (shell exec)
- **Tasks / notes**: `todo.py`, `reminder.py`, `calendar_event.py`, `note.py`
  (five host share routes and sharing helpers only), `entity.py`,
  `entity_note_relation.py`, `entity_rss_relation.py`
- **Content pipelines**: `link.py`, `link_todo_relation.py`, `rss_feed.py`, `email.py`,
  `english_correction.py`
- **Modules**: `module.py` (list / versions / publish / activate / rollback / enable /
  disable / delete / bundle); module-owned domain routes are dispatched under
  `/api/module/<slug>/*` by `api/module_runtime/` (not a built-in controller per
  domain). Per-module route inventories live in `code/y-module/<slug>/README.md`.
- **Infrastructure**: `telegram.py` (webhook, bind/unbind, routing),
  `provider_status.py` (exact Anthropic Statuspage receiver), `vm_config.py`,
  `dev_worktree.py`, `tg_topic.py`

### Agent (`agent/src/agent/`)
- `claude_code.py` — spawn `claude -p`, stream-json parser
- `detach.py` — shared detached-tmux launch skeleton (`DetachBackendSpec`)
- `perplexity.py`, `openai_chat.py`, `xai_search.py` — inline single-shot (non-agentic)
  backends; `xai_search.py` serves both `xai_web` and `xai_x`
- `config.py` — provider factory, bot/vm config resolution
- `module_host.py` — backend host contract for modules (`BACKEND_CONTRACT_VERSION = 12`:
  `session`, `run_vm_command` with work_dir/stdin, `cli_user_id`, external-table
  protocol, plus request-scoped `bot_config_*`, `chat_*` with optional
  `sort_by`/`sort_order`, `note_list_at_path`, owner-bound `note_*`, `tag_*`
  (including `tag_rename_plan` / `tag_rename_apply`), fixed `api_latency_*`, and
  configured-maintainer-only `provider_status_*` capabilities; `tag_get` todo rows
  include `updated_at_unix`)
- `vm_command.py` — the local/SSH VM execution primitive; `module_host.run_vm_command`
  delegates to it after owner validation, and host `note.py` / `git.py` / `link.py`
  import it directly
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
- `steps/` — RSS feed fetch, link batch download, provider-status reconciliation
- `downloaders/` — SSH wrapper that runs `y link fetch --json` on the user's VM
- `link_downloader.py`, `process_manager.py`
- `handler.py` — Lambda SQS event handler (in worker root)

### Web Frontend (`web/src/`)
- `App.tsx` — multi-panel layout; `host/artifacts.ts` resolves the shell slot
  (logged-out → host; loading → wait; `shell` claimant → module; else
  `ChatFallbackView`)
- Host chat leaves: `HostMessageView.tsx` (≤300 lines), `ChatFallbackView.tsx`,
  `ChatSnapshotView.tsx`, `ShareView.tsx`, right-drawer `ChatList.tsx`. Live
  conversation / Files / Notes panels are module surfaces
  (`code/y-module/{chat,file,note}/README.md`).
- `FileViewer.tsx` — special/public tab shell + module `detail` mount; file
  selection via `file.open` / `file.close` / `file.search` (`utils/fileHost.ts`)
- `TraceView.tsx`, `PublicTraceApp.tsx` (`/t/:shareId`); host `PublicNoteList` for
  logged-out shares
- `host/commands.ts`, runtime-loaded `todo` artifact; `TraceView` stays bundled for
  unauthenticated shares
- `LinkList.tsx`, `EntityList.tsx`, `RssFeedList.tsx`, `DiffViewer.tsx`,
  `GitPanel.tsx`, `CommandPalette.tsx`, `api.ts`, `hooks/useAuth.ts`

### CLI (`cli/src/yagent/`)
- `command_option.py` — root `y` group
- Built-in `commands/`: hybrid `chat` (dispatch/stop/attach stay built-in; browse
  falls through), `todo`, `calendar`, `entity`, `reminder`, `rss`, `link`, `email`,
  `dev`, `image`, `trace`, `english`, `module`, `assoc`/`unassoc`, `init`/`login`/
  `logout`. Domain groups (`y finance`, `y bot`, `y file`, `y note`, …) resolve
  lazily from `code/y-module/<slug>/cli.py`. `y assoc note` stays built-in (3041
  content-path authority). `LazyModuleProxy` uses `module.json` `label` for help.
- `sdk/` — build-time UI SDK (`contract.json`, shims, `build.mjs`, templates);
  `contract.json` is the `@y/host` version source of truth

### Infrastructure
- `template.yaml` — SAM template (SQS, Lambda × 3, S3 + CloudFront, DynamoDB,
  EventBridge schedules for reminders + RSS)
- `samconfig.toml` — deploy config (stack `y-agent`, region `us-east-1`)
- `scripts/deploy.sh`, `deploy-web.sh`

## Auth Flow

Google OAuth → `POST /api/auth/google` (id_token) → JWT (HS256) stored in localStorage.
Middleware validates Bearer token on all routes except `/api/auth/*`, `/api/telegram/*`,
and public share routes (`/api/chat/share/*`, `/api/trace/share/*`).

## Message Flow

1. User enters prompt via web, CLI, or Telegram → `POST /api/chat` (or a variant).
2. API persists the user message, marks `chat.running=True`, and enqueues to SQS
   (Celery filesystem broker in dev).
3. Worker `process_chat` → `run_chat` resolves the target backend
   (`claude_code`, or an inline backend: `perplexity` / `openai` / `xai_web` / `xai_x`),
   sets up trace participants,
   and either:
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

# Deploy backend
./scripts/deploy.sh

# Deploy web
./scripts/deploy-web.sh

# Build web
cd web && npm run build

# Cross-skill notify (--topic / --skill / --chat-id are all independently optional)
y chat -m "..." [--topic <name>] [--skill <name>] [--chat-id <id>] [--bot <name>] [--trace-id ...] [--from-topic ...]
# Interactive REPL — same `y chat` command with -i
y chat -i [-c <id>] [-l] [-b <bot>] [-p "one-off prompt"]

# Dev worktree lifecycle
# Root uv projects (pyproject.toml + uv.lock) get an isolated locked .venv;
# repository post-create hooks must not symlink .venv across checkouts.
y dev wt add <project_path> <name>
y dev wt rm <name>
y dev commit <name> [-m "msg"]

# Modules. Canonical source is code/y-module/<slug>/ (module.json + ui/index.tsx;
# API/CLI/data optional). Domain CLI groups resolve lazily from that source —
# use `y <slug> --help` for the authoritative command list.
y module create <slug> [--label <text>] [--icon <key>] [--force] [--no-register]
y module list
y module versions <slug>
y module schema-sql <slug>  # print DDL only; migrations are maintainer-applied SQL
y module publish <slug> [--no-activate] [--label <text>] [--icon <key>] [-d|--desc <text>]
y module rollback <slug>
y module activate <slug> <version_no>
y module enable <slug> | y module disable <slug>
y module delete <slug> [-y|--yes]
```

## Conventions

- Python: no linter/formatter configured; follow existing style. Minimum 3.11.
- Tests are local-only and untracked. Run `uv run python -m unittest discover -s tests`
  per Python package or `npm run test` in `web`; fresh clones have no test files.
- Frontend: TypeScript strict, TailwindCSS utility classes, Solarized light/dark
  theme. Control patterns (4px radius, `shadow-float`, host classes `.y-check` /
  `.y-field`) are documented in `docs/prd/design-language.md` and the approved
  visual reference `pages/design-3112.html`.
- Storage pattern: Entity (ORM) → Repository (CRUD) → Service (business logic) →
  Controller (API). Do not call repos directly from controllers.
- `chat` stores its DTO as a `json_content` blob **plus** promoted columns, so a
  promoted field is persisted twice. The column is the write target and the only
  side SQL can reach, so every promoted field must be re-read in
  `_entity_to_chat`; a field left out of it makes any manual migration against
  its column a silent no-op (todo 2930 broke 983 chats this way). Before writing
  a migration that rewrites one of these columns, check that the read path
  honours it — and that NULL means what the migration intends it to mean.
- All tool_calls use OpenAI format internally; providers convert to native format.
- Cross-skill communication: `y chat --topic <name> -m "..."` (fire-and-forget,
  the default top-level mode of `y chat`; all flags independently optional) with
  trace context auto-propagation via env vars (`Y_TRACE_ID`, `Y_TOPIC`).
- Global config: `~/.y-agent/config.toml` (preferred) or `.env` loaded from
  `Y_AGENT_HOME`. Key vars: `DATABASE_URL`, `JWT_SECRET_KEY`, `SQS_QUEUE_URL`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `GOOGLE_CLIENT_ID`,
  `Y_AGENT_S3_BUCKET`, `Y_AGENT_TIMEZONE`, `FETCHER_URL`, `ALPHAVANTAGE_API_KEY`,
  `Y_AGENT_MODULE_BUNDLE_DIR` (local module bundle store used when
  `Y_AGENT_S3_BUCKET` is unset; defaults to `~/.y-agent/ui-bundles`),
  `Y_AGENT_MODULE_MAINTAINER_USER_ID` (the public string `user.user_id` of the
  single account that owns every module: publishing always 403s for everyone else,
  and backend dispatch 403s for everyone else unless the active version declares
  `dispatch_scope: authenticated`. Both fail closed when this is unset; required in
  any environment that publishes or dispatches backend modules).
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
- S3 keys and cache keys MUST use public string IDs (e.g. `lifelog/link/<link_id>/...`).
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
- **AGENTS.md** — update opportunistically when a PR introduces a new entity,
  controller, CLI subcommand group, or architectural convention. A quarterly audit
  reconciles the "Notable Subsystems", "Data Models", and "API Routes" sections with
  what's actually in `storage/entity/`, `api/controller/`, and `cli/commands/`. Keep
  numbers vague ("see the directory") to avoid stale counts.
- **README.md** — update when user-visible capability changes (new subsystem, changed
  install flow). Same quarterly audit window as AGENTS.md.

Audit checklist (run quarterly):

- [ ] Entity list matches `storage/src/storage/entity/*.py`?
- [ ] Controller groupings match `api/src/api/controller/*.py`?
- [ ] CLI subcommand list matches `cli/src/yagent/commands/`?
- [ ] `Notable Subsystems` has an entry for every new cross-cutting feature?
- [ ] `Commands` section — every snippet still runs?
- [ ] README `Capabilities` and `Install / Run` still match reality?
