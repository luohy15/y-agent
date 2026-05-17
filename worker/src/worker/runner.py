"""Run a single chat through the agent loop, writing messages to DB."""

import os
import re
import tempfile
from urllib.parse import urlparse

from loguru import logger

from storage.entity.dto import Message
from storage.service import chat as chat_service

import agent.config as agent_config
from agent.ec2_wake import ensure_and_touch_vm


def _latest_user_text_and_images(messages) -> tuple[str, list]:
    """Return the latest user message text plus image paths, preserving text-only behavior."""
    for msg in reversed(messages):
        if msg.role == "user":
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            return content, list(msg.images or [])
    return "", []


def message_callback(chat_id: str, message: Message):
    logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
    chat_service.append_message_sync(chat_id, message)


def check_interrupted(chat_id: str) -> bool:
    c = chat_service.get_chat_by_id_sync(chat_id)
    return c.interrupted if c else False


def make_steer_checker(chat_id: str, initial_message_ids: set, previously_consumed: set = None):
    """Create a function that checks for new user messages (steer) in the chat.

    Returns list of (text, id, images) tuples for messages added after the worker started.
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
                steer_messages.append((content, msg.id, list(msg.images or [])))
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
    """Resolve Telegram target for a chat. Returns (bot_token, tg_chat_id, topic_id) or None.

    A chat with no topic (e.g. legacy / pre-topic chats) never routes to Telegram.
    """
    from storage.service.telegram import resolve_target

    if not chat.topic:
        return None
    return resolve_target(user_id, topic=chat.topic)


def _send_telegram_photo_reference(bot_token: str, tg_chat_id, image_path: str, caption: str | None, topic_id=None, vm_config=None, ssh_client=None) -> bool:
    from storage.util import send_telegram_photo

    parsed = urlparse(image_path)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        send_telegram_photo(bot_token, tg_chat_id, image_path, caption=caption, message_thread_id=topic_id)
        return True
    if scheme == "s3":
        logger.warning("telegram photo: skipping legacy s3 image ref {}", image_path)
        return False

    suffix = os.path.splitext(image_path)[1] or ".jpg"
    if ssh_client is not None:
        with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
            sftp = ssh_client.open_sftp()
            try:
                sftp.get(image_path, image_file.name)
            finally:
                sftp.close()
            image_file.flush()
            send_telegram_photo(bot_token, tg_chat_id, image_file.name, caption=caption, message_thread_id=topic_id)
        return True

    if vm_config is None:
        logger.warning("telegram photo: cannot fetch local image without vm_config: {}", image_path)
        return False

    ensure_and_touch_vm(vm_config)
    from agent.ssh_pool import SSHPool

    pool = SSHPool()
    try:
        client = pool.get_or_create(vm_config)
        return _send_telegram_photo_reference(bot_token, tg_chat_id, image_path, caption, topic_id=topic_id, vm_config=vm_config, ssh_client=client)
    finally:
        pool.close_all()


def _consolidate_turn_images(chat) -> bool:
    """Move current-turn assistant images onto the turn result message."""
    turn_messages = []
    for msg in reversed(chat.messages):
        if msg.role == "user":
            break
        if msg.role == "assistant":
            turn_messages.append(msg)
    if not turn_messages:
        return False

    turn_messages.reverse()
    aggregated = []
    seen = set()
    has_images = False
    for msg in turn_messages:
        for image_path in list(msg.images or []):
            has_images = True
            if image_path in seen:
                continue
            seen.add(image_path)
            aggregated.append(image_path)

    if not has_images:
        return False

    result_msg = None
    for msg in reversed(turn_messages):
        if isinstance(msg.content, str) and msg.content.strip():
            result_msg = msg
            break
    if result_msg is None:
        result_msg = turn_messages[-1]

    mutated = False
    for msg in turn_messages:
        if msg is result_msg:
            continue
        if msg.images:
            msg.images = []
            mutated = True

    if list(result_msg.images or []) != aggregated:
        result_msg.images = aggregated
        mutated = True

    return mutated


def _send_telegram_user_message(chat, user_id: int, vm_config=None, ssh_client=None) -> None:
    """Send the last user message to Telegram immediately (before agent runs)."""
    from storage.util import send_telegram_message
    from storage.repository.user import get_user_by_id

    target = _resolve_telegram_target(chat, user_id)
    if not target:
        return
    bot_token, tg_chat_id, topic_id = target

    for msg in reversed(chat.messages):
        if msg.role != "user":
            continue
        if msg.source == 'telegram':
            break

        content = msg.content if isinstance(msg.content, str) else ""
        text = content.strip()
        images = list(msg.images or [])
        if not text and not images:
            break

        if text and not text.startswith('[trace:'):
            user = get_user_by_id(user_id)
            display_name = (user.username or user.email.split('@')[0]) if user else 'unknown'
            text = f"{display_name}: {text}"

        if images:
            for index, image_path in enumerate(images):
                _send_telegram_photo_reference(bot_token, tg_chat_id, image_path, caption=text if index == 0 and text else None, topic_id=topic_id, vm_config=vm_config, ssh_client=ssh_client)
        elif text:
            send_telegram_message(bot_token, tg_chat_id, text, topic_id)
        break


def _send_telegram_reply(chat, user_id: int, trace_id: str = None, vm_config=None, ssh_client=None) -> None:
    """Send assistant reply to Telegram, routing by topic."""
    from storage.util import send_telegram_message

    target = _resolve_telegram_target(chat, user_id)
    if not target:
        return
    bot_token, tg_chat_id, topic_id = target

    reply_text = None
    images = []
    for msg in reversed(chat.messages):
        if msg.role == "user":
            break
        if msg.role != "assistant":
            continue
        if isinstance(msg.content, str) and msg.content.strip():
            reply_text = msg.content.strip()
            images = list(msg.images or [])
            break

    if not reply_text:
        for msg in reversed(chat.messages):
            if msg.role == "user":
                break
            if msg.role == "assistant":
                images = list(msg.images or [])
                if images:
                    break

    if images:
        sent_count = 0
        for index, image_path in enumerate(images):
            if _send_telegram_photo_reference(bot_token, tg_chat_id, image_path, caption=reply_text if index == 0 and reply_text else None, topic_id=topic_id, vm_config=vm_config, ssh_client=ssh_client):
                sent_count += 1
        logger.info("telegram reply: sent {} photos to topic={} tg_chat_id={}", sent_count, chat.topic, tg_chat_id)
    elif reply_text:
        send_telegram_message(bot_token, tg_chat_id, reply_text, topic_id)
        logger.info("telegram reply: sent to topic={} tg_chat_id={}", chat.topic, tg_chat_id)


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, topic: str = None, skill: str = None, backend: str = None) -> str:
    """Execute a chat round. Always runs in detached tmux mode, returns 'detached'.

    bot_name, user_id, vm_name, work_dir, and post_hooks are passed from the queue message.
    backend overrides bot_config.backend for routing (e.g. 'claude_code', 'codex', 'gemini_cli').
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

    # Persist trace context on the chat. Root-topic chats (today: 'manager')
    # deliberately don't carry a trace_id: a root is a long-lived inbox that
    # participates in many traces over its lifetime, so binding it to a single
    # trace would be wrong. The data model has one trace_id column per chat, so
    # we just skip persisting on root and let trace context flow through the
    # per-message metadata instead. A proper many-to-many chat↔trace table is
    # the right long-term shape but is deferred (see plan-1876 §4).
    from storage.repository import chat as chat_repo
    if trace_id and chat.topic != 'manager' and not chat.trace_id:
        chat.trace_id = trace_id
    if topic and not chat.topic:
        chat.topic = topic
    elif not topic and chat.topic:
        topic = chat.topic
        logger.info("Using topic from chat: {}", topic)
    if skill and not chat.skill:
        chat.skill = skill
    # Default skill = topic for non-root topics. Covers chats created outside
    # /api/chat/notify (e.g. Telegram forum-topic chats) where skill wasn't supplied.
    if not chat.skill and chat.topic and chat.topic != "manager":
        chat.skill = chat.topic

    # Reset interrupted flag and mark as running
    chat.interrupted = False
    chat.running = True
    await chat_repo.save_chat_by_id(chat)

    # Send user message to Telegram immediately (before agent runs)
    try:
        vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
        _send_telegram_user_message(chat, user_id, vm_config=vm_config)
    except Exception as e:
        logger.exception("telegram user message failed: {}", e)

    if chat.bot_name:
        if bot_name and bot_name != chat.bot_name:
            logger.warning(
                "Ignoring bot_name change for chat {}: existing={} requested={}",
                chat_id, chat.bot_name, bot_name,
            )
        bot_name = chat.bot_name
        logger.info("Using bot_name from chat: {}", bot_name)

    bot_config = agent_config.resolve_bot_config(user_id, bot_name, backend=chat.backend or backend)
    if chat.backend:
        logger.info("Using backend from chat: {}", chat.backend)
    elif backend:
        logger.info("Using backend from queue: {}", backend)
    logger.info("Resolved bot config: name={} backend={} model={}", bot_config.name, bot_config.backend or bot_config.api_type, bot_config.model)

    # Persist routing identity on first run only. A chat's backend is fixed for
    # the lifetime of the chat so changing the user's default bot does not move
    # existing conversations between agent backends.
    if not chat.backend:
        chat.backend = bot_config.backend or bot_config.api_type
    if not chat.bot_name:
        chat.bot_name = bot_config.name
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
    user_prompt, user_images = _latest_user_text_and_images(messages)

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
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "-r", session_id, "--permission-mode", "bypassPermissions", "--tools", "Bash,Edit,Glob,Grep,Read,Skill,TodoWrite,Write"]
    else:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions", "--tools", "Bash,Edit,Glob,Grep,Read,Skill,TodoWrite,Write"]
        session_id = None

    if model:
        cmd.extend(["--model", model])
    if chat.skill and not resume:
        cmd.extend(["--append-system-prompt", f"IMPORTANT: Before doing anything else, you MUST use the Skill tool to load the '{chat.skill}' skill."])

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
            env["Y_TOPIC"] = topic
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



