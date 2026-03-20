"""Run a single chat through the agent loop, writing messages to DB."""

import os
import re
import subprocess
from typing import List

from loguru import logger

from storage.entity.dto import Message
from storage.service import chat as chat_service
from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

import agent.config as agent_config
from agent.ec2_wake import ensure_and_touch_vm
from agent.loop import run_agent_loop
from agent.tools import get_tools_map, get_openai_tools


def message_callback(chat_id: str, message: Message):
    logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
    chat_service.append_message_sync(chat_id, message)


def check_interrupted(chat_id: str) -> bool:
    c = chat_service.get_chat_by_id_sync(chat_id)
    return c.interrupted if c else False



def _run_post_hooks(chat, user_id: int, post_hooks: list, trace_id: str = None) -> None:
    """Execute post-completion hooks."""
    for hook in post_hooks:
        hook_type = hook.get("type")
        try:
            if hook_type == "commit_and_merge":
                _hook_commit_and_merge(chat.work_dir, hook, user_id)
            elif hook_type == "save_plan_to_todo":
                _hook_save_plan_to_todo(chat, hook, user_id)
            else:
                logger.warning("Unknown post_hook type: {}", hook_type)
        except Exception as e:
            logger.exception("Post hook {} failed: {}", hook_type, e)


def _hook_commit_and_merge(work_dir: str, hook: dict, user_id: int = None) -> None:
    """Stage, commit, rebase onto main, and fast-forward main.

    Resolves worktree from DB via service layer, then commit + merge + cleanup.
    """
    from storage.service import dev_worktree as wt_service

    worktree_name = hook.get("worktree_name")
    if not worktree_name:
        logger.warning("commit_and_merge: missing worktree_name")
        return

    if not user_id:
        logger.error("commit_and_merge: missing user_id")
        return

    wt = wt_service.get_worktree_by_name(user_id, worktree_name)
    if not wt:
        logger.error("commit_and_merge: worktree '{}' not found in DB", worktree_name)
        return
    work_dir = wt.worktree_path
    project_path = wt.project_path
    branch = wt.branch
    commit_msg = worktree_name

    git = ["git", "-C", work_dir]

    status = subprocess.run(git + ["status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        logger.info("commit_and_merge: no changes to commit")
        return

    subprocess.check_call(git + ["add", "-A"])
    subprocess.check_call(git + ["commit", "-m", commit_msg])
    logger.info("commit_and_merge: committed")

    # Rebase current branch onto main, then fast-forward main
    subprocess.check_call(git + ["rebase", "main"])
    logger.info("commit_and_merge: rebased onto main")

    subprocess.check_call(["git", "-C", project_path, "merge", "--ff-only", branch])
    logger.info("commit_and_merge: fast-forwarded main to {}", branch)
    # Clean up worktree and registry
    subprocess.check_call(["git", "-C", project_path, "worktree", "remove", work_dir])
    subprocess.call(["git", "-C", project_path, "branch", "-d", branch])
    logger.info("commit_and_merge: removed worktree and branch {}", branch)
    wt_service.remove_worktree(user_id, wt.worktree_id)
    logger.info("commit_and_merge: removed '{}' from DB", worktree_name)


def _hook_save_plan_to_todo(chat, hook: dict, user_id: int) -> None:
    """Extract plan file path from last assistant message and save to todo progress."""
    from storage.service import todo as todo_service
    todo_id = hook.get("todo_id")
    if not todo_id:
        return

    plan_path = None
    for msg in reversed(chat.messages):
        if msg.role == "assistant":
            content = msg.content if isinstance(msg.content, str) else ""
            paths = re.findall(r'(/[^\s\n`"\']+\.md)', content)
            if paths:
                plan_path = paths[-1]
            break

    if plan_path:
        todo_service.update_todo(user_id, todo_id, progress=plan_path)
        logger.info("save_plan_to_todo: saved plan path {} to todo {}", plan_path, todo_id)


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, skill: str = None) -> None:
    """Execute a chat round. bot_name, user_id, vm_name, work_dir, and post_hooks are passed from the queue message."""
    logger.info("run_chat start chat_id={} bot_name={} user_id={} vm_name={} work_dir={} post_hooks={}", chat_id, bot_name, user_id, vm_name, work_dir, post_hooks)

    # Load chat from DB (with user_id access check)
    chat = await chat_service.get_chat(user_id, chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return

    # Fallback: read active_trace_id from chat if not passed via queue
    if not trace_id and chat.active_trace_id:
        trace_id = chat.active_trace_id
        logger.info("Using active_trace_id from chat: {}", trace_id)

    # Persist trace context on the chat
    from storage.repository import chat as chat_repo
    if trace_id:
        chat.active_trace_id = trace_id
        if not chat.trace_ids:
            chat.trace_ids = [trace_id]
        elif trace_id not in chat.trace_ids:
            chat.trace_ids.append(trace_id)
    if skill and chat.skill != skill:
        chat.skill = skill

    # Reset interrupted flag and mark as running
    chat.interrupted = False
    chat.running = True
    await chat_repo.save_chat_by_id(chat)

    bot_config = agent_config.resolve_bot_config(user_id, bot_name)
    logger.info("Resolved bot config: name={} api_type={} model={}", bot_config.name, bot_config.api_type, bot_config.model)

    # Route to Claude Code worker or agent loop based on api_type
    error_occurred = False
    try:
        if bot_config.api_type == "claude-code":
            await _run_chat_claude_code(chat, chat_id, user_id, bot_config, vm_name=vm_name, work_dir=work_dir, trace_id=trace_id, skill=skill)
        else:
            await _run_chat_agent_loop(chat, chat_id, user_id, bot_config, vm_name=vm_name, work_dir=work_dir)
    except Exception:
        error_occurred = True
        raise
    finally:
        # Mark chat as no longer running
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            await chat_repo.save_chat_by_id(fresh)
            # Send assistant reply to Telegram if chat has a channel
            if not fresh.interrupted and not error_occurred:
                try:
                    from storage.util import parse_telegram_channel_id, get_telegram_bot_token, send_telegram_message
                    tg = parse_telegram_channel_id(fresh.channel_id)
                    if tg:
                        group_id, topic_id = tg
                        reply_text = None
                        for msg in reversed(fresh.messages):
                            if msg.role == "assistant" and isinstance(msg.content, str) and msg.content.strip():
                                reply_text = msg.content.strip()
                                break
                        if reply_text:
                            if trace_id:
                                web_url = os.environ.get("Y_AGENT_WEB_URL", "https://yovy.app")
                                reply_text += f"\n\n🔗 {web_url}/trace/{trace_id}"
                            bot_token = get_telegram_bot_token()
                            if bot_token:
                                send_telegram_message(bot_token, group_id, reply_text, topic_id)
                                logger.info("telegram reply: sent to channel={}", fresh.channel_id)
                except Exception as e:
                    logger.exception("telegram reply failed: {}", e)
            # Execute post hooks if chat completed (not interrupted)
            if not fresh.interrupted and post_hooks:
                logger.info("Running {} post hooks for chat {}", len(post_hooks), chat_id)
                _run_post_hooks(fresh, user_id, post_hooks, trace_id=trace_id)


async def _run_chat_agent_loop(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None) -> None:
    """Run chat through the custom agent loop."""
    provider = agent_config.make_provider(bot_config)

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    ensure_and_touch_vm(vm_config)
    tools_map = get_tools_map(vm_config)
    openai_tools = get_openai_tools(vm_config)
    system_prompt = await agent_config.build_system_prompt(vm_config)
    logger.info("Loaded {} tools, system_prompt length={}", len(tools_map), len(system_prompt) if system_prompt else 0)

    messages: List[Message] = list(chat.messages)
    logger.info("Loaded {} messages from chat {}", len(messages), chat_id)

    result = await run_agent_loop(
        provider=provider,
        messages=messages,
        system_prompt=system_prompt,
        tools_map=tools_map,
        openai_tools=openai_tools,
        message_callback=lambda msg: message_callback(chat_id, msg),
        check_interrupted_fn=lambda: check_interrupted(chat_id),
    )

    logger.info("run_chat finished chat_id={} status={}", chat_id, result.status)


async def _run_chat_claude_code(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, skill: str = None) -> None:
    """Run chat through Claude Code CLI with stateful session resume.

    First message creates a new session. Subsequent messages resume via
    session_id stored in chat.external_id.
    """
    from agent.claude_code import run_claude_code

    messages: List[Message] = list(chat.messages)
    logger.info("Loaded {} messages from chat {}", len(messages), chat_id)

    # Extract the latest user message as the prompt
    user_prompt = ""
    user_images = None
    for msg in reversed(messages):
        if msg.role == "user":
            user_prompt = msg.content if isinstance(msg.content, str) else str(msg.content)
            user_images = msg.images
            break

    if not user_prompt:
        logger.error("No user message found in chat {}", chat_id)
        return

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    ensure_and_touch_vm(vm_config)
    logger.info("Resolved vm config: name={} vm_name={} work_dir={}", vm_config.name, vm_config.vm_name, vm_config.work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None  # treat empty string as None
    cb = lambda msg: message_callback(chat_id, msg)
    interrupted_fn = lambda: check_interrupted(chat_id)

    # Resume existing session only if work_dir matches (session files are path-specific)
    session_id = chat.external_id
    if session_id and chat.work_dir != cwd:
        logger.info("claude-code work_dir mismatch (was {}, now {}), aborting", chat.work_dir, cwd)
        return
    resume = bool(session_id)
    logger.info("claude-code start chat_id={} session_id={} resume={} prompt={}", chat_id, session_id, resume, user_prompt[:200])

    result = await run_claude_code(
        prompt=user_prompt,
        message_callback=cb,
        cwd=cwd,
        session_id=session_id,
        resume=resume,
        last_message_id=last_message_id,
        check_interrupted_fn=interrupted_fn,
        model=model,
        vm_config=vm_config,
        api_base_url=bot_config.base_url if bot_config.base_url else None,
        api_key=bot_config.api_key if bot_config.api_key else None,
        images=user_images,
        chat_id=chat_id,
        trace_id=trace_id,
        skill=skill,
    )
    logger.info("claude-code done status={} session_id={} cost={}", result.status, result.session_id, result.cost_usd)

    # Surface error status as a visible message to the user
    if result.status == "error":
        error_text = result.result_text or "Claude Code exited with an error."
        error_msg = Message(
            id=generate_message_id(),
            role="assistant",
            content=error_text,
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        )
        cb(error_msg)

    # Save session_id and work_dir for future resume
    # Reload fresh chat from DB to avoid overwriting messages appended via callback
    if result.session_id:
        fresh_chat = await chat_service.get_chat_by_id(chat_id)
        if fresh_chat:
            fresh_chat.external_id = result.session_id
            fresh_chat.work_dir = cwd
            from storage.repository import chat as chat_repo
            await chat_repo.save_chat_by_id(fresh_chat)

