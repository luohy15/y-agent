# y-agent

Personal AI agent platform: React web UI + FastAPI backend + async worker, deployed as AWS Lambda (SAM). Supports multi-LLM (Anthropic/OpenAI), remote SSH execution on EC2, Telegram bot, and cross-skill orchestration via trace context.

## Architecture

```
Web (React) → API (FastAPI/Lambda) → SQS → Worker (Lambda)
                                              ├→ Agent Loop (LLM + tools)
                                              └→ Claude Code subprocess
Storage layer (SQLAlchemy/PostgreSQL) shared across API/Worker/CLI
```

## Packages

UV workspace with 6 Python members + 1 JS frontend:

| Package | Purpose | Entry |
|---------|---------|-------|
| **storage** | ORM models, repos, services, DTOs, celery config | `src/storage/` |
| **agent** | LLM loop, providers (Anthropic/OpenAI), tools (bash/file/SSH), skills, claude_code runner | `src/agent/loop.py` |
| **api** | FastAPI REST + SSE, JWT auth, 17 controllers | `src/api/app.py` (port 8001) |
| **worker** | Celery/SQS task consumer, runs agent loop | `src/worker/runner.py` |
| **cli** | Click CLI (`y` command), chat/todo/calendar/dev/beancount/notify | `src/yagent/command_option.py` |
| **admin** | Lambda handler for DB init/migrations | `handler.py` |
| **web** | React 19 + Vite + TailwindCSS SPA | `src/main.tsx` (port 5174) |

Other dirs: `scripts/` (deploy/DNS/IAM shell scripts), `control/` (Celery broker state), `worktree/` (dev worktree tracking).

## Tech Stack

- **Python 3.11+**, UV workspace, Hatchling build
- **FastAPI** + Uvicorn + SSE (sse-starlette) + Lambda Web Adapter (response streaming)
- **SQLAlchemy 2.0** + PostgreSQL (psycopg3), DynamoDB (job cache)
- **Celery 5.3** (filesystem broker local, SQS in prod)
- **React 19** + React Router 7 + Vite 7 + TailwindCSS 4 + SWR
- **AWS SAM**: Lambda (API/Worker/Admin), SQS, S3+CloudFront (web), DynamoDB
- **Integrations**: Telegram bot, Google OAuth, SSH/Paramiko, EC2 lifecycle (boto3)

## Key Files

### Data Models
- `storage/src/storage/entity/*.py` — 11 SQLAlchemy models (user, chat, todo, calendar_event, bot_config, vm_config, dev_worktree, email, link, tg_topic)
- `storage/src/storage/dto/*.py` — DTOs (Message with role/content/tool_calls, BotConfig, VmConfig)
- `storage/src/storage/repository/*.py` — Data access layer (10 repos)
- `storage/src/storage/service/*.py` — Business logic (10 services)

### API Routes (api/src/api/controller/)
- `chat.py` — CRUD, SSE streaming (`/api/chat/messages`), share, stop
- `auth.py` — Google OAuth → JWT
- `todo.py` — Todo CRUD + status transitions
- `notify.py` — Cross-skill messaging with trace context
- `trace.py` — Trace listing and chat lookup
- `file.py` — File list/read/search/upload (local + SSH)
- `git.py` — Status/diff/discard
- `terminal.py` — Shell command execution
- `telegram.py` — Webhook handler, bind/unbind, message routing
- `calendar_event.py`, `email.py`, `link.py`, `finance.py`, `vm_config.py`, `bot_config.py`, `dev_worktree.py`, `tg_topic.py`

### Agent Core
- `agent/src/agent/loop.py` — Main loop: LLM call → tool execution → repeat
- `agent/src/agent/claude_code.py` — Spawn `claude -p` subprocess, stream-json parser
- `agent/src/agent/provider/` — Anthropic/OpenAI format converters
- `agent/src/agent/tools/` — bash, file_read, file_write, file_edit, local_exec, ssh_exec
- `agent/src/agent/skills.py` — Discover skills from `~/.agents/skills/`
- `agent/src/agent/config.py` — Provider factory, bot/vm config resolution

