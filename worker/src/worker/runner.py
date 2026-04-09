"""Run a single chat through the agent loop, writing messages to DB."""

import os
import re

from loguru import logger

from storage.entity.dto import Message
from storage.service import chat as chat_service
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

import agent.config as agent_config
from agent.ec2_wake import ensure_and_touch_vm


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
            if hook_type == "save_plan_to_todo":
                _hook_save_plan_to_todo(chat, hook, user_id)
            else:
                logger.warning("Unknown post_hook type: {}", hook_type)
        except Exception as e:
            logger.exception("Post hook {} failed: {}", hook_type, e)



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


def _resolve_telegram_target(chat, user_id: int):
    """Determine Telegram routing target based on chat skill.

    Returns (bot_token, tg_chat_id, topic_id) or None if no valid target.
    """
    from storage.util import get_telegram_bot_token
    from storage.repository.tg_topic import find_topic_by_name
    from storage.repository.user import get_user_by_id

    bot_token = get_telegram_bot_token()
    if not bot_token:
        return None

    tg_chat_id = None
    topic_id = None
    if chat.skill and chat.skill != 'DM':
        topic = find_topic_by_name(user_id, chat.skill)
        if not topic or topic.topic_id is None:
            logger.debug("telegram: no topic for skill '{}'", chat.skill)
            return None
        tg_chat_id = topic.group_id
        topic_id = topic.topic_id
    else:
        user = get_user_by_id(user_id)
        if not user or not user.telegram_id:
            logger.debug("telegram: no telegram_id for user_id={}", user_id)
            return None
        tg_chat_id = user.telegram_id

    return (bot_token, tg_chat_id, topic_id)


def _send_telegram_user_message(chat, user_id: int) -> None:
    """Send the last user message to Telegram immediately (before agent runs)."""
    from storage.util import send_telegram_message
    from storage.repository.user import get_user_by_id

    target = _resolve_telegram_target(chat, user_id)
    if not target:
        return
    bot_token, tg_chat_id, topic_id = target

    for msg in reversed(chat.messages):
        if msg.role == "user" and isinstance(msg.content, str) and msg.content.strip():
            if msg.source != 'telegram':
                text = msg.content.strip()
                # Prefix with display name for non-notify messages (web-originated)
                if not text.startswith('[trace:'):
                    user = get_user_by_id(user_id)
                    display_name = (user.username or user.email.split('@')[0]) if user else 'unknown'
                    text = f"{display_name}: {text}"
                send_telegram_message(bot_token, tg_chat_id, text, topic_id)
            break


def _send_telegram_reply(chat, user_id: int, trace_id: str = None) -> None:
    """Send assistant reply to Telegram, routing by skill."""
    from storage.util import send_telegram_message

    target = _resolve_telegram_target(chat, user_id)
    if not target:
        return
    bot_token, tg_chat_id, topic_id = target

    # Send assistant reply
    reply_text = None
    for msg in reversed(chat.messages):
        if msg.role == "assistant" and isinstance(msg.content, str) and msg.content.strip():
            reply_text = msg.content.strip()
            break
    if reply_text:
        send_telegram_message(bot_token, tg_chat_id, reply_text, topic_id)
        logger.info("telegram reply: sent to skill={} tg_chat_id={}", chat.skill, tg_chat_id)