def build_codex_resume_cmd(thread_id: str, model: str = None) -> list:
    """`codex exec resume` command for a known thread (used on fresh resume + steer restart)."""
    cmd = ["codex", "exec", "resume", thread_id, "--json", "--dangerously-bypass-approvals-and-sandbox"]
    if model:
        cmd.extend(["-m", model])
    return cmd


def build_codex_env(bot_config, chat_id: str = None, trace_id: str = None,
                    topic: str = None, last_message_id: str = None) -> dict:
    """Codex subprocess env: OpenAI auth + trace/topic vars (mirrors claude_code env)."""
    env = {}
    if bot_config.api_key:
        env["OPENAI_API_KEY"] = bot_config.api_key
    if chat_id:
        env["Y_CHAT_ID"] = chat_id
    if trace_id:
        env["Y_TRACE_ID"] = trace_id
    if topic:
        env["Y_TOPIC"] = topic
    if last_message_id:
        env["Y_MESSAGE_ID"] = last_message_id
    return env


def build_gemini_resume_cmd(session_id: str, model: str = None) -> list:
    """Gemini CLI resume command for a known session."""
    cmd = ["gemini", "--resume", session_id, "--output-format", "stream-json", "--yolo", "--skip-trust"]
    if model:
        cmd.extend(["-m", model])
    return cmd


