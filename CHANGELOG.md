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

## [0.5.18] - 2026-06-28

### Added
- **claude_tui backend (2514)** — new tmux-backed Claude Code TUI backend that drives the interactive `claude` TUI on EC2 over the subscription login (no `base_url` / API key), parallel to the existing `claude -p` path.
- **Claude `/usage` scrape (2515)** — `y claude usage` CLI plus a `claude-usage-check` alert skill that scrapes the claude_tui `/usage` TUI for current limit-window usage and notifies via Telegram above a threshold.
- **Daily Claude usage persistence (2588)** — daily Claude (CRS) limit-window usage is persisted into a `model_usage_daily` table.
- **Codex per-bot credentials (2590)** — the codex backend honors per-bot `base_url` / `api_key` via `-c` provider injection.
- **Calendar editor save hotkey (2585)** — cmd+s / ctrl+s saves in the calendar event editor.
- **Claude status RSS monitor (2529)** — worker monitor that polls Claude's status RSS feed and pushes Telegram notifications on new incidents.
- **Auto-generated showcase screenshots (2541)** — `/showcase` skill generates panel screenshots via Playwright, with chat added as a 6th showcased capability.
- **Calendar event view / add in web (2572)** — CalendarViewer surfaces a shared view/edit/add form with a 30-minute time-picker dropdown, in-modal event view/add, pointer cursor, and an optimistic preview while saving.
- **Bot credentials in web panel (2567)** — bot list and detail views surface each bot's `base_url` plus a masked `api_key`.
- **Bot per-model usage view (2606, 2607, 2610, 2611, 2615, 2619, 2620, 2622)** — new bot-page model-usage view with Live | Over-time tabs at daily granularity, wired to `model_usage_daily`; a Live time-range selector with independent Live vs Over-time range storage (routed through finance's shared time grammar); a single/multi-pie metric breakdown (Requests/Tokens/Cost toggle, CRS-style bottom legend) plus a 3-card totals summary and a consolidated Live-totals header strip; the Live table's `provider` column is replaced with a sort-relative `%` column; per-column totals row, independent clickable-column sorting, a refresh button that triggers a CRS sync, and an over-time history table that opens scrolled to the most-recent columns. Pie chart polished: totals moved into the donut center via HTML overlay, legend sorted by share descending and wrapped 3-per-row below the chart, plus tooltip animation/z-index and box-sizing fixes.
- **CRS usage sync + backfill (2608)** — sync CRS model-usage as a global per-model aggregate across all `cr_` keys, plus `y usage backfill` for dated-window historical sync.
- **Calendar schedule list (2613)** — a Google-Calendar-style schedule list (one event per row, grouped by day) in the main left sidebar (ScheduleList), showing all future events.
- **Finance large-transactions panel (2614)** — finance-mode left panel with quick-stats and large-transactions endpoints, filtered to Income/Expenses events (internal transfers excluded), sized by Income/Expenses posting magnitude, with a USD 100 threshold and full-display wrapping for long entries; entries are classified as income / expense / investment with distinct colors and signed amounts.
- **FileViewer Ctrl+number tab switching (2630)** — Ctrl+1–8 select FileViewer tabs by position and Ctrl+9 jumps to the last tab.
- **FileViewer download for all file types (2605)** — download is now allowed for all file types, not just markdown.

### Changed
- **MCP disabled on agent launch (2549, 2550)** — both the `claude -p` and claude_tui launch paths now disable MCP (`--strict-mcp-config`), and claude_tui launches are restricted to a tool allowlist.
- **Docs refresh (2541)** — capabilities / CLI / getting-started docs refreshed with a clearer client-vs-server framing.

### Fixed
- **Mermaid artifact rendering (2551)** — mermaid artifacts no longer render as an empty box (relaxed the over-strict `sanitizeSvg` DOMPurify config), and scroll jitter / snap-to-top is fixed via `scrollbar-gutter: stable`, a render-once cache, and a stick-to-bottom guard on the chat scroll container.
- **HTML comments in markdown** — HTML comments are now hidden when rendering markdown.
- **claude_tui idle-turn finalization** — stuck idle turns in claude_tui sessions now finalize instead of hanging.
- **claude_tui default backend fallback (2518)** — worker default agent backend now falls back to `claude_tui` instead of `claude -p`.
- **claude_tui `/usage` scrape scrollback (2515)** — capture full tmux scrollback so the windows block is reliably read.
- **ChatList badge filter guard (2517)** — badge filters no-op under `hideFilters` so the trace sidebar can't get stuck on one topic.
- **Calendar click-to-add slot (2570)** — click-to-add now uses a Google-Calendar-style 30-minute slot anchored at the cursor, snapping the start past any overlapping event in the clicked hour while still allowing overlap.
- **Note list flicker on open (2573)** — opening a note no longer flickers the list; the loading UI is gated on `isLoading` only.
- **pi_cli backend option (2568)** — `pi_cli` is now selectable in the bot list and detail backend selector.
- **Finance to-date semantics (2592)** — YTD / MTD / QTD ranges now include today so same-day entries show, and the net-worth-over-time chart applies the realtime overlay so the current period matches the table.
- **Calendar editor delete confirmation (2586)** — deleting an event from the editor no longer happens without confirmation.
- **Link list load-more (2624)** — `load more` now appends without a full reload (preserving scroll) and dedupes by `activity_id` to stop duplicate keys, scroll reset, and repeated rows.
- **Chat scroll-to-bottom button (2626)** — the scroll-to-bottom button now jumps instantly instead of smooth-scrolling.

### Removed

## [0.5.17] - 2026-06-14

### Added
- **Inline calendar event editing (2446)** — CalendarViewer now supports editing, creating, and deleting calendar events inline.
- **Calendar drag interactions (2450, 2451)** — drag an event's top/bottom border to resize its time range, drag the whole event to move it, with a live time label shown during the drag.
- **Calendar Today button (2454)** — the Today button now scrolls the time grid to the current hour.
- **Export chat messages as long-image (2487)** — export selected chat messages as a Solarized long-image, with a single delivery channel per platform (desktop download / mobile share sheet) and a yovy.app footer.
- **Gmail-style email viewing (2489, 2490, 2491)** — two-pane email layout (list in sidebar, single-email detail viewer), thread grouping (list shows thread head + count badge; detail stacks the thread chronologically), a collapsed conversation view that folds all-but-first/latest messages into one-line rows with click-to-expand, a recipient-details dropdown (Gmail-style triangle popover with from/to/cc/date/subject/mailed-by metadata), and Gmail-style recipient/date lines ("to me, Aria"; weekday-prefixed dates).
- **HTML email bodies (2498)** — EmailViewer renders sanitized HTML email bodies in a shadow DOM (DOMPurify, light background), with a unified plain-text snippet for list and collapsed rows.
- **Multi-account Gmail sync (2499)** — per-account IMAP app passwords in a new `email_account` table, `y email sync-gmail` fans out over all registered accounts, account management via API/CLI/web, and per-account filtering in list views.
- **Calendar events in trace view (2501)** — trace info API now includes associated calendar events; TraceView renders them in a collapsible Calendar Events section, with click-to-navigate to the calendar panel at the event's date/time.
- **Chat-list routine & skill filters (2485, 2488)** — filter the chat list by triggering routine (name) and skill, with click-to-filter trace/topic/routine/skill badges, wired end-to-end across storage/API/CLI/web.
- **Chat-less todo click opens fileview + trace (2467)** — clicking a todo with no chat now switches to the file view and shows its trace.
- **`y chat --wait/--wait-timeout` (2472)** — generic synchronous one-shot dispatch flags for `y chat`.
- **`y link` fetch channel + source filter (2460, 2463)** — `y link fetch` is now recorded as a third visit channel (`source=fetch`), and `y link list` gains a `--source` filter (sync/rss/fetch).
- **CI test workflow (2484)** — added `test.yml` running per-package Python unittest + web vitest on push/PR, with new coverage for trace/notify, CLI dispatch trace-flags, post-hooks, the claude_code stream converter, and telegram webhook routing.
- **FileTree new-file button (2505)** — a new-file button next to upload in the FileTree toolbar: enter a path, the file is created via `POST /api/file/touch` and opened in the FileViewer.

### Changed
- **Finance over-time table sorting (2452)** — the income-statement and income/expense category over-time tables now default-sort by range-sum descending.

### Fixed
- **Calendar week grid rendering (2445)** — always render the week grid and show the empty state as an in-grid hint instead of replacing the grid.
- **Calendar event todo-id navigation (2500)** — clicking a calendar event's todo id now navigates to the trace view.
- **Telegram General-topic fallback (2471)** — fall back to the forum General topic when a topic has no `tg_topic` binding.
- **Dateless RSS entries (2462)** — stop dropping dateless RSS entries during stage-2 ingest.
- **Mobile chat-list drawer tint (2428)** — `display:none` the mobile right chat-list drawer when closed to stop iOS 26 Safari chrome tint sampling.
- **Agent no-result death & stream robustness (2510)** — check tmux session liveness before declaring a detached run dead on no-result, anchor the deadline pkill to the session, make the tail watcher self-terminating, and surface stream errors instead of swallowing them (with updated stream-converter tests).

### Removed

## [0.5.16] - 2026-06-07

### Added
- **pi.dev (pi_cli) agent backend** — added pi.dev as a new agent backend, wired its base URL through the OpenRouter gateway via `models.json`.
- **Bot config CLI** — added `y bot get <name>` to show a bot's full config and `y bot prices` to live-fetch OpenRouter per-1M prices, with those prices now shown inline in `y bot list` / `y bot get`. `y bot list` now defaults to compact columns (name/backend/model) with `--full` for all columns and a `--type` filter.
- **Multi-tier bot routing** — added 3-tier model-pool routing (tier0 uniform, tier1/tier2 inverse-square price load balancing), an explicit `route_weight` field replacing `price_override`, a bot `type` dimension (agent/model), and a `--tier` flag on `y chat` for tier selection.
- **Bot enable/disable (2362)** — bots can now be enabled or disabled, with routing and UI support.
- **Ref/pointer bots** — added a `ref_bot_name` field so a bot can point at another (e.g. default → codex).
- **Bot table UX** — moved the web bot table into BotViewer with a sortable price table, persisted sort state in localStorage, and OpenRouter providers sorted by throughput.
- **Trace bot badges** — trace skill badges now show the bot name.
- **Viewer TOC h3 headings** — file/link viewer TOC now includes h3 headings so TLDR sections get a table of contents.
- **Todo sidebar batch actions** — select mode in the todo sidebar now supports batch pin / status / priority actions; mark-read folded into the sidebar actions dropdown.
- **Public trace projection (2419)** — rebuilt the public trace share `/t/:shareId` as a read-only projection of the authed app: reuses ChatList + icon tabs in the right sidebar, a left balance rail, a centered todo-title page header, Ctrl+` to toggle FileViewer/ChatView, todo-detail rendered via the trace.md FileViewer view, and view state persisted per shareId.
- **Batch-share trace notes (2416)** — sharing a trace now batch-shares its associated notes in a single backend call.
- **Stable share links (2420)** — share links stay stable across unshare/reshare via soft-revoke.
- **Close-all-open-files mobile button (2427)** — added a close-all-open-files action to the mobile top bar.
- **Upload overwrite confirmation (2435)** — uploading a file with the same name as an existing one now prompts for confirmation before overwriting.

### Changed
- **Finance Transactions page revamp** — reworked the finance Transactions page with an IBKR-inspired layout.
- **ChatView header** — now shows the bot name before the backend.
- **pi models.json sync on bot CRUD (2377)** — bot create/update/delete now syncs the pi `models.json`, guarded for empty API keys, and `BotConfig.base_url` defaults to an empty string.
- **Docs migration** — migrated `CLAUDE.md` to `AGENTS.md` with a symlink and updated Maintenance references accordingly.
- **Unified trace & note shareviews (2417)** — unified trace and note shareviews with an in-place note overlay.
- **Lambda API cold-start latency (2423)** — cut API cold-start latency cheaply by lazy-importing the agent layer (after reverting an ineffective API memory bump).

### Fixed
- **Precise no-result error (2405)** — agent now derives a precise "no result" error message from the subprocess exit code.
- **Chat process error guards** — `run_chat` now guards bot-resolve failures with a fallback to the default bot and wraps all core chat process errors with a `running=False` fallback so a chat never gets stuck running.
- **pi_cli log noise** — suppressed `message_start` / `message_update` DEBUG logs from the pi_cli backend.
- **Unshare cascade to note shares (2418)** — unsharing a trace now cascades to revoke its associated note shares in the backend.
- **Mobile chat horizontal swipe lock (2431)** — locked the mobile chat view against horizontal swipe via `overflow-x-hidden`, with wide tables made independently scrollable.
- **iOS Safari chrome tint drift (2428)** — mobile left drawers are now `display:none` when closed so iOS 26 Safari stops sampling them for chrome bar tint on sidebar toggle.
- **Share-page TOC scoping (2434)** — share-page TOC heading lookup is now scoped to the active tab's article.
- **Remote upload/write NameError (2439)** — remote file upload/write now uses `_get_cmd_runner_cls()` to fix a `_CmdRunner` NameError.

### Removed

## [0.5.15] - 2026-05-31

### Added
- **Finance Investment Returns tab (2277)** — added an Investment Returns view splitting realized/unrealized/total P&L with MTD/YTD/over-time ranges, plus a sortable positions table (default Unrealized desc).
- **Forex sub-tab in finance notes sidebar (2279)** — the finance notes sidebar now nests a forex sub-tab under notes → forex → tickers.
- **Finance positions CLI and reusable service (2243)** — added `y finance positions` / click wiring plus a storage-level positions service so the API and CLI share realtime quote overlays, P&L math, and allocation output.
- **Chat artifacts rendering (1390 / 2237)** — chat messages can now render Markdown artifact fences, including Mermaid diagrams and HTML/CSS/JS previews, with a dedicated artifact viewer route and safer parser/test coverage for nested fences.
- **Finance realtime quotes and P&L display (2229)** — finance APIs now persist Alpha Vantage realtime quotes, overlay them into holding positions, pass the API key through deploy/CI wiring, parse quote timestamps in US Eastern time, and show holdings P&L with separate amount and percent columns.
- **Cross-machine YouTube cookie sync (2228)** — added `y cookies` CLI/API support for syncing browser cookies across machines, including multi-domain matching, language-aware subtitles, filtered link fetches, and lean JSON output.
- **Link list and viewer controls (2226 / 2227)** — link listing now supports a tri-state downloaded filter, while link/file viewers copy titles and URLs from the detail view without changing list selection behavior.
- **OpenRouter bot config hardening (2224 / 2225)** — bot config flows now honor custom OpenRouter-compatible base URLs and allow optional model/base URL fields in bot detail forms and storage defaults.
- **Manager bot (2217)** — added a `manager` bot config for Claude Code over OpenRouter GLM-4.7.
- **Finance risk and performance views (2189 / 2191 / 2198 / 2201)** — FinanceViewer now adds richer portfolio performance/range controls, YTD/MTD/QTD/1M/3M/1Y/ALL aliases, backend-resolved price ranges, future-price filtering, risky allocation percentages per period, and consistent risky-only allocation math.
- **Finance FIRE and config-backed analytics (2184 / 2185 / 2196)** — finance sync and APIs now expose config-backed FIRE/derived analytics, realized/unrealized holding calculations, normalized price/transaction/holding fields, and expanded tests for Beancount-derived portfolio data.
- **Responsive sidebar/list layout polish (2192)** — app navigation and sidebar lists now better support compact layouts with shared responsive behavior across notes, links, chats, reminders, routines, RSS feeds, todos, traces, dev, entity, file tree, and git panels.
- **Shared list error handling (2200)** — list panels now use a common error state component, including clean suppression for aborted list fetches.

### Changed
- **Friendly finance CLI tables (2274)** — the six DB-backed `y finance` commands (balance-sheet, income-statement, holdings, transactions, prices, fire-progress) now print human-readable tables by default, with the raw JSON envelope behind an explicit `--json` flag; `y finance beancount` is unchanged.
- **Chat/todo list query indexes (2238)** — chat list ordering now uses `updated_at_unix` so the new composite indexes can cover hot chat and todo list paths.
- **Bot sidebar and local path handling (2216 / 2220)** — bot sidebar rows are capped to two lines, and API/CLI link asset paths now resolve from `Y_AGENT_HOME` instead of hard-coded home-directory assumptions.
- **Finance snapshots storage model (2184)** — the earlier finance snapshot persistence path was replaced by direct holdings, prices, and transactions storage as the durable source of synced finance data.
- **Trace fetching and rendering stability (2199)** — detached agent handling and TraceView fetching/rendering were hardened to avoid noisy focus revalidation and preserve inline note-share metadata.
- **Worker deployment cleanup (2184)** — removed obsolete Lambda template and handler wiring that no longer participates in the finance sync path.
- **Finance over-time bucket labels (2288)** — weekly over-time buckets are now labeled with their Monday date instead of an ISO week number.

### Fixed
- **Finance holdings over-time fully-sold tickers (2285)** — holdings over-time no longer drops tickers that were fully sold within the range (e.g. QQQ).
- **Chat local file rendering (2219)** — Claude Code chat/file-link handling and shared chat rendering now resolve local file references more consistently across normal and shared views.
- **Finance price filtering (2184 / 2191)** — finance price queries now parse `from_date` before filtering, ignore future-dated prices, resolve time ranges on the backend, and default charts to YTD.
- **Trace shared-note metadata (2184)** — trace payloads now inline note share metadata so shared note links render correctly in trace todo details.

### Removed

## [0.5.14] - 2026-05-24

### Added
- **Note sharing (2164 / 2165 / 2171)** — notes can now be shared via S3-backed snapshots at `/n/:shareId`, with optional password protection, share management, refresh-to-resnapshot, linked shared-note URLs in trace todo details, and a generated table of contents on shared note pages.
- **Telegram assistant image delivery metadata (2112)** — assistant image delivery now records durable Telegram delivery metadata for follow-up chat rendering and monitoring.
- **Claude Code resume session restoration** — Claude Code resume launches now restore missing session JSONL files from the backup-projects archive before starting `claude -r`, recovering chats pruned by Claude's cleanup window.
- **Finance snapshots, holdings, prices, and transactions (2184)** — Beancount finance sync now persists snapshots, holdings, prices, and transactions through storage entities/repositories/services, adds matching CLI commands and API wiring, and expands FinanceViewer to browse the synced data.

### Changed

### Fixed
- **EC2 wake before SSH connect (2149)** — detached runs and pooled SSH connections now wake stale EC2 VMs before connecting, wait longer for SSH readiness, and use explicit connect timeouts.
- **Absolute file reads over SSH (2151)** — `read_file` and `raw_file` no longer prepend stale `work_dir` values for absolute or home-relative paths, preventing empty reads when the cwd is missing.
- **EC2 detached-run heartbeat (2121)** — detached tmux runs now keep `/tmp/ec2-ssh-last-seen` fresh during long executions and stop the heartbeat after command exit, preventing premature hibernation while preserving exit status.
- **Tail cancellation resume state (2120)** — Codex, Claude, and Gemini tailers now return resumable monitoring state on cancellation, preserving offsets, message ids, sessions, and consumed steer ids for the next monitor pass.
- **Attached image duplicate delivery (2115)** — chat image attachments are now delivered once per request instead of being duplicated through the API handoff path.
- **Worker timeout resume session ids** — worker monitor metadata now falls back to the stored process session/thread id when a timeout or error result omits it, keeping resumed Claude/Codex/Gemini chats linked to the correct session.
- **Local file link handling (2183)** — local file URL normalization, opening, and CodeEditor/FileViewer navigation now handle additional path shapes consistently across chat messages and tests.

### Removed

## [0.5.13] - 2026-05-17

### Added
- **Bot list sidebar (2085)** — ActivityBar gains a dedicated bot list sidebar backed by the bot-config API.
- **Image attachment delivery hardening (2107 / 2108 / 2110)** — Codex, Claude, and Gemini launches accept staged image paths from Telegram/API/CLI chat flows; image handling now supports Telegram, EC2-only paths, S3 fallback, and chat rendering for attached/generated images.
- **`y note delete` + `y note update --front-matter` (2009)** — new `y note delete` CLI command + `POST /api/note/delete` endpoint with safe-delete guards (refuses when an entity backs the note; requires `--force` to unlink live `note_todo` relations before soft-deleting). `y note update` now accepts `--front-matter` to re-parse and replace the stored YAML front-matter from the file at `content_key`.
- **Finance `topics` sub-tab** — NoteList's finance tab gains a fourth `topics` sub-tab alongside `notes` / `weekly` / `tickers`, persisted via `noteListFinanceSubTab`.
- **Skills tab in NoteList (2045)** — new top-level Skills tab with search, backed by a new `GET /api/file/skills` endpoint that lists `~/.claude/skills/`.
- **Front-matter preview card in FileViewer (2046)** — markdown files with YAML front-matter render a collapsible card above the body, with the raw front-matter still toggleable.
- **Risky positions toggle in FinanceViewer (2028)** — FinanceViewer adds a switch to hide/show high-risk holdings in the balance sheet view.
- **ReminderList sidebar (2048 / 2049 / 2057)** — full-featured reminder panel in the sidebar with create/edit/cancel, sort by trigger time, and filtering.
- **`y telegram` CLI (2047)** — new `y telegram send` / `click` subcommands + matching `POST /api/telegram/{send,click}` endpoints; worker telegram code refactored into `storage/service/telegram.py` and shared with the CLI.
- **Todo mark-all-as-read (2060)** — bulk "mark all read" action in TodoList with a new repo/service/controller path; complements the existing per-todo toggle.
- **Editable trace todo detail (2058)** — TraceTodoDetail rewritten with full inline edit for status / priority / due / tags / description / progress; shared between TraceView (editable) and ShareTraceView (read-only). Textareas now expand and autosize robustly for longer description / progress edits. Extends the 0.5.12 inline-progress edit (1995).
- **LinkList sidebar time filter (2053)** — time-range filter chips on the link sidebar, matching the unified `--on/--from/--to` semantics.
- **Unified `y ... list` time filter flags** — canonical `--on / --from / --to` plus prefixed `--created-* / --updated-*` overrides on every list CLI (todo, note, chat, link, calendar, reminder, email, rss, entity, routine) and the matching API controllers, with a shared `apply_time_filter` helper. Date `--to` is closed-day; datetime `--to` is half-open. Hard cut on old `--completed-*` / `--start` / `--end` / `--date` flags and link list's `today/yesterday/Nd` relative tokens. Web list views (LinkList, CalendarViewer) re-aligned to the new params (2061).
- **Gemini CLI backend** — new Gemini CLI agent backend with stream conversion, monitor/runner integration, bot and routine CLI wiring, docs, and headless-run handling.
- **Bot backend identity (2072 / 2074)** — chats now persist/display the selected bot name, bot configs carry an explicit backend field, and runner paths resolve resumed chats through the stored backend.
- **Codex tool detail rendering (2081)** — Codex stream conversion and chat/share message parsing now expose richer tool details in the UI.
- **Local file links in chat and FileViewer (2083)** — local file path references are parsed into clickable links across FileViewer and chat messages.
- **Bot config OpenRouter clearing** — `y bot update --clear-openrouter` clears OpenRouter settings from an existing bot config.
- **Inline bot routing + desktop popup refinement** — `/api/inline` now routes through each user's named `inline` bot, while the macOS desktop app has been converted to TS/React with a three-section popup, more reliable selection capture, and the new `⌘⌃Y` shortcut.
- **Image attachments for chat + telegram** — chat input, `y chat click`, `y telegram send`, and telegram/API controllers now accept uploaded images; backend launchers pass staged image paths through Claude/Codex/Gemini runners, pasted/attached images render in chat, and completed image chats clear the running state durably (2104).
- **OpenAI image provider** — `y image generate` can use an OpenAI-backed image provider in addition to the existing generation path.

### Changed
- **Release publishing config (2111)** — CLI packaging metadata and the publish workflow were refreshed for the next release path.
- **TodoContextMenu status options inlined (1994)** — status choices moved out of the "Status" submenu into an inline radio row at the top of the context menu, refining the 0.5.12 submenu version.
- **TodoContextMenu pin/unpin (2054)** — pin/unpin moved into the right-click menu; TodoList and TodoViewer route through the menu action.
- **Note sidebar drops the "Weekly" tab (2064)** — NoteList top-level Weekly tab removed; weekly notes still reachable through Finance → weekly.
- **Chat read/unread no longer bumps `updated_at` (2051)** — `set_chat_unread` / `mark_chats_read_by_trace` / `mark_latest_chat_unread_by_trace` switched to raw SQL so SQLAlchemy's `onupdate` doesn't bump the chat row, keeping the chat list order stable when toggling read state.
- **`y chat --bot` replaces `--backend`** — both interactive and one-shot chat CLI modes now select named bot configs instead of raw backend flags.
- **Todo read controls (2095 / 2101)** — Todo context menu now toggles read/unread based on current unread state, and TodoList adds select mode plus bulk mark-read via `POST /api/chat/trace/read_bulk`.

### Fixed
- **Telegram resume preserves `work_dir` (2011)** — `_handle_message` and `_handle_routed_message` now forward the chat's `work_dir` when re-queuing, so the worker resumes the existing claude-code session under the same cwd instead of falling back to the VM default.
- **Backend launch and resume reliability** — backend launch errors are persisted, resumed chats prefer their stored backend, flexible backend defaults are preserved, and Gemini headless runs are treated as trusted.
- **Codex blocker detection (2077)** — Codex monitor/runner handling better surfaces blocked sessions and tool events.
- **`y bot list -v` OpenRouter crash** — verbose bot listing no longer raises `UnboundLocalError` when OpenRouter config is absent.
- **Telegram image staging** — telegram image uploads are staged under Lambda `/tmp` and passed through the API send path reliably.

### Removed

## [0.5.12] - 2026-05-10

### Added
- **macOS desktop inline rewrites** — new Electron app under `desktop/` plus `POST /api/inline` endpoint (Claude Haiku 4.5): `Alt+Space` captures the current selection via AppleScript `Cmd+C`, an input window calls `/api/inline`, and the result is pasted back via `Cmd+V` or shown in a copy popover. Includes macOS Accessibility permission docs and in-app permission-error surfacing.
- **Finance tab in NoteList** — new top-level "Finance" tab with `notes` / `weekly` / `tickers` sub-tabs reading from `~/finance/`; `notes` uses access-time sort, `weekly` reverse-lex, `tickers` lex.
- **`FINANCE_MONTHLY_EXPENSE` config override (1993)** — `y beancount fire-progress` resolves `monthly_expense` with precedence `config.toml` → `position.json` → `fire_target.json` → default 5000, and reports the resolved source so the FIRE tab and weekly rebalance can share the value via `~/.y-agent/config.toml`.
- **Todo `completed_at` date filters (1998)** — `GET /api/todo/list` and `y todo list` accept `--completed-on` / `--completed-since` / `--completed-until` (local-tz `YYYY-MM-DD`) to scope completed todos to a single day or range.
- **Inline trace progress edit (1995)** — TraceView's todo progress field is now editable with a dirty-aware draft + Save flow; shared between TraceView and ShareTraceView via a new `TraceTodoDetail` component (read-only on the share view).

### Changed
- **TodoContextMenu status submenu (1994)** — status transitions consolidated into a single "Status" submenu with color-coded options and the current status disabled, replacing the per-status flat action list.

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
- **Personal Information Hub (Phase 1)** — link download/archiving via SSH, Twitter/X post + article support
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
