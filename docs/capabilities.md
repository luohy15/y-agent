---
title: Capabilities
category: Reference
order: 2
---

# Capabilities

*Client + server reference.* This is what a running deployment ships and what you can reach from the web GUI or the `y` CLI against it. Running your own instance is covered in [self-host.md](self-host.md).

## Showcased capabilities

These four are the ones worth seeing first — each has a dedicated walkthrough (and a screenshot) in [getting-started.md](getting-started.md).

- **Todo & Trace** — first-class todos (full-stack CRUD, kanban, pagination, pin, search, status history) where the todo's public ID *is* the `trace_id`. Every chat dispatched under a todo carries that id, and the **TraceView** waterfall stitches the whole cross-skill call chain into one tree. Traces are shareable as a public read-only page (optionally password-protected).
- **Note** — structured notes with a `content_key` file pointer plus JSON front-matter, linked many-to-many to todos. Journals (daily log), Pages (topic state), and plan / requirement / decision context all live here.
- **Link** — a browsable link archive: Chrome history / bookmark sync, on-demand fetch of Twitter / X, Bilibili, WeChat, and generic pages into markdown, TLDR summaries, and in-app markdown preview.
- **Finance** — beancount-backed balance sheet, income statement, holdings, transactions, prices, investment returns, and FIRE progress, rendered as web charts and mirrored by `y finance`.

## Sidebar panels

Every activity-bar panel in the web GUI:

- **Todo** — kanban + list, pin, pagination, search, history. *(showcased)*
- **Notes** — Journals + Pages + structured notes. *(showcased)*
- **Chats** — every chat in reverse-chronological order; click to stream history via SSE; new / clear / share / trace actions.
- **Links** — the link archive. *(showcased)*
- **RSS** — feed subscriptions with a two-stage scrape pipeline (admin schedules → worker scrapes feed XML → downloader fetches each item); per-item content on S3.
- **Entities** — knowledge-graph nodes (person / product / org / project). Each entity has a backing note and can be associated with other notes and RSS feeds.
- **Bots** — manage bot/backend configurations (Claude Code / Codex / Gemini CLI / others): add, enable/disable, set model + API key, pick per-chat or per-routine.
- **Reminders** — time-based reminders delivered via Telegram, optionally attached to a todo or event.
- **Routines** — cron-style schedules that auto-fire a chat to a topic; the admin Lambda fires them on EventBridge (daily journal, weekly digests, health checks).
- **Files** — lazy file tree of the VM's `work_dir`; viewer/editor with syntax highlighting, line numbers, unsaved-edits preview, and click-to-open relative links.
- **Calendar** — timezone-aware events with a current-time ticker; ICS import.
- **Finance** — balance sheet / income statement / holdings / FIRE charts. *(showcased)*
- **Email** — multi-account Gmail sync for lightweight inbox review; each row tagged with its source account.
- **Dev** — `y dev` worktree lifecycle from the GUI: create/remove worktrees per task, auto-commit, dynamic merge target.

## Other surfaces

Not in the activity bar, but part of the same app:

- **Trace view / waterfall** — the cross-skill call-chain visualizer described above; reachable from any chat. *(showcased with Todo)*
- **Web terminal** — a slide-out shell scoped to the current VM / `work_dir`.
- **Git panel** — file-level status against `HEAD`, diff viewer, per-file discard.
- **Command palette (⌘K / Ctrl+K)** — fuzzy-jump to any chat, file, todo, note, or panel.
- **Message export to image** — select chat messages and export them to a phone-friendly PNG (native share sheet on touch, else download + clipboard copy).
- **Claude usage widget** — surfaces Claude Code subscription limit-window usage (5h session + weekly windows).
- **Artifacts** — assistant markdown fenced as `mermaid`, `vega-lite`, or `artifact-svg` render inline in chat.

## Integrations & infrastructure

- **Telegram bot** — webhook with secret verification, forum-topic routing, markdown → HTML conversion, reminder delivery.
- **Agent runtime** — Claude Code / Codex / Gemini CLI backends run detached inside `tmux` on EC2 over SSH; the worker tails output, streams JSON events, and hands off across Lambda's 15-minute cap; mid-run steer + explicit stop; context monitor auto-restarts long sessions.
- **Browser cookies** — `y cookies sync` uploads local browser cookies so remote link fetchers (e.g. `yt-dlp` on YouTube) can use them.