def build_gemini_env(bot_config, chat_id: str = None, trace_id: str = None,
                     topic: str = None, last_message_id: str = None) -> dict:
    """Gemini CLI subprocess env: Gemini auth + trace/topic vars."""
    env = {}
    if bot_config.api_key:
        env["GEMINI_API_KEY"] = bot_config.api_key
    if chat_id:
        env["Y_CHAT_ID"] = chat_id
    if trace_id:
        env["Y_TRACE_ID"] = trace_id
    if topic:
        env["Y_TOPIC"] = topic
    if last_message_id:
        env["Y_MESSAGE_ID"] = last_message_id
    return env


def _build_codex_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for codex. Returns dict with all params needed to run."""
    messages = list(chat.messages)

    # Extract the latest user message as the prompt
    user_prompt, user_images = _latest_user_text_and_images(messages)

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
        cmd = build_codex_resume_cmd(thread_id, model)
    else:
        cmd = ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox"]
        thread_id = None
        if cwd:
            cmd.extend(["-C", cwd])
        if model:
            cmd.extend(["-m", model])

    # Skill loading: codex exec has no --append-system-prompt equivalent, so
    # prepend the skill-load instruction to the prompt (only on a fresh run).
    if chat.skill and not resume:
        user_prompt = (
            f"IMPORTANT: Before doing anything else, you MUST use the Skill tool "
            f"to load the '{chat.skill}' skill.\n\n{user_prompt}"
        )

    env = build_codex_env(bot_config, chat_id, trace_id, topic, last_message_id)

    return {
        "prompt": user_prompt,
        "images": user_images,
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


def _build_gemini_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for Gemini CLI."""
    messages = list(chat.messages)

    user_prompt, user_images = _latest_user_text_and_images(messages)

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None

    session_id = chat.external_id
    resume = bool(session_id) and chat.work_dir == cwd

    if resume and session_id:
        cmd = build_gemini_resume_cmd(session_id, model)
    else:
        cmd = ["gemini", "--output-format", "stream-json", "--yolo", "--skip-trust"]
        session_id = None
        if model:
            cmd.extend(["-m", model])

    if chat.skill and not resume:
        user_prompt = (
            f"IMPORTANT: Before doing anything else, you MUST use the Skill tool "
            f"to load the '{chat.skill}' skill.\n\n{user_prompt}"
        )

    env = build_gemini_env(bot_config, chat_id, trace_id, topic, last_message_id)

    return {
        "prompt": user_prompt,
        "images": user_images,
        "cmd": cmd,
        "env": env if env else None,
        "cwd": cwd,
        "vm_config": vm_config,
        "session_id": session_id,
        "resume": resume,
        "last_message_id": last_message_id,
        "model": model,
        "messages": messages,
    }



