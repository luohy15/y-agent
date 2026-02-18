- We use uv to manage Python dependencies, so run Python scripts with uv run
- CLI install command: uv tool install --force -e ./cli

## Git Worktree

When creating a new worktree, symlink build artifacts to avoid rebuilds:

```bash
git worktree add -b <branch> <path> main
cd <path>
ln -s ../y-agent/.venv .venv
ln -s ../y-agent/node_modules node_modules
ln -s ../y-agent/.aws-sam .aws-sam
ln -s ../y-agent/.env .env
```