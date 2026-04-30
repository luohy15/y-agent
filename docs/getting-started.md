---
title: Getting started
category: Intro
order: 1
---

# Getting Started

This page walks through what y-agent looks like after you sign in. It assumes a deployed instance (e.g. `yovy.app`) — installing your own copy is in [self-host.md](self-host.md).

## Sign in

Click **Sign in with Google** on the landing page. The first sign-in creates your user record; subsequent sessions reuse it. Auth is a JWT stored in `localStorage`, so the same browser stays signed in until you hit **Logout**.

Preview deployments (any non-`yovy.app` host) bounce you to the main domain to sign in, then redirect back with a short-lived token in the URL. You don't need to log in twice.

## The home screen

After login, `/` renders the main app. The layout is multi-panel:

- **Activity bar** (left edge) — switches between Notes, Chats, Links, Files, Git, and a few other subsystem panels.
- **Sidebar** — content for the active panel. Resizable; collapsible on mobile.
- **Main area** — file viewer / editor. Markdown previews automatically; click a code file to syntax-highlight it.
- **Chat panel** — on the right (or full-screen on mobile). The center of the agent surface.
- **Terminal** — a slide-out shell scoped to the current VM and `work_dir`.
- **Trace** — a waterfall view of any cross-skill call chain. See [a real one](https://yovy.app/t/6fc5c4) for what it looks like.

Everything is keyboard-friendly. **⌘K** (Ctrl+K on Linux/Windows) opens the command palette — start typing to jump to a chat, file, todo, note, or any panel.

## Sending a task

A "task" in y-agent is just a chat. Type into the chat input and hit ⌘↩ (or click Send) to dispatch it. The first message creates a new chat row, queues an SQS job, and a worker picks it up and starts a Claude Code or Codex subprocess on EC2.

You'll see streaming output in real time:

- **Tool calls** render inline with collapsible bodies. Bash commands show stdout/stderr; `file_read` shows the file path.
- **Steer messages** — type into the chat while the agent is running; the message is delivered to the live stdin pipe so you can redirect mid-thought.
- **Stop** — the explicit interrupt button. Also useful when the agent is stuck.
- **Context usage** — hover the small percentage in the header for input / output / cache breakdown. Long sessions auto-restart in a fresh chat with a summary once they hit ~50% context.

If a task is going to run longer than 15 minutes, the worker hands off to the next Lambda invocation transparently. You don't need to do anything; the chat stays "running" and output keeps streaming.

### Picking a backend or skill

Defaults work for most cases, but you can override per chat:

- **Backend**: Claude Code (default) or Codex. Codex is cheaper but doesn't have the same tool ecosystem.
- **Skill**: pick a specialized skill (e.g. `dev`, `plan`, `impl`) instead of the default `manager`. The skill defines what tools and prompts the agent loads.
- **VM** / **work_dir**: which EC2 instance and project directory to run in. Most users have one VM and a default work_dir, so this is set-and-forget.

## Todos

Todos are first-class. The agent reads, creates, and updates them via the `y todo` CLI; you do the same from the **Todo** sidebar panel or the kanban view.

- **Create** — top-right "+" button or `y todo add "..." -p high`.
- **Activate** — drag from "pending" to "active". Only one in-progress per chain by convention.
- **Pin** — a star icon on each card; pinned todos float to the top.
- **History** — every status change is logged so you can see when you started / finished.

Todos can be linked to **notes** (plan / requirement / decision context), **links** (web pages, articles, X / Bilibili / WeChat), and a **trace_id** (which is just the todo's public ID — every chat dispatched under that todo carries the same trace_id, and the TraceView stitches them into a tree).

## Switching between chats

The **Chats** panel lists all chats in reverse-chronological order. Click any to load it; the message history streams in via SSE so it's instant even for long chats.

A few shortcuts:

- **New chat**: + button at the top of the chat panel, or send a message with no chat selected.
- **Clear**: the trash icon resets the selection without deleting the chat.
- **Share**: the share button creates a public read-only URL (with optional password). Useful for showing a coworker a debugging session.
- **Trace view**: the trace icon next to a chat opens the waterfall — every cross-skill `y chat` call shows up as a row.

## Files

The **Files** panel is a lazy file tree of your VM's `work_dir`. Click a file to open it in the main area; ⌘P (file search) jumps directly to a file by name.

The viewer/editor:

- Syntax highlighting for the usual languages.
- **Edit mode** — click the pencil icon. Changes are local until you save.
- **Click-to-open** — relative paths inside markdown are clickable.
- **Preview** — markdown renders side-by-side; opening a `.md` file you only browse without committing is treated as a "preview" tab.

The **Git panel** shows file-level status against `HEAD`. Click a file to see its diff; per-file discard is one click. Commits go through the chat — ask the agent to commit and it'll write the message.

## Telegram

If your deployment has a Telegram bot configured, you can chat with the same backend from your phone:

1. Bind a forum topic to a y-agent chat from the chat menu (the Telegram icon).
2. Messages in that topic now route to the bound chat. Replies from the agent come back as Telegram posts (markdown auto-converts to HTML).
3. **Reminders** are also delivered through Telegram — add `y reminder add "ping me at 3pm to review the PR"`.

Forum topics are great for "one chat per project" — the topic name is the persistent address, and you can join/leave the conversation across days without losing trace context.

## Routine

Recurring jobs live under **Routine**. Each routine is a cron-like schedule that dispatches a chat to a topic every interval. Use it for:

- Daily journal prompts.
- Weekly digest of new RSS items.
- Hourly health checks against an external service.

The schedule + payload are stored as a routine row; the admin Lambda fires them on EventBridge.

## Tips

- **Restart on context creep**: if the agent feels confused, `y todo finish` the current todo and start fresh. The auto-restart at 50% context handles most cases, but a manual restart is faster.
- **One trace per todo**: dispatch a new chat with `--new` for every new todo. Reusing an old chat across todos pollutes the trace tree.
- **Worktrees for code**: when the agent needs to work on a feature branch in parallel, use the **Dev worktrees** panel (or `y dev wt add`). Each worktree gets its own chat session and can run independently of `main`.
- **CDN for shared assets**: if you upload a file via the link archive or generate one with the image skill, it lands on the CDN and is reusable across chats.
- **Read the trace, not the chat**: when something goes wrong, open the trace view first. Cross-skill failures are almost always more obvious in the waterfall than in any single chat.
- **Skill list**: see the [skills directory in the repo](https://github.com/luohy15/y-agent/tree/main/agent) for what comes out of the box. Adding your own is just dropping a `SKILL.md` under `~/.agents/skills/<name>/`.

## Where to next

- [README](https://github.com/luohy15/y-agent) — capabilities matrix, install, deploy.
- [Architecture write-up](https://luohy15.com/y-agent-introduction) — design rationale, why coding agents, why a session tree.
- [CHANGELOG](https://github.com/luohy15/y-agent/blob/main/CHANGELOG.md) — weekly updates.
