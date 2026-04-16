"""Run a single chat through the agent loop, writing messages to DB."""

import os
import re

from loguru import logger

from storage.entity.dto import Message
from storage.service import chat as chat_service
from storage.util import generate_id, generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp

import agent.config as agent_config


def message_callback(chat_id: str, message: Message):
    logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
    chat_service.append_message_sync(chat_id, message)


def check_interrupted(chat_id: str) -> bool:
    c = chat_service.get_chat_by_id_sync(chat_id)
    return c.interrupted if c else False


def make_steer_checker(chat_id: str, initial_message_ids: set, previously_consumed: set = None):
    """Create a function that checks for new user messages (steer) in the chat.

    Returns list of (text, id) tuples for messages added after the worker started.
    previously_consumed: steer IDs already sent by a previous Lambda, to avoid duplicates.
    """
    consumed = set(previously_consumed) if previously_consumed else set()

    def check():
        chat = chat_service.get_chat_by_id_sync(chat_id)
        if not chat:
            return []
        steer_messages = []
        for msg in chat.messages:
            if msg.role == "user" and msg.id not in initial_message_ids and msg.id not in consumed:
                consumed.add(msg.id)
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                steer_messages.append((content, msg.id))
        return steer_messages

    return check



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
    """Determine Telegram routing target based on chat role/topic.

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
    if chat.role == 'worker' and chat.topic:
        tg_topic = find_topic_by_name(user_id, chat.topic)
        if not tg_topic or tg_topic.topic_id is None:
            logger.debug("telegram: no tg_topic for topic '{}'", chat.topic)
            return None
        tg_chat_id = tg_topic.group_id
        topic_id = tg_topic.topic_id
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
    """Send assistant reply to Telegram, routing by role/topic."""
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
        logger.info("telegram reply: sent to topic={} tg_chat_id={}", chat.topic, tg_chat_id)


async def _maybe_restart_manager_session(user_id: int, input_tokens: int, context_window: int, num_turns: int = 0) -> None:
    """Auto-restart manager session when context usage exceeds 50% or turns exceed 50.

    Creates a new manager chat placeholder so find_latest_chat_by_topic returns the fresh
    chat for subsequent messages, effectively starting a new Claude Code session.
    """
    usage_ratio = (input_tokens / context_window) if context_window else 0.0
    context_exceeded = context_window and usage_ratio > 0.5
    turns_exceeded = num_turns > 50

    if not context_exceeded and not turns_exceeded:
        logger.info("Manager context usage {:.1%}, turns={}, no restart needed", usage_ratio, num_turns)
        return

    reason = []
    if context_exceeded:
        reason.append(f"context {usage_ratio:.0%}")
    if turns_exceeded:
        reason.append(f"turns {num_turns}")
    reason_str = " & ".join(reason)
    logger.info("Manager restart triggered: {}", reason_str)

    # Create new manager chat with initial message
    new_chat_id = generate_id()
    restart_msg = Message(
        id=generate_message_id(),
        role="user",
        content="load manager skill",
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )
    await chat_service.create_chat(user_id, messages=[restart_msg], chat_id=new_chat_id)

    # Mark role/topic on new chat
    from storage.repository import chat as chat_repo
    new_chat = await chat_service.get_chat_by_id(new_chat_id)
    if new_chat:
        new_chat.role = 'manager'
        new_chat.topic = 'manager'
        await chat_repo.save_chat_by_id(new_chat)

    logger.info("Manager restart: new chat_id={}", new_chat_id)


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, role: str = None, topic: str = None, backend: str = None) -> str:
    """Execute a chat round. Always runs in detached tmux mode, returns 'detached'.

    bot_name, user_id, vm_name, work_dir, and post_hooks are passed from the queue message.
    backend overrides bot_config.api_type for routing (e.g. 'claude_code', 'codex').
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
    if trace_id and role != 'manager':
        chat.trace_id = trace_id
    if role and not chat.role:
        chat.role = role
    elif not role and chat.role:
        role = chat.role
        logger.info("Using role from chat: {}", role)
    if topic and not chat.topic:
        chat.topic = topic
    elif not topic and chat.topic:
        topic = chat.topic
        logger.info("Using topic from chat: {}", topic)

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

    # Persist backend on chat
    chat.backend = bot_config.api_type
    await chat_repo.save_chat_by_id(chat)

    # Always run in detached tmux mode
    await _start_detached(chat, chat_id, user_id, bot_config,
                           vm_name=vm_name, work_dir=work_dir,
                           post_hooks=post_hooks, trace_id=trace_id, topic=topic)
    return "detached"



def _build_claude_code_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
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
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "-r", session_id, "--permission-mode", "bypassPermissions", "--disallowed-tools", "AskUserQuestion,EnterPlanMode"]
    else:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions", "--disallowed-tools", "AskUserQuestion,EnterPlanMode"]
        session_id = None

    if model:
        cmd.extend(["--model", model])
    if topic and topic != "manager" and not resume:
        cmd.extend(["--append-system-prompt", f"IMPORTANT: Before doing anything else, you MUST use the Skill tool to load the '{topic}' skill."])

    # Build env
    env = None
    api_base_url = bot_config.base_url if bot_config.base_url else None
    api_key = bot_config.api_key if bot_config.api_key else None
    if api_base_url or api_key or chat_id or trace_id or topic or last_message_id:
        env = {}
        if api_base_url:
            env["ANTHROPIC_BASE_URL"] = api_base_url
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
        if chat_id:
            env["Y_CHAT_ID"] = chat_id
        if trace_id:
            env["Y_TRACE_ID"] = trace_id
        if topic:
            env["Y_SKILL"] = topic
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



def _build_codex_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
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
        cmd = ["codex", "exec", "resume", thread_id, "--json", "--dangerously-bypass-approvals-and-sandbox"]
    else:
        cmd = ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox"]
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



async def _start_detached(chat, chat_id: str, user_id: int, bot_config,
                           vm_name: str = None, work_dir: str = None,
                           post_hooks: list = None, trace_id: str = None,
                           topic: str = None) -> None:
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
                                      trace_id=trace_id, topic=topic)
    else:
        params = _build_claude_code_params(chat, chat_id, user_id, bot_config,
                                            vm_name=vm_name, work_dir=work_dir,
                                            trace_id=trace_id, topic=topic)

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
        chat_id=chat_id, user_id=user_id, vm_name=params["vm_config"].name,
        bot_name=bot_config.name, trace_id=trace_id, topic=topic,
        post_hooks=post_hooks, work_dir=cwd, session_id=session_id,
        backend_type=bot_config.api_type,
        initial_msg_count=len(chat.messages),
    )

