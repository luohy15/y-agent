# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Weekly release cadence since 0.5.1: one `0.5.x` per ISO week (Mon–Sun), dated to that
week's final day. The current week's in-progress entry sits under `[Unreleased]` until
that Sunday, when it is stamped with the next version and date. Backlog between
2026-02-15 and 2026-04-23 was reconstructed from git history.

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [0.5.11] - 2026-05-03

### Added
- **Recursive session tree alignment (1876)** — `chat.skill` column added, decoupled from `topic`; `chat.role` column dropped (root vs non-root now derives from `topic == 'manager'`). Badges, docs, and comments reframed around the new model.
- **`y notify` merged into top-level `y chat` (1890 / 1891)** — `y chat -m "..."` is now the default fire-and-forget dispatch; `y chat -i` opens the interactive REPL. `--topic` / `--skill` / `--chat-id` are independently optional; bare `y chat -m` creates an anonymous chat. API endpoint moved from `/api/notify` to `/api/chat/notify`.
- **`y chat list --trace-id <id>` (1899)** — list every chat in a trace, sorted chronologically; list response now includes `skill`.
- **TraceView waterfall grouped by skill** — per-session waterfall layout; `desc` rendered as markdown in TraceView and ShareTraceView.
- **Todo read/unread tracking (1882)** — right-click context menu to toggle read/unread; sidebar badge integration.
- **Topic singleton enforcement (1888)** — repository-level guard ensures one active chat per topic; Telegram and notify paths honor it.
- **ChatList items show `skill` instead of `backend` (1903)** — backend remains in chat detail.
- **`y image` CLI** — image generation and tinify sub-commands.
- **`y fetch` CLI (1961)** — new top-level `y fetch` command group with `get` / `click` subcommands and bilibili / oxylabs / youtube fetchers.
- **Routine system (1910)** — `routine` entity + repo/service, REST controller, `y routine` CLI (`add` / `list` / `get` / `update` / `enable` / `disable` / `delete` / `run`), admin Lambda scheduler wired up via EventBridge, and a web `RoutineList` panel with sidebar handoff to the chat list.
- **Landing page redesign (1947)** — dedicated `Landing` component with hero image and demo trace matching README, extracted `GoogleSignInButton`, `DocsView` with sidebar + TOC, `getting-started` doc, and `scripts/build-docs.sh` integrated into web deploy.
- **Avatar / user menu (1948)** — `UserMenu` + `UserInfoModal` replace the inline avatar button in ActivityBar.
- **CodeMirror 6 FileViewer (1933)** — FileViewer rewritten on CodeMirror 6 with language detection and a Solarized theme, plus follow-ups for save concurrency, scroll restoration, and cursor jump.
- **Telegram DM smart routing (1938 / 1939)** — DM messages auto-route to the right topic chat; todo references inside a DM resolve to the topic that owns the todo.
- **Cross-device activity bar order (1930)** — new `user_preference` entity + REST controller; `useUserPreference` syncs ActivityBar layout across devices.
- **FileTree upload (1927)** — drag-and-drop and click-to-upload directly in FileTree.
- **Sidebar filter unification (1923)** — shared filter state between todo and chat lists, with repo-level filtering.
- **Sidebar `running` filter (1926)** — ChatList exposes a "running" filter chip.
- **Click-to-reload chat (1925)** — re-clicking the selected chat re-fetches it.
- **`y pdf` CLI (1924)** — PDF parsing skill + CLI command group.
- **Todo priority submenu (1943)** + **viewport-aware context menu flip (1944)** + **mark-as-read on top of context menu (1922)** — TodoContextMenu polish pass.
- **Todo long-press on touch (1976)** — TodoList opens the context menu on a 500ms long-press on touch devices, with movement/cancel guards so a tap still selects the todo.
- **Sidebar sort (1921)** — repo-level ordering for the sidebar todo list.
- **Blog tab in NoteList (1929)** — separate tab for blog-tagged pages.
- **Chat header skill label (1928)** — chat header shows the skill name.
- README: Architecture section with ASCII session-tree diagram; dev/plan/impl/review skill-per-task example; demo image bumped to v4 with trace URL refresh; copy simplified (1941).

