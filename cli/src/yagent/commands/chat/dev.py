import os
import subprocess
import sys
import click

from yagent.api_client import api_request
from yagent.chat.stream_client import stream_chat
from yagent.display_manager import DisplayManager
from yagent.input_manager import InputManager


def _stop_chat(chat_id: str):
    try:
        api_request("POST", "/api/chat/stop", json={"chat_id": chat_id})
    except Exception:
        pass


def _stream_and_handle(chat_id: str, display_manager: DisplayManager, last_index: int = 0):
    """Stream messages. Returns (last_index, interrupted)."""
    try:
        last_index, status, data = stream_chat(chat_id, display_manager, last_index)
    except KeyboardInterrupt:
        _stop_chat(chat_id)
        return last_index, True

    if status == "interrupted":
        _stop_chat(chat_id)
        return last_index, True

    if status == "done":
        return last_index, False

    return last_index, True


def _build_prompt(todo: dict, mode: str | None = None) -> str:
    parts = [f"Task: {todo['name']}"]
    if todo.get('desc'):
        parts.append(todo['desc'])
    if mode == 'plan':
        parts.append("\nYou are in plan mode. Create a detailed implementation plan but do NOT write any code.")
        parts.append("When finishing a plan, always include the plan file path in your response so the user can review it.")
    elif mode == 'implement':
        if todo.get('progress'):
            parts.append(f"\nImplementation plan: {todo['progress']}")
        parts.append("\nYou are in implement mode. Follow the plan and implement the changes.")
    else:
        if todo.get('progress'):
            parts.append(todo['progress'])
        parts.append("\nWhen finishing a plan, always include the plan file path in your response so the user can review it.")
    return "\n".join(parts)


def _build_post_hooks(todo: dict, todo_id: str, mode: str | None, no_worktree: bool) -> list | None:
    hooks = []
    if mode == 'plan':
        hooks.append({"type": "save_plan_to_todo", "todo_id": todo_id})
    if not no_worktree:
        hooks.append({"type": "commit_and_pr", "todo_id": todo_id, "todo_name": todo['name'], "todo_desc": todo.get('desc', '')})
    return hooks or None


def _git_root() -> str:
    return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()


def _create_worktree(git_root: str, todo_id: str) -> str:
    repo_name = os.path.basename(git_root)
    path = os.path.join(os.path.dirname(git_root), f"{repo_name}-{todo_id}")
    branch = f"worktree-{todo_id}"
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.check_call(["git", "worktree", "add", "-b", branch, path, "HEAD"])
    _apply_symlinks(git_root, path)
    return path


def _apply_symlinks(git_root: str, worktree_path: str):
    symlinks_file = os.path.join(git_root, ".symlinks")
    if not os.path.exists(symlinks_file):
        return
    with open(symlinks_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            src, dst = line.split(",", 1)
            src = src.strip()
            dst = dst.strip()
            # resolve relative paths against worktree_path
            if not os.path.isabs(src):
                src = os.path.join(worktree_path, src)
            else:
                src = os.path.expanduser(src)
            target = os.path.join(worktree_path, dst)
            if not os.path.exists(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(src, target)


def _remove_worktree(git_root: str, todo_id: str):
    repo_name = os.path.basename(git_root)
    path = os.path.join(os.path.dirname(git_root), f"{repo_name}-{todo_id}")
    if not os.path.exists(path):
        click.echo(f"No worktree found at {path}")
        return
    subprocess.check_call(["git", "worktree", "remove", "--force", path])
    branch = f"worktree-{todo_id}"
    subprocess.call(["git", "branch", "-D", branch])
    click.echo(f"Removed worktree and branch {branch}")


@click.command('dev')
@click.argument('todo_id')
@click.option('--clear', is_flag=True, help='Start a fresh chat session')
@click.option('--follow', '-f', is_flag=True, help='Follow output stream after submitting')
@click.option('--no-worktree', is_flag=True, help='Skip worktree creation, use cwd')
@click.option('--clean', is_flag=True, help='Remove worktree and exit')
@click.option('--message', '-m', default=None, help='Continue message (default: "Continue working on this task.")')
@click.option('--mode', type=click.Choice(['plan', 'implement']), default=None, help='Plan or implement mode')
@click.option('--bot', '-b', default='claude-code', help='Bot name')
@click.option('--vm', default='default', help='VM name')
def chat_dev(todo_id: str, clear: bool, follow: bool, no_worktree: bool, clean: bool, message: str, mode: str, bot: str, vm: str):
    """Start a dev chat session linked to a todo item."""
    # Handle --clean: remove worktree and exit
    if clean:
        git_root = _git_root()
        _remove_worktree(git_root, todo_id)
        return

    # 1. Fetch todo
    try:
        resp = api_request("GET", "/api/todo/detail", params={"todo_id": todo_id})
        todo = resp.json()
    except Exception as e:
        click.echo(f"Error fetching todo: {e}", err=True)
        raise click.Abort()

    click.echo(f"Todo: {todo['name']} [{todo['status']}]")

    # 2. Determine work_dir (worktree or cwd)
    if no_worktree:
        work_dir = os.getcwd()
    else:
        git_root = _git_root()
        work_dir = _create_worktree(git_root, todo_id)
        click.echo(f"Worktree: {work_dir}")

    # 3. Resume vs new chat
    chat_ids = todo.get('chat_ids') or []
    post_hooks = _build_post_hooks(todo, todo_id, mode, no_worktree)

    if chat_ids and not clear:
        chat_id = chat_ids[-1]
        prompt = message or "Continue working on this task."
        api_request("POST", "/api/chat/message", json={
            "chat_id": chat_id, "prompt": prompt, "bot_name": bot, "work_dir": work_dir,
            "post_hooks": post_hooks,
        })
        click.echo(f"Resumed chat {chat_id}")
    else:
        prompt = _build_prompt(todo, mode)
        resp = api_request("POST", "/api/chat", json={
            "prompt": prompt, "bot_name": bot, "work_dir": work_dir,
            "post_hooks": post_hooks,
        })
        chat_id = resp.json()["chat_id"]

        chat_ids.append(chat_id)
        api_request("POST", "/api/todo/update", json={
            "todo_id": todo_id, "chat_ids": chat_ids,
        })
        click.echo(f"Created chat {chat_id}")

    if not follow:
        return

    # 4. Follow mode: stream output and interactive loop
    display_manager = DisplayManager()
    input_manager = InputManager(display_manager.console)
    last_index = 0

    last_index, interrupted = _stream_and_handle(chat_id, display_manager, last_index)

    while not interrupted:
        try:
            user_input, is_multiline, num_lines = input_manager.get_input()
        except KeyboardInterrupt:
            break

        if input_manager.is_exit_command(user_input):
            break

        if not user_input:
            continue

        clear_lines = num_lines + 2 if is_multiline else 1
        sys.stdout.write("\033[A\033[2K" * clear_lines)
        sys.stdout.flush()

        api_request("POST", "/api/chat/message", json={
            "chat_id": chat_id, "prompt": user_input, "bot_name": bot, "work_dir": work_dir,
        })

        last_index, interrupted = _stream_and_handle(chat_id, display_manager, last_index)
        if interrupted:
            break