async def _maybe_restart_dm_session(user_id: int, input_tokens: int, context_window: int, num_turns: int = 0) -> None:
    """Auto-restart DM session when context usage exceeds 50% or turns exceed 50.

    Creates a new DM chat placeholder so find_chat_by_skill returns the fresh
    chat for subsequent messages, effectively starting a new Claude Code session.
    """
    usage_ratio = (input_tokens / context_window) if context_window else 0.0
    context_exceeded = context_window and usage_ratio > 0.5
    turns_exceeded = num_turns > 50

    if not context_exceeded and not turns_exceeded:
        logger.info("DM context usage {:.1%}, turns={}, no restart needed", usage_ratio, num_turns)
        return

    reason = []
    if context_exceeded:
        reason.append(f"context {usage_ratio:.0%}")
    if turns_exceeded:
        reason.append(f"turns {num_turns}")
    reason_str = " & ".join(reason)
    logger.info("DM restart triggered: {}", reason_str)

    # Create new DM chat with initial message (mirrors y notify DM --new behavior)
    new_chat_id = generate_id()
    restart_msg = Message(
        id=generate_message_id(),
        role="user",
        content="load DM skill",
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )
    await chat_service.create_chat(user_id, messages=[restart_msg], chat_id=new_chat_id)

    # Mark skill on new chat
    from storage.repository import chat as chat_repo
    new_chat = await chat_service.get_chat_by_id(new_chat_id)
    if new_chat:
        new_chat.skill = 'DM'
        await chat_repo.save_chat_by_id(new_chat)

    # Auto-ack (same as DM short-circuit in notify controller)
    ack_msg = Message(
        id=generate_message_id(),
        role="assistant",
        content=f"DM session restarted ({reason_str})",
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )
    await chat_service.append_message(new_chat_id, ack_msg)

    # Send Telegram notification about restart
    try:
        from storage.util import get_telegram_bot_token, send_telegram_message
        from storage.repository.user import get_user_by_id
        bot_token = get_telegram_bot_token()
        if bot_token:
            user = get_user_by_id(user_id)
            if user and user.telegram_id:
                send_telegram_message(bot_token, user.telegram_id, f"DM session restarted ({reason_str})")
    except Exception as e:
        logger.exception("DM restart telegram notify failed: {}", e)

    logger.info("DM restart: new chat_id={}", new_chat_id)


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, skill: str = None, backend: str = None) -> str:
    """Execute a chat round. Returns 'detached' or 'done'.

    bot_name, user_id, vm_name, work_dir, and post_hooks are passed from the queue message.
    backend overrides bot_config.api_type for routing (e.g. 'claude_code', 'codex').
    Routing (detached SSH vs inline) is decided internally after resolving bot/vm config.
    """
    logger.info("run_chat start chat_id={} bot_name={} user_id={} vm_name={} work_dir={} post_hooks={}", chat_id, bot_name, user_id, vm_name, work_dir, post_hooks)

    # Load chat from DB (with user_id access check)
    chat = await chat_service.get_chat(user_id, chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return "done"

    # Fallback: read trace_id from chat if not passed via queue
    if not trace_id and chat.trace_id:
        trace_id = chat.trace_id
        logger.info("Using trace_id from chat: {}", trace_id)

    # Persist trace context on the chat
    from storage.repository import chat as chat_repo
    if trace_id and skill != 'DM':
        chat.trace_id = trace_id
    if skill and not chat.skill:
        chat.skill = skill
    elif not skill and chat.skill:
        skill = chat.skill
        logger.info("Using skill from chat: {}", skill)

    # Reset interrupted flag and mark as running
    chat.interrupted = False
    chat.running = True
    await chat_repo.save_chat_by_id(chat)

    # Send user message to Telegram immediately (before agent runs)
    try:
        _send_telegram_user_message(chat, user_id)
    except Exception as e:
        logger.exception("telegram user message failed: {}", e)

    bot_config = agent_config.resolve_bot_config(user_id, bot_name)
    # Override api_type if backend is explicitly specified
    if backend:
        bot_config.api_type = backend
    logger.info("Resolved bot config: name={} api_type={} model={}", bot_config.name, bot_config.api_type, bot_config.model)

    # Route: SSH claude_code/codex → detached tmux mode (if "detach" feature flag exists)
    # A vm_config named "detach" for this user acts as a feature flag.
    # Present → detached mode; absent → inline (safe fallback).
    if bot_config.api_type in ("claude_code", "codex"):
        vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
        if vm_config.vm_name and vm_config.vm_name.startswith("ssh:"):
            from storage.service import vm_config as vm_service
            if vm_service.get_config(user_id, "detach"):
                await _start_detached(chat, chat_id, user_id, bot_config,
                                       vm_name=vm_name, work_dir=work_dir,
                                       post_hooks=post_hooks, trace_id=trace_id, skill=skill)
                return "detached"

    # Inline mode
    error_occurred = False
    try:
        if bot_config.api_type == "codex":
            await _run_chat_codex(chat, chat_id, user_id, bot_config, vm_name=vm_name, work_dir=work_dir, trace_id=trace_id, skill=skill)
        else:
            await _run_chat_claude_code(chat, chat_id, user_id, bot_config, vm_name=vm_name, work_dir=work_dir, trace_id=trace_id, skill=skill)
    except Exception:
        error_occurred = True
        raise
    finally:
        # Mark chat as no longer running
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            await chat_repo.save_chat_by_id(fresh)
            # Send assistant reply to Telegram based on skill routing
            if not fresh.interrupted and not error_occurred:
                try:
                    _send_telegram_reply(fresh, user_id, trace_id)
                except Exception as e:
                    logger.exception("telegram reply failed: {}", e)
            # Execute post hooks if chat completed (not interrupted)
            if not fresh.interrupted and post_hooks:
                logger.info("Running {} post hooks for chat {}", len(post_hooks), chat_id)
                _run_post_hooks(fresh, user_id, post_hooks, trace_id=trace_id)

    return "done"



def _build_claude_code_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, skill: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for claude-code. Returns dict with all params needed to run."""
    messages = list(chat.messages)

    # Extract the latest user message as the prompt
    user_prompt = ""
    user_images = None
    for msg in reversed(messages):
        if msg.role == "user":
            user_prompt = msg.content if isinstance(msg.content, str) else str(msg.content)
            user_images = msg.images
            break

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None

    # Build session_id / resume
    session_id = chat.external_id
    resume = bool(session_id) and chat.work_dir == cwd

    # Build cmd
    if resume and session_id:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "-r", session_id, "--permission-mode", "bypassPermissions"]
    else:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions"]
        session_id = None

    if model:
        cmd.extend(["--model", model])
    if skill and skill != "DM" and not resume:
        cmd.extend(["--append-system-prompt", f"IMPORTANT: Before doing anything else, you MUST use the Skill tool to load the '{skill}' skill."])

    # Build env
    env = None
    api_base_url = bot_config.base_url if bot_config.base_url else None
    api_key = bot_config.api_key if bot_config.api_key else None
    if api_base_url or api_key or chat_id or trace_id or skill or last_message_id:
        env = {}
        if api_base_url:
            env["ANTHROPIC_BASE_URL"] = api_base_url
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
        if chat_id:
            env["Y_CHAT_ID"] = chat_id
        if trace_id:
            env["Y_TRACE_ID"] = trace_id
        if skill:
            env["Y_SKILL"] = skill
        if last_message_id:
            env["Y_MESSAGE_ID"] = last_message_id

    return {
        "prompt": user_prompt,
        "images": user_images,
        "cmd": cmd,
        "env": env,
        "cwd": cwd,
        "vm_config": vm_config,
        "session_id": session_id,
        "resume": resume,
        "last_message_id": last_message_id,
        "model": model,
        "messages": messages,
    }


async def _run_chat_claude_code(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, skill: str = None) -> None:
    """Run chat through Claude Code CLI with stateful session resume.

    First message creates a new session. Subsequent messages resume via
    session_id stored in chat.external_id.
    """
    from agent.claude_code import run_claude_code

    params = _build_claude_code_params(chat, chat_id, user_id, bot_config,
                                        vm_name=vm_name, work_dir=work_dir,
                                        trace_id=trace_id, skill=skill)

    if not params["prompt"]:
        logger.error("No user message found in chat {}", chat_id)
        return

    cwd = params["cwd"]
    vm_config = params["vm_config"]
    session_id = params["session_id"]
    resume = params["resume"]

    ensure_and_touch_vm(vm_config)
    logger.info("Resolved vm config: name={} vm_name={} work_dir={}", vm_config.name, vm_config.vm_name, vm_config.work_dir)

    cb = lambda msg: message_callback(chat_id, msg)
    interrupted_fn = lambda: check_interrupted(chat_id)

    # Set work_dir early so it persists even if the run is interrupted or errors out
    if not chat.work_dir:
        chat.work_dir = cwd
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat_by_id(chat)

    # work_dir mismatch check (session files are path-specific)
    if chat.external_id and chat.work_dir != cwd:
        error_msg = f"work_dir mismatch: chat has '{chat.work_dir}', got '{cwd}'"
        logger.error("claude-code {}, aborting", error_msg)
        message_callback(chat_id, Message.from_dict({
            "role": "assistant",
            "content": f"Error: {error_msg}. Cannot resume session with a different work_dir.",
        }))
        return

    logger.info("claude-code start chat_id={} session_id={} resume={} prompt={}", chat_id, session_id, resume, params["prompt"][:200])

    result = await run_claude_code(
        prompt=params["prompt"],
        message_callback=cb,
        cwd=cwd,
        session_id=session_id,
        resume=resume,
        last_message_id=params["last_message_id"],
        check_interrupted_fn=interrupted_fn,
        model=params["model"],
        vm_config=vm_config,
        api_base_url=bot_config.base_url if bot_config.base_url else None,
        api_key=bot_config.api_key if bot_config.api_key else None,
        images=params["images"],
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

    # Save session_id and token usage
    # Reload fresh chat from DB to avoid overwriting messages appended via callback
    if result.session_id or result.input_tokens is not None:
        fresh_chat = await chat_service.get_chat_by_id(chat_id)
        if fresh_chat:
            if result.session_id:
                fresh_chat.external_id = result.session_id
            if result.input_tokens is not None:
                fresh_chat.input_tokens = result.input_tokens
                fresh_chat.output_tokens = result.output_tokens
                fresh_chat.cache_read_input_tokens = result.cache_read_input_tokens
                fresh_chat.cache_creation_input_tokens = result.cache_creation_input_tokens
                fresh_chat.context_window = result.context_window
            from storage.repository import chat as chat_repo
            await chat_repo.save_chat_by_id(fresh_chat)

            # Auto-restart DM session if context usage exceeds 50% or turns exceed 50
            if skill == 'DM':
                num_turns = sum(1 for m in fresh_chat.messages if m.role == "user") if fresh_chat.messages else 0
                await _maybe_restart_dm_session(user_id, result.input_tokens or 0, result.context_window or 0, num_turns)


def _build_codex_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, skill: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for codex. Returns dict with all params needed to run."""
    messages = list(chat.messages)

    # Extract the latest user message as the prompt
    user_prompt = ""
    for msg in reversed(messages):
        if msg.role == "user":
            user_prompt = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None

    # Resume support: thread_id stored in chat.external_id
    thread_id = chat.external_id
    resume = bool(thread_id) and chat.work_dir == cwd

    # Build cmd (resume subcommand doesn't support -C)
    if resume and thread_id:
        cmd = ["codex", "exec", "resume", thread_id, "--json", "--full-auto"]
    else:
        cmd = ["codex", "exec", "--json", "--full-auto"]
        thread_id = None
        if cwd:
            cmd.extend(["-C", cwd])
    if model:
        cmd.extend(["-m", model])

    # Build env
    env = {}
    if bot_config.api_key:
        env["OPENAI_API_KEY"] = bot_config.api_key

    return {
        "prompt": user_prompt,
        "cmd": cmd,
        "env": env if env else None,
        "cwd": cwd,
        "vm_config": vm_config,
        "thread_id": thread_id,
        "resume": resume,
        "last_message_id": last_message_id,
        "model": model,
        "messages": messages,
    }


async def _run_chat_codex(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, skill: str = None) -> None:
    """Run chat through OpenAI Codex CLI (codex exec)."""
    from agent.codex import run_codex

    params = _build_codex_params(chat, chat_id, user_id, bot_config,
                                  vm_name=vm_name, work_dir=work_dir,
                                  trace_id=trace_id, skill=skill)

    if not params["prompt"]:
        logger.error("No user message found in chat {}", chat_id)
        return

    cwd = params["cwd"]
    thread_id = params.get("thread_id")
    resume = params.get("resume", False)

    # Set backend and work_dir on chat
    chat.backend = "codex"
    if not chat.work_dir:
        chat.work_dir = cwd
    from storage.repository import chat as chat_repo
    await chat_repo.save_chat_by_id(chat)

    logger.info("codex start chat_id={} thread_id={} resume={} prompt={}", chat_id, thread_id, resume, params["prompt"][:200])

    cb = lambda msg: message_callback(chat_id, msg)
    interrupted_fn = lambda: check_interrupted(chat_id)

    result = await run_codex(
        prompt=params["prompt"],
        message_callback=cb,
        cwd=cwd,
        last_message_id=params["last_message_id"],
        check_interrupted_fn=interrupted_fn,
        model=params["model"],
        api_key=bot_config.api_key if bot_config.api_key else None,
        thread_id=thread_id,
    )

    logger.info("codex done status={} thread_id={}", result.status, result.thread_id)

    # Surface error as visible message
    if result.status == "error":
        error_text = result.result_text or "Codex exited with an error."
        error_msg = Message(
            id=generate_message_id(),
            role="assistant",
            content=error_text,
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        )
        cb(error_msg)

    # Save thread_id (for resume) and token usage
    if result.thread_id or result.input_tokens is not None:
        fresh_chat = await chat_service.get_chat_by_id(chat_id)
        if fresh_chat:
            if result.thread_id:
                fresh_chat.external_id = result.thread_id
            if result.input_tokens is not None:
                fresh_chat.input_tokens = result.input_tokens
                fresh_chat.output_tokens = result.output_tokens
            from storage.repository import chat as chat_repo
            await chat_repo.save_chat_by_id(fresh_chat)


async def _start_detached(chat, chat_id: str, user_id: int, bot_config,
                           vm_name: str = None, work_dir: str = None,
                           post_hooks: list = None, trace_id: str = None,
                           skill: str = None) -> None:
    """Start claude-code or codex as a detached tmux process on EC2.

    Called from run_chat after chat loading, trace setup, and running flag are done.
    Starts tmux, registers in DynamoDB, returns immediately.
    Monitoring happens in the handler event loop.
    """
    from agent.claude_code import start_detached_ssh
    from agent.ec2_wake import ensure_and_touch_vm
    from worker.process_manager import register_process

    # Build params based on backend type
    if bot_config.api_type == "codex":
        params = _build_codex_params(chat, chat_id, user_id, bot_config,
                                      vm_name=vm_name, work_dir=work_dir,
                                      trace_id=trace_id, skill=skill)
    else:
        params = _build_claude_code_params(chat, chat_id, user_id, bot_config,
                                            vm_name=vm_name, work_dir=work_dir,
                                            trace_id=trace_id, skill=skill)

    if not params["prompt"]:
        logger.error("No user message found in chat {}", chat_id)
        return

    # Set work_dir early
    cwd = params["cwd"]
    if not chat.work_dir:
        chat.work_dir = cwd
        from storage.repository import chat as chat_repo
        await chat_repo.save_chat_by_id(chat)

    # Wake EC2 if needed
    ensure_and_touch_vm(params["vm_config"])

    # Start detached tmux session
    session_id = await start_detached_ssh(
        cmd=params["cmd"],
        prompt=params["prompt"],
        cwd=cwd,
        chat_id=chat_id,
        vm_config=params["vm_config"],
        env=params["env"],
    )

    logger.info("_start_detached: tmux started chat_id={} session_id={}", chat_id, session_id)

    # Register in DynamoDB for monitoring
    register_process(
        chat_id=chat_id, user_id=user_id, vm_name=params["vm_config"].vm_name,
        bot_name=bot_config.name, trace_id=trace_id, skill=skill,
        post_hooks=post_hooks, work_dir=cwd, session_id=session_id,
        backend_type=bot_config.api_type,
    )

