#!/bin/bash

# Share non-environment runtime assets only. Do NOT link .venv: editable installs
# write absolute checkout paths into *.pth, so a shared venv makes every worktree
# import whichever checkout last ran `uv sync` / `uv run`. `y dev wt add` creates
# a worktree-local locked environment after this hook for root uv projects.
for item in web/node_modules web/.env.local .env migration; do
  ln -sfn /Users/roy/luohy15/code/y-agent/$item $item
done

# Tests stay local-only, so share the suites that are safe outside their checkout.
for item in agent/tests api/tests cli/tests storage/tests worker/tests web/e2e; do
  ln -sfn /Users/roy/luohy15/code/y-agent/$item $item
done