### Changed
- **Manager-topic callback rule made explicit (1887)** — API rejects callbacks aimed at root topics (root sessions are conversations, not function calls).
- **Trace propagation made permissive (1886)** — MessageBubble accepts inherited `trace_id` even when the participant chat predates the trace.
- **API restructure (1891)** — notify endpoints folded into `api/controller/chat.py`; `controller/notify.py` deleted.
- Worker `run_chat` signature: `role` argument removed; skill defaulted from topic when not explicitly set.
- **`y image tinify` writes `<stem>.min<ext>` by default** — original is preserved; `-i/--in-place` restores the old overwrite behavior.
- **API keys loaded from `~/.y-agent/config.toml`** — `y image generate` / `tinify` and `y beancount alphavantage` read `GOOGLE_API_KEY` / `TINIFY_API_KEY` / `ALPHAVANTAGE_API_KEY` from the central config instead of an implicit `.env`.
- **Shared `migration/` across worktrees (1932)** — `worktree/post-create.sh` symlinks `migration` to the main repo so SQL written in a worktree survives `wt rm`.
- **`y dev wt rm` made idempotent (1934)** — safe to re-run when residual state lingers.
- **Link download consolidated into `y fetch get` (1965)** — fetch path handles link download with dry-run support; worker downloaders pruned (`httpx.py` / `oxylabs.py` removed, `router.py` simplified, `link/download.py` retired).
- **README + docs restructure (1959)** — README slimmed down; `docs/capabilities.md`, `docs/cli.md`, `docs/self-host.md` split out for self-host details. Internal `lambda-detached-mode.md` doc dropped from the repo.

### Fixed
- **Telegram routing tightened (worker)** — `_resolve_telegram_target` only DMs the `manager` topic; non-root topics without a `tg_topic` binding no longer fall back to DM.
- **Routine see-chats handoff** — left-side click no longer clears the right-side ChatList's trace filter.
- **ShareTraceView TOC + mobile polish (1958 / 1962)** — TOC scroll behavior, centering layout, and mobile overflow fixes on the public share page.

## [0.5.10] - 2026-04-26

### Added
- **RSS subscription pipeline** — `y rss` CLI, admin-side scheduling, worker scrape with two-stage fetch, unified S3 storage for feed content, and a web feed viewer
- **Entity (knowledge graph)** — new entity table plus note and rss relations, frontend sidebar integration
- **Entity ↔ Link relations** — entity-link relation table; entity viewer lists associated links
- **Shareable trace pages with password protection**
- `y trace unshare` — CLI + UI + backend delete for shared traces
- Link `published_at` extracted during scrape; link list shows title + URL; internal link-click navigation
- Full-path breadcrumbs in the file viewer
- Unified link viewer (centered layout in `links/` markdown files)
- RSS feed fail cooldown and dedup
- **Activity bar overhaul (1848 / 1850 / 1855)** — dedicated reminder slot, unified active/icon styling, reorder, todo checkbox icon
- **Finance F.I.R.E. progress tab (1858 / 1860)** — `y beancount fire-progress` CLI + frontend tab
- **Activity source label (1844)** — surfaces which downloader produced an activity

### Changed
- Immutable `trace_id` — align notify/steer on a single trace identifier
- Restore S3 as backing store for link content (supersedes the 0.5.9 local-filesystem attempt)
- **RSS via oxylabs (1843 / 1845 / 1849 / 1851)** — OpenAI and WeChat feeds now scrape through oxylabs; every RSS item gets an activity row; OpenAI skipped from direct download path
- Finance panel cleanup (1853)

### Fixed
- Share popover bug (1806)
- Note pages workdir resolution
- RSS EventBridge schedule type (`Schedule`, not `ScheduleV2`)
- **Codex resume bug (1834)** — session resume now picks up the right offset
- Activity bar reorder edge cases (1850)

### Removed
- Stale root `todo.md`

## [0.5.9] - 2026-04-19

