---
title: Use via CLI
category: Intro
order: 2
---

# Use via CLI

This page is for using a hosted y-agent instance (e.g. `yovy.app`) from your terminal. You don't need to run the API or worker yourself — `y login` authenticates against an existing instance and the CLI talks to it over HTTPS. If you want to run your own instance, see [self-host.md](self-host.md).

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
| `ALPHAVANTAGE_API_KEY` | `y beancount` market-data updates |

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
```

`y --help` lists every subcommand group; each group has its own `--help` for details.

## Where to next

- [docs/getting-started.md](getting-started.md) — what the web UI looks like once you're signed in.
- [docs/capabilities.md](capabilities.md) — what subsystems the running instance ships.
- [docs/self-host.md](self-host.md) — only if you want to run your own API + worker.