### Worker
- `worker/src/worker/runner.py` — `run_chat()`: agent loop execution, post-hooks (git commit+merge, todo), trace context
- `worker/src/worker/tasks.py` — Celery task `process_chat()`
- `worker/handler.py` — Lambda SQS event handler

### Web Frontend (web/src/)
- `App.tsx` — Multi-panel layout (sidebar, file viewer, chat/terminal/trace)
- `components/ChatView.tsx` — SSE-based real-time chat with tool call display
- `components/FileTree.tsx` — Lazy-loaded file browser with drag-drop
- `components/TraceView.tsx` — Skill execution timeline/waterfall
- `api.ts` — `authFetch()` wrapper, base URL from `VITE_API_URL`
- `hooks/useAuth.ts` — Google Sign-In + JWT

### Infrastructure
- `template.yaml` — SAM template (SQS, Lambda×3, S3+CloudFront, DynamoDB)
- `samconfig.toml` — Deploy config (stack: y-agent, region: us-east-1)
- `scripts/deploy.sh` — SAM build+deploy (main or preview by branch)
- `scripts/deploy-web.sh` — Vite build → S3 sync → CloudFront invalidation

## Auth Flow

Google OAuth → `POST /api/auth/google` (id_token) → JWT (HS256) stored in localStorage. Middleware validates Bearer token on all routes except `/api/auth/*`, `/api/telegram/*`, public share.

## Message Flow

1. User sends prompt → `POST /api/chat` or `/api/chat/message`
2. API enqueues to SQS (prod) or Celery (dev) → `process_chat` task
3. Worker runs agent loop or claude_code subprocess
4. Messages saved to DB incrementally
5. Frontend polls via SSE (`GET /api/chat/messages?chat_id=&last_index=`)

## Commands

```bash
# Install CLI
uv tool install --force -e ./cli

# Dev API server
cd api && uv run uvicorn api.app:app --reload --port 8001

# Dev web
cd web && npm install && npm run dev  # port 5174

# Dev worker (Celery filesystem broker)
cd worker && uv run celery -A worker.celery_app worker --loglevel=info

# Deploy backend
./scripts/deploy.sh

# Deploy web
./scripts/deploy-web.sh

# Build web
cd web && npm run build

# Preview deploy (branch-based)
./scripts/deploy-preview.sh
./scripts/list-previews.sh
./scripts/delete-preview.sh <branch>
```

## Conventions

- Python: no linter/formatter configured, follow existing style
- Frontend: TypeScript strict, TailwindCSS utility classes, Solarized dark theme
- Storage pattern: Entity (ORM) → Repository (CRUD) → Service (business logic) → Controller (API)
- All tool_calls use OpenAI format internally; providers convert to native format
- Cross-skill communication: `y notify <skill> -m "msg"` with trace context auto-propagation
- Env vars: `DATABASE_URL`, `JWT_SECRET_KEY`, `SQS_QUEUE_URL`, `TELEGRAM_BOT_TOKEN`, `GOOGLE_CLIENT_ID`

### ID Convention

Every entity has two kinds of identifier:

| Kind | Type | Where to use |
|------|------|-------------|
| **Internal ID** | Integer (autoincrement PK) | DB foreign keys, ORM joins, internal queries only |
| **Public ID** | String/UUID (`chat_id`, `todo_id`, `user_id`, etc.) | API requests/responses, JWT payloads, S3 keys, cache keys, URLs, logs |

**Rules:**
- API controllers MUST NOT expose integer `id` or integer FK fields (e.g. `user_id` as int) in request/response payloads or URL path params
- JWT tokens MUST use the string `user_id` (from UserEntity.user_id), not the integer PK
- S3 keys and cache keys MUST use public string IDs
- DTOs returned to the API layer MUST omit internal integer IDs; use dedicated response dicts or filter fields in the controller
- Entities without a public string ID (BotConfig, VmConfig, TgTopic) should be addressed by their natural key (e.g. `name`, `group_id+topic_name`) rather than exposing the integer PK
