#!/bin/bash

# Stop vite dev server and ngrok (if running)
# Pattern must match the actual command: "node <worktree>/web/node_modules/.bin/vite"
pkill -f "$(pwd)/web" 2>/dev/null || true
pkill -f "ngrok" 2>/dev/null || true

# Remove symlinked/copied artifacts
rm -rf web/node_modules web/.env.local .env .venv

# Reinstall CLI pointing to main project to fix editable install path
cd /Users/roy/luohy15/code/y-agent/cli && uv tool install --force -e .