async def _start_detached(chat, chat_id: str, user_id: int, bot_config,
                           vm_name: str = None, work_dir: str = None,
                           post_hooks: list = None, trace_id: str = None,
                           topic: str = None) -> None:
    """Start claude-code, codex, or Gemini CLI as a detached tmux process on EC2.

    Called from run_chat after chat loading, trace setup, and running flag are done.
    Starts tmux, registers in DynamoDB, returns immediately.
    Monitoring happens in the handler event loop.
    """
    from agent.ec2_wake import ensure_and_touch_vm
    from worker.process_manager import register_process

    # Build params based on backend type
    effective_backend = bot_config.backend or bot_config.api_type
    if effective_backend == "codex":
        params = _build_codex_params(chat, chat_id, user_id, bot_config,
                                      vm_name=vm_name, work_dir=work_dir,
                                      trace_id=trace_id, topic=topic)
    elif effective_backend == "gemini_cli":
        params = _build_gemini_params(chat, chat_id, user_id, bot_config,
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

    # Start detached tmux session (backend-specific launcher)
    if effective_backend == "codex":
        from agent.codex import start_detached_codex_ssh
        session_id = await start_detached_codex_ssh(
            cmd=params["cmd"],
            prompt=params["prompt"],
            cwd=cwd,
            chat_id=chat_id,
            vm_config=params["vm_config"],
            env=params["env"],
            images=params.get("images"),
        )
    elif effective_backend == "gemini_cli":
        from agent.gemini_cli import start_detached_gemini_ssh
        session_id = await start_detached_gemini_ssh(
            cmd=params["cmd"],
            prompt=params["prompt"],
            cwd=cwd,
            chat_id=chat_id,
            vm_config=params["vm_config"],
            env=params["env"],
            images=params.get("images"),
        )
    else:
        from agent.claude_code import start_detached_ssh
        session_id = await start_detached_ssh(
            cmd=params["cmd"],
            prompt=params["prompt"],
            cwd=cwd,
            chat_id=chat_id,
            vm_config=params["vm_config"],
            env=params["env"],
            images=params.get("images"),
        )

    logger.info("_start_detached: tmux started chat_id={} session_id={}", chat_id, session_id)

    # Register in DynamoDB for monitoring
    register_process(
        chat_id=chat_id, user_id=user_id, vm_name=params["vm_config"].name,
        bot_name=bot_config.name, trace_id=trace_id, topic=topic,
        post_hooks=post_hooks, work_dir=cwd, session_id=session_id,
        backend_type=effective_backend,
        initial_msg_count=len(chat.messages),
    )
