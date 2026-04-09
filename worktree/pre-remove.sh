#!/bin/bash
# Remove symlinked/copied artifacts
rm -rf web/node_modules web/.env.local .env .venv

# Reinstall CLI pointing to main project to fix editable install path
cd /Users/roy/luohy15/code/y-agent/cli && uv tool install --force -e .
