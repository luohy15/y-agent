import os
import subprocess
import click

from yagent.api_client import api_request
from .registry import get_worktree


def _plans_dir(work_dir: str) -> str:
    path = os.path.expanduser(work_dir)
    slug = path.replace("/", "-")
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", slug, "plans")


def _build_prompt_from_todo(todo: dict, work_dir: str) -> str:
    parts = [f"Task: {todo['name']}"]
    if todo.get('desc'):
        parts.append(todo['desc'])
    if todo.get('progress'):
        parts.append(todo['progress'])
    if work_dir:
        parts.append(f"\nWrite plan files to: {_plans_dir(work_dir)}/")
    parts.append("\nWhen finishing a plan, always include the plan file path in your response so the user can review it.")
    return "\n".join(parts)


@click.command('run')
@click.argument('worktree_name')
@click.option('--todo', 'todo_id', default=None, help='Use a todo item as input')
@click.option('--message', '-m', default=None, help='Requirement / prompt message')
@click.option('--clear', is_flag=True, help='Start a new session instead of continuing')
@click.option('--bot', '-b', default='claude-code', help='Bot name')
def dev_run(worktree_name: str, todo_id: str, message: str, clear: bool, bot: str):
    """Submit work to a worktree. Provide --todo or --message as input."""
    entry = get_worktree(worktree_name)
    work_dir = entry["worktree_path"]

    if not os.path.isdir(work_dir):
        click.echo(f"Error: worktree path does not exist: {work_dir}", err=True)
        raise click.Abort()

    # Rebase worktree branch onto main before running
    try:
        subprocess.check_call(["git", "rebase", "main"], cwd=work_dir)
    except subprocess.CalledProcessError:
        click.echo("Error: rebase onto main failed. Resolve conflicts first.", err=True)
        raise click.Abort()

    # Determine prompt and chat tracking
    chat_ids = []
    prompt = message

    if todo_id:
        try:
            resp = api_request("GET", "/api/todo/detail", params={"todo_id": todo_id})
            todo = resp.json()
        except Exception as e:
            click.echo(f"Error fetching todo: {e}", err=True)
            raise click.Abort()
        click.echo(f"Todo: {todo['name']} [{todo['status']}]")
        chat_ids = todo.get('chat_ids') or []
        if not prompt:
            prompt = _build_prompt_from_todo(todo, work_dir)

    if not prompt:
        click.echo("Error: provide --message or --todo as input", err=True)
        raise click.Abort()

    # Resume or new session
    if chat_ids and not clear:
        chat_id = chat_ids[-1]
        continue_msg = message or "Continue working on this task."
        api_request("POST", "/api/chat/message", json={
            "chat_id": chat_id, "prompt": continue_msg, "bot_name": bot, "work_dir": work_dir,
        })
        click.echo(f"Resumed chat {chat_id}")
    else:
        resp = api_request("POST", "/api/chat", json={
            "prompt": prompt, "bot_name": bot, "work_dir": work_dir,
        })
        chat_id = resp.json()["chat_id"]
        click.echo(f"Created chat {chat_id}")

        # Track chat_id on todo if using todo input
        if todo_id:
            chat_ids.append(chat_id)
            api_request("POST", "/api/todo/update", json={
                "todo_id": todo_id, "chat_ids": chat_ids,
            })