### Added
- **Note system** — `note` entity + `note_todo_relation`, `content_key` file pointer with front-matter JSON, Notes sidebar panel with Journals/Pages tabs, year/month filters, pages atime display, refresh button
- **Reminder system** — entity, API, admin scheduler, and `y reminder` CLI
- **Steer (mid-conversation messages)** — send user messages to a running Claude Code session; works in detach mode via `tail -f` stdin pipe
- `y chat stop` CLI command
- Auto-restart DM session when context usage exceeds 50% or turn count exceeds 50 (detached path included)
- Chat status + unread tracking with frontend filters; auto-mark-as-read on SSE fetch
- FileViewer edit mode with syntax highlighting, line numbers, and unsaved-edits preview
- Global `~/.y-agent/config.toml` replaces scattered `.env` files
- Notify 400 errors now include actionable hints
- Concurrent DM handling; rejection of DM notify callbacks

### Changed
- `skill` field split into `role (manager/worker) + topic`; skill-manager renamed to `hr`, dev-manager to `cto`
- Replaced S3 with local filesystem for link content storage (reverted in 0.5.10)
- Chat initial load uses REST snapshot instead of SSE replay
- Interrupt watchdog thread added for immediate stop during LLM wait
- Claude `-p` uses `--tools` allowlist (disallows `AskUserQuestion` / `EnterPlanMode`)

### Removed
- AskUserQuestion / EnterPlanMode / WebSearch / WebFetch / Agent display code from MessageBubble
- Auto-ack and Telegram notification on DM session restart

### Fixed
- Steer detach variable ordering, Lambda handoff dedup, result wait window
- Lease release for cancelled tasks before SQS continuation
- Stale-chat overwrite in notify after `append_message`

## [0.5.8] - 2026-04-12

### Added
- **Codex CLI as a second coding backend** — `y notify --backend codex|claude_code`, backend field surfaced in chat detail/list/trace APIs
- **Lambda worker detached process management** with event loop; SSH connection pool for monitoring detached processes
- **Context usage telemetry** — token usage displayed on chat sessions, detailed tooltip breakdown, auto-restart DM session over 50% context or 50 turns
- Todo pin/unpin, backend pagination + search, right-click context menu
- Worktree lifecycle management — todo linkage, server state tracking, GC
- Command palette (⌘K)
- Calendar auto-scroll to current time + smart week persistence
- Google Analytics on the web frontend
- Bilibili subtitle download

### Changed
- Normalized `api_type` to `claude_code` (underscore), display consolidated in bot selector

### Removed
- Agent loop, codex backend loop, and local subprocess runner — claude_code/codex subprocesses are the only execution paths

### Fixed
- Lambda continuation when tail tasks are already reaped; lease release on pause
- Detached mode routing, tail leak, offset save on deadline
- Relative markdown link resolution in chat view
- Codex tool call display: strip shell wrapper, match results

## [0.5.7] - 2026-04-05

### Added
- **Personal Information Hub (Phase 1)** — link download/archiving via SSH/opencli, Twitter/X post + article support
- Link preview panel with markdown content fetching; raw/preview toggle in FileViewer
- "Add to link" button for `pages/` files in FileViewer
- Desktop header bar with panel toggles; bottom terminal panel
- Activity-level `download_status` for URLs with query parameters
- `FETCHER_URL` and `Y_AGENT_S3_BUCKET` surfaced as SAM parameters
- **ID Convention** section added to CLAUDE.md

### Changed
- Link relations use `activity_id` instead of `link_id`; S3 upload moved to worker
- Activity bar reorder — terminal first, then todo and links
- Link viewer turned into a sidebar mode with FileViewer preview

### Fixed
- DM callback resolves to the latest session instead of stale `from_chat`
- Balance-sheet date filter made cumulative, not period-only
- Finance API maps remote command failures to 502 instead of 500

## [0.5.6] - 2026-03-29

### Added
- **Shareable trace pages** — todo trace waterfall + chat viewer, TOC navigation, trace prefix badges on user messages, unified badge color/style system
- Navigate to a trace page from `#id` clicks in todo / chat / trace lists
- Collapsible tablet panels — chat list, TOC, ChatToc, scroll-to-bottom
- `y dev commit` supports a dynamic target branch
- **Telegram DM callback short-circuit** at API layer — replies without invoking the LLM
- Portfolio tracker for finance
- AskUserQuestion tool display in ChatView
- Diff viewer scrollbar change markers; per-file discard improvements in git panel

