- We use uv to manage Python dependencies, so run Python scripts with uv run
- CLI install command: uv tool install --force -e ./cli

## Git Worktree

When creating a new worktree, symlink build artifacts to avoid rebuilds:

`.venv` and `web/node_modules` live in local xfs (`~/.cache/`, not JuiceFS) to avoid FUSE performance issues with many small files. `.aws-sam` is handled by `deploy.sh` directly via `~/.cache/y-agent/.aws-sam`.

```bash
git worktree add -b <branch> <path> main
cd <path>
ln -s ~/.cache/y-agent/.venv .venv
ln -s ~/.cache/y-agent/node_modules web/node_modules
ln -s ../.env .env
```