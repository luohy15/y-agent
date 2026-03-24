#!/bin/bash

# Stop vite dev server and ngrok using PID files (dev skill v3.0 multi-instance isolation)
WORKTREE_NAME=$(basename "$(pwd)")
SESSION_DIR="/tmp/dev-sessions/$WORKTREE_NAME"

if [ -d "$SESSION_DIR" ]; then
  for pidfile in vite.pid ngrok.pid; do
    if [ -f "$SESSION_DIR/$pidfile" ]; then
      kill "$(cat "$SESSION_DIR/$pidfile")" 2>/dev/null || true
    fi
  done
  rm -rf "$SESSION_DIR"
fi

# Remove symlinked/copied artifacts
rm -rf web/node_modules web/.env.local .env .venv

# Reinstall CLI pointing to main project to fix editable install path
cd /Users/roy/luohy15/code/y-agent/cli && uv tool install --force -e .