### Changed
- Unified todo status management; `completed_at` cleared on deactivate
- Simplified notify flow; `send_chat_message` moved to service layer
- Removed `channel_id` from chat in favor of skill-based Telegram routing
- Base font size bumped to 110%
- TraceView drops inline messages; skill labels clickable to open the chat

### Fixed
- ShareTraceView defaults to earliest chat; mobile waterfall shows only start/end labels
- Trace participant resolution: prefer participant chat_id, then skill lookup, then create new
- `work_dir` validation on resume
- NotifyResponse `trace_id` made optional (prevents 500s)

## [0.5.5] - 2026-03-22

### Added
- **Trace system (phase 1)** — `trace_id` as a first-class concept across notify / chat / worker, TraceView with waterfall + messages, mobile trace list, trace-id badges with copy
- **Notify hub** — default skill is DM, trace/from meta line on notify messages, Telegram push routed to the target skill's topic, notify supports `chat_id` for callback/resume
- **EC2 auto-wake** with `last_up` tracking and `ssh_exec` integration — replaces Sprites VM runner
- **Telegram session management** — `/clear` command, forum topic support
- Chat search with a dedicated `search_text` column
- DevViewer, process summary, ChatView TOC, todo history, inline skill content

### Changed
- Trace context passed via env vars instead of message content
- Trace decoupled from notify — participants registered in `run_chat`
- One trace segment per message round (simplified segmentation)
- Dev workflow: remove `chat dev`, add commit flag, use registry in hooks
- Replace `sleep(10)` with an SSH connectivity check after EC2 wake

### Fixed
- `wt rm` leaving residual directories under `code/`
- Notify user-id propagation; CLI reinstall quirks; process leak in monitor
- TOC jump, notify prefix, DiffViewer full-file rendering

## [0.5.4] - 2026-03-15

### Added
- **`y dev` commands with worktree support + todo-linked sessions**, plan and implement modes
- Auto commit and PR submission after dev chat completes; worktree post-create symlink script
- **Telegram bot** — webhook with secret verification, bind/unbind, reply post-hook, markdown → HTML conversion
- Telegram photo support — download, store as base64, materialize on target machine for Claude Code
- **Kanban board view** with drag-and-drop; due date display; search filter
- Git panel with diff viewer (`@pierre/diffs`) and per-file discard
- Chat search + get CLI commands
- Terminal `clear` command + `Ctrl+L` shortcut
- Mobile VM/dir buttons, `y image splice` command
- GitHub secrets helper script

### Changed
- Bumped minimum Python to 3.11
- Post-completion hooks (commit/PR, plan save) moved from CLI to worker
- File directory follows chat selection; VM selector + dir toggle moved to left activity bar
- Permission system removed — simplified CLI chat with a streaming client
- Clear chat when VM changes instead of disabling the selector

### Removed
- Public `/set-webhook` endpoint (security)

### Fixed
- Markdown table placeholder bug in Telegram HTML converter
- TodoDetail modal ergonomics — remove close button, auto-size textareas, cap history scroll

## [0.5.3] - 2026-03-08

### Added
- **Finance** — beancount balance sheet and income statement
- **Investment portfolio management** — market data, holdings, position tracking, investment plan
- **Email management** with Gmail sync
- **Link management** with Chrome bookmark sync
- **Web terminal** feature
- Markdown preview and enhanced file search in the web UI

### Removed
- **Sprites VM** support — replaced by EC2 + SSH architecture

### Fixed
- Batch link sync duplicate timestamp collision within the same batch
- Batch link sync switched to bulk queries (removes per-item lookups)
- App file detection uses `endsWith` to support `apps/` subdirectory

## [0.5.2] - 2026-03-01

### Added
- File upload endpoint and upload button in FileTree; loading states for move/upload
- `Y_AGENT_TIMEZONE` env var for calendar timezone-aware filtering
- Claude Code history import with incremental sync (skip unchanged files via mtime)
- Headless login (`--token`, `--no-browser`)
- Clickable file paths in chat messages to open in the file editor
- `/cle` alias for the clear command
- VPC configuration for Lambda to reach RDS

