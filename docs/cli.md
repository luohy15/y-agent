---
title: Use via CLI
category: Intro
order: 2
---

# Use via CLI

**Client page.** This covers the client-side `y` CLI driving a *hosted* y-agent instance (e.g. `yovy.app`) from your terminal. You don't need to run the API or worker yourself — `y login` authenticates against an existing instance and the CLI talks to it over HTTPS. Running your own server is a separate concern; see [self-host.md](self-host.md).

## Install the CLI

The CLI lives in the `cli/` package of this UV workspace.

```bash
git clone https://github.com/luohy15/y-agent.git
cd y-agent
uv tool install --force -e ./cli
```

`y --help` should now work from anywhere.

## Sign in

```bash
y login
```

Opens a browser to the configured instance (`https://yovy.app` by default), runs Google OAuth, and writes a JWT to `~/.y-agent/auth.json`. The token is reused across CLI invocations until you run `y logout`.

If you're on a headless box, `y login --no-browser` prints the URL and waits for you to paste back the token from the callback page.

To point the CLI at a different instance, set `Y_AGENT_WEB_URL` before running `y login`.

## Config keys

CLI-side config lives in `~/.y-agent/config.toml` (or as env vars). Only these matter for the basic CLI flow:

| Key | Purpose | Default |
|-----|---------|---------|
| `Y_AGENT_HOME` | Local data + auth dir | `~/.y-agent` |
| `Y_AGENT_WEB_URL` | Instance the CLI logs in against | `https://yovy.app` |
| `Y_AGENT_TIMEZONE` | IANA tz used for date display | system |
| `Y_AGENT_PROXY_HOST` / `Y_AGENT_PROXY_PORT` | Optional outbound HTTP proxy | — |

### Optional integrations

These are only needed for the matching subcommands:

| Key | Used by |
|-----|---------|
| `TINIFY_API_KEY` | `y image tinify` (TinyPNG compression) |
| `GOOGLE_API_KEY` | `y image generate` / `refine` (Gemini) |
| `ALPHAVANTAGE_API_KEY` | `y finance beancount` market-data updates and realtime finance quote overlays |

## Common commands

```bash
# Chat — fire a message at a topic, skill, or chat-id (fire-and-forget by default)
y chat -m "summarize today's reminders" --topic manager
y chat -i                                 # interactive REPL, human use

# Todos
y todo list -s active
y todo add "ship docs split" -p high -t docs
y todo update <id> --progress "drafted self-host.md"
y todo finish <id>

# Notes
y note import pages/plan-foo.md
y note list

# Calendar / reminders
y calendar import path/to/file.ics
y reminder add "ping me at 3pm to review the PR"

# Dev worktrees
y dev wt add /path/to/repo my-feature
y dev commit my-feature -m "wip"
y dev wt rm my-feature

# Finance — DB-backed views matching /api/finance/*
y finance balance-sheet --convert USD
y finance income-statement --time month --convert USD
y finance holdings --base-currency USD
y finance transactions --limit 20
y finance prices --symbol AAPL --limit 5
y finance fire-progress

# Ledger-side producer / low-level local views
y finance beancount snapshot
y finance beancount update-market-data
```

## All command groups

`y --help` lists every group; each has its own `--help`. The full set:

| Group | What it does |
|-------|--------------|
| `chat` | Dispatch a message to a topic / skill / chat-id (fire-and-forget); `-i` for the REPL |
| `todo` | Tasks: add / list / update / activate / finish; the public id doubles as the trace id |
| `note` | Structured notes (`content_key` + front-matter); import / list / get |
| `entity` | Knowledge-graph nodes; `import` a page, `import-link`, `list`, `get` |
| `assoc` / `unassoc` | Link or unlink notes / links to a todo |
| `calendar` | Events: `import` an ICS, list, CRUD |
| `reminder` | Time-based reminders delivered via Telegram |
| `routine` | Cron-style auto-fired chats: add / list / enable / disable / run |
| `link` | Link archive: `fetch`, `get`, `list`, `sync-chrome`, `tldr`, `import-page` |
| `rss` | Feeds: `add`, `list`, `update`, `import-opml`, remove / restore |
| `email` | Gmail: `sync-gmail`, `list`, `get`, multi-account `account add/list/rm` |
| `finance` | DB-backed views (balance-sheet / holdings / …); `beancount` is the ledger producer |
| `image` | `generate` (Gemini/OpenAI), `splice`, `tinify` (TinyPNG) |
| `pdf` | `parse` a PDF into Markdown |
| `cookies` | `sync` / `list` / `delete` local browser cookies for remote fetchers |
| `bot` | Manage backend configs (Claude Code / Codex / Gemini CLI): add / enable / disable / update |
| `trace` | `share` / `unshare` a trace as a public read-only page |
| `claude` | `usage` — scrape Claude Code 5h + weekly limit-window usage |
| `dev` | Worktree lifecycle: `wt add` / `wt rm` / `commit` |
| `telegram` | Send a Telegram message via the API |
| `init` / `login` / `logout` | Config bootstrap + auth against the hosted instance |

A few more snippets:

```bash
# Links — sync history, fetch a page to markdown, get a TLDR
y link sync-chrome
y link fetch https://example.com/article
y link tldr <link_id>

# RSS / Email
y rss add https://example.com/feed.xml
y email sync-gmail

# Entities + association to a todo
y entity import pages/some-product.md
y assoc note pages/plan-foo.md --todo <todo_id>

# Image + PDF helpers
y image tinify shot.png
y pdf parse paper.pdf

# Trace share + Claude usage
y trace share <trace_id>
y claude usage
```

## Where to next

- [docs/getting-started.md](getting-started.md) — what the web UI looks like once you're signed in.
- [docs/capabilities.md](capabilities.md) — what subsystems the running instance ships.
- [docs/self-host.md](self-host.md) — only if you want to run your own API + worker.