### Changed
- **CLI `todo` and `calendar` commands use the API** instead of direct DB access
- Switched from `psycopg2` to `psycopg` v3
- Timezone conversion moved from server to CLI side
- API entrypoint renamed `main.py` → `app.py`; port 8001
- `.env` loaded consistently from `Y_AGENT_HOME`
- Chat list refresh, work_dir display, and todo sorting improvements
- Don't steal input focus when the user has text selected

### Fixed
- Todo list sort order for completed and unfiltered views
- Treat empty `due_date` as NULL in todo sort

## [0.5.1] - 2026-02-22

### Added
- **Todo system** — full-stack CRUD, TodoViewer with inline expanded rows, ESC to close, completed filter tab
- **Calendar event management** across the full stack, with current-time ticker
- **SSH exec tool** (paramiko-based) — subprocess stdout limit fix
- **Claude Code worker backend** with session resume support
- **Branch preview deployments** — per-branch SAM stacks, git tags, `list-previews` script
- File upload staging, work_dir tracking + mismatch handling
- File tree refresh, locate-in-tree / copy-path, VSCode excludes for file filtering
- File search powered by `git ls-files` (respects `.gitignore`), wrap-around navigation
- 3-level message filtering (process/detail toggle buttons)
- Landing page with demo and sign-in; share copy feedback
- Right-click context menu (copy path, skip non-printable entries)
- Text wrapping in tool-call displays; running-cursor indicator
- `selected_message_id` field on Chat for message tree branching
- VM selector always visible, even with a single default VM
- Git worktree setup guide in CLAUDE.md
- Auto-resize textarea for mobile chat input; larger touch targets on mobile

### Changed
- Timestamps standardized to UTC ISO 8601 with `unix_timestamp` fields
- Chat layout preferences persisted in localStorage
- Sidebar hamburger replaced with a folder icon showing the work directory
- Input bar hidden during run; always pinned to bottom
- Logo click resets selected chat
- Skip SAM deploy for web-only changes; skip deploy workflow for markdown-only changes

### Removed
- Preview GitHub Actions workflows (now deploy locally)

### Fixed
- CloudFront CNAME error when DomainName is empty
- IME composition triggering message submit on Enter
- Share button clipboard copy on Safari
- Mobile paste, mobile chat-list drawer visibility
- Process interruption: `kill()` for local, `channel.close()` for SSH
- Horizontal overflow in chat view and code blocks
- Calendar `todo_id` type switched from int FK to string external ID

## [0.5.0] - 2026-02-15

### Added
- **Web UI**: Full React web frontend with Solarized theme, markdown rendering, and CLI-style messages
- **Serverless backend**: AWS SAM-based API (Lambda) and Celery task queue worker
- **Google OAuth authentication** for multi-user support
- **Agent package**: Autonomous tool-use loop with `LoopResult` and unified CLI/worker runners
- **Skill discovery**: Auto-detect and load agent skills
- **Remote VM execution** via Sprites API backend with configurable `VmBackend` parameter
- **Chat sharing**: Public share view with DB-backed deduplication and `/share/:shareId` route
- **Tool approval system**: Per-tool-call approval modal, auto-approve toggle, deny-with-message, and tool status display
- **Chat interrupt/stop** functionality across full stack (CLI, API, and web)
- **SQLite local storage** and D1 export command
- **Intent analyzer** for smart routing and dependency cleanup
- **One-off prompt mode** for non-interactive usage
- **Responsive mobile UI**: Hamburger menu sidebar, dvh viewport units, zoom prevention on input focus
- **Running cursor indicator** in message list during agent execution
- **User isolation**: `user_id` support in bot config for multi-user environments
- Perplexity links display support
- GitHub link icon in Header and ShareView

### Changed
- **Project renamed** to y-agent
- **Major restructure**: Multi-package workspace with `cli`, `storage`, `admin`, `api`, `agent`, and `worker` packages
- Replaced DynamoDB cache with DB-backed chat state and Celery task queue
- Consolidated API routes under `/api` prefix
- Refactored user management and service layer abstractions
- Refactored tool approval flow with separate rejected/cancelled backfill modes
- Refactored `MessageList` into shared component with improved tool display
- Improved web deployment pipeline with SWR replacing manual polling
- Auto-allow read-only bash commands for smoother agent experience
- Moved Google sign-in button from header to chat view landing page
- Made header logo clickable to start new chat

### Removed
- MCP daemon and deprecated features
- VPC config from Lambda functions (simplified networking)

## [0.4.0] - 2025-06-09

### Added
- Cloudflare D1 storage integration as a new storage_type option
- Chat import command for migrating between storage types
- Enhanced Message model with parent_id field for message relationships
- Enhanced Chat model with new fields for content tracking and message selection
- Documentation for Cloudflare D1 setup and usage

### Changed
- Replaced Cloudflare KV/R2 storage with more robust Cloudflare D1 database solution
- Updated repository factory to support D1 database
- Refactored chat service HTML generation for better TOC integration
- Improved list_chats to support more advanced filtering options

### Removed
- Cloudflare Worker backup functionality (replaced by D1's built-in reliability)
- Legacy Cloudflare KV/R2 storage implementation

## [0.3.13] - 2025-03-25

### Added
- Cloudflare storage integration for chat data with KV and R2 support
- MCP daemon for persistent MCP server connections between sessions
- Prompt configuration management system with customizable prompts
- Asynchronous repository operations for improved performance
- Repository factory pattern for flexible storage selection
- Cloudflare worker script for automated backups
- Detailed documentation for new features

### Changed
- Refactored chat repository into modular structure
- Updated chat manager to support async repository operations
- Enhanced message models with MCP tool execution information
- Improved logging with loguru integration
- Updated system architecture documentation
- Optimized display manager for tool execution representation

## [0.3.10] - 2025-02-25

### Added
- Topia Orchestration Provider support
- Memory bank documentation structure
- Project rules documentation (.clinerules)
- Immediate chat ID generation for better session management
- New utility function for ID generation

### Changed
- Updated default model from claude-3.5-sonnet to claude-3.7-sonnet
- Improved README with new features and demo visuals
- Enhanced display manager to better handle structured content
- Updated chat service to support pre-generated chat IDs

## [0.3.7] - 2025-02-13

### Changed
- Use bot name as provider if not provider info

## [0.3.6] - 2025-02-13

### Fixed
- Fixed reasoning content output

## [0.3.5] - 2025-02-13

### Fixed
- Fixed bot config print_speed

## [0.3.4] - 2025-02-13

### Fixed
- Fixed infinite recursion bug in bot configuration service when ensuring default config exists

## [0.3.3] - 2025-02-12

### Changed
- Refactored MCP server configuration system
- Renamed mcp_setting package to mcp_server for better clarity
- Simplified MCP server configuration structure

## [0.3.2] - 2025-02-11

### Added
- New visual documentation with interactive chat and multiple bot screenshots

### Changed
- Refactored ChatApp initialization to use BotConfig for better configuration management
- Improved README documentation with visual examples

## [0.3.1] - 2025-02-11

### Changed
- Modified bot configuration defaults handling for better flexibility

## [0.3.0] - 2025-02-11

### Added
- Bot configuration system
- MCP server settings integration with bot configs
- New CLI commands for managing bot configurations (`bot add`, `bot list`, `bot delete`)
- Improved chat list filtering by model and provider
- Dynamic terminal width handling for better display

### Changed
- Major project restructuring with dedicated packages for bot, chat, and CLI components
- Moved CLI components to dedicated cli package
- Updated configuration system to use bot configs
- Improved error handling and user feedback
- Enhanced system prompt with current time

## [0.2.5] - 2025-02-08

### Added
- Smooth output print with rate-limited streaming (30 chars/sec)

## [0.2.4] - 2025-02-08

### Fixed
- Fix list -k error
- Fix scrolling error using vertical_overflow="visible"

## [0.2.3] - 2025-02-06

### Added
- Support deepseek-r1 reasoning content
- Add model, provider info

## [0.2.2] - 2025-02-06

### Fixed
- Prevent saving system message

## [0.2.0] - 2025-02-06

### Added
- Add MCP client support for integrating with Model Context Protocol servers
- Add cache_control for prompt caching

## [0.1.1] - 2025-02-05

### Fixed
- Fix fcntl compatible issue

### Added
- Support copy command when chat: use 0 for entire message, 1-n for specific code blocks
- Support OpenRouter indexed db file import
