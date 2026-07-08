"""Run a single chat through the agent loop, writing messages to DB."""

import os
import re
import threading

from loguru import logger

from agent.telegram_delivery import send_telegram_photo_reference
from storage.entity.dto import BotConfig, Message, _throughput_enabled
from storage.service import chat as chat_service

import agent.config as agent_config
from agent.ec2_wake import ensure_and_touch_vm
from agent.pi_models import (
    DEFAULT_BOT_BASE_URL,
    build_pi_models_provider,
    resolve_pi_model_and_provider,
)


# Stock OpenRouter endpoint that BotConfig falls back to when base_url is unset.
# A pi bot left at this default keeps the v1 behavior (provider inferred from the
# `<provider>/<model>` prefix); only an explicitly-configured custom gateway
# triggers models.json custom-provider registration.
DEFAULT_BOT_BASE_URL = BotConfig.__dataclass_fields__["base_url"].default


PERPLEXITY_ALLOWED_ROLES = {"system", "user", "assistant"}
OPENAI_ALLOWED_ROLES = {"system", "user", "assistant"}

# Fixed built-in tool subset shared by the `claude -p` and `claude_tui` launches.
CLAUDE_TOOLS_ALLOWLIST = "Bash,Edit,Glob,Grep,Read,Skill,TodoWrite,Write"

ARTIFACT_FENCE_RE = re.compile(
    r"```(?P<lang>mermaid|vega-lite|artifact-svg)[^\n`]*\n.*?```",
    re.IGNORECASE | re.DOTALL,
)
ARTIFACT_PLACEHOLDERS = {
    "mermaid": "[diagram]",
    "vega-lite": "[chart]",
    "artifact-svg": "[svg]",
}


def _pending_user_text_and_images(messages) -> tuple[str, list]:
    """Return all trailing user messages (since the last non-user message),
    concatenated text plus merged image paths.

    A single trailing user message behaves exactly like the old
    latest-message-only lookup. Gathering all of them recovers a message
    that a prior turn's steer race silently failed to deliver (see
    plan-2662-steer-race.md): the moment any new turn starts, every
    unanswered trailing user message is folded into its prompt.
    """
    trailing = []
    for msg in reversed(messages):
        if msg.role != "user":
            break
        trailing.append(msg)
    trailing.reverse()

    texts = []
    images = []
    for msg in trailing:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if content:
            texts.append(content)
        images.extend(msg.images or [])
    return "\n\n".join(texts), images


def message_callback(chat_id: str, message: Message):
    logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
    chat_service.append_message_sync(chat_id, message)


def strip_artifact_fences_for_telegram(text: str) -> str:
    """Replace web-only artifact fences with compact Telegram placeholders."""
    if not text:
        return text

    def replacement(match):
        lang = match.group("lang").lower()
        return ARTIFACT_PLACEHOLDERS.get(lang, "[artifact]")

    return ARTIFACT_FENCE_RE.sub(replacement, text)


def check_interrupted(chat_id: str) -> bool:
    c = chat_service.get_chat_by_id_sync(chat_id)
    return c.interrupted if c else False


def make_steer_checker(chat_id: str, initial_message_ids: set, previously_consumed: set = None):
    """Create a function that checks for new user messages (steer) in the chat.

    Returns list of (text, id, images) tuples for messages added after the worker started.
    previously_consumed: steer IDs already sent by a previous Lambda, to avoid duplicates.

    A message is claimed (added to `consumed`) as soon as it's discovered, to
    prevent two concurrent callers (the poll loop and a turn-end drain) from
    both picking it up. Claiming is not the same as delivery: the returned
    `check` function exposes an `unclaim(msg_id)` attribute that a caller
    should invoke if it learns delivery actually failed, so the message stays
    available for the next mechanism to pick up (see plan-2662-steer-race.md).
    """
    consumed = set(previously_consumed) if previously_consumed else set()
    lock = threading.Lock()

    def check():
        chat = chat_service.get_chat_by_id_sync(chat_id)
        if not chat:
            return []
        steer_messages = []
        with lock:
            for msg in chat.messages:
                if msg.role == "user" and msg.id not in initial_message_ids and msg.id not in consumed:
                    consumed.add(msg.id)
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    steer_messages.append((content, msg.id, list(msg.images or [])))
        return steer_messages

    def unclaim(msg_id):
        with lock:
            consumed.discard(msg_id)

    check.unclaim = unclaim
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


_send_telegram_photo_reference = send_telegram_photo_reference


def _append_delivered_images(msg, image_paths: list[str]) -> bool:
    existing = list(msg.telegram_delivered_images or [])
    seen = set(existing)
    changed = False
    for image_path in image_paths:
        if image_path in seen:
            continue
        existing.append(image_path)
        seen.add(image_path)
        changed = True
    if changed:
        msg.telegram_delivered_images = existing
    return changed


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


def _send_telegram_reply(chat, user_id: int, trace_id: str = None, vm_config=None, ssh_client=None) -> bool:
    """Send assistant reply to Telegram, routing by topic."""
    from storage.util import send_telegram_message

    target = _resolve_telegram_target(chat, user_id)
    if not target:
        return False
    bot_token, tg_chat_id, topic_id = target

    reply_text = None
    images = []
    target_message = None
    for msg in reversed(chat.messages):
        if msg.role == "user":
            break
        if msg.role != "assistant":
            continue
        if isinstance(msg.content, str) and msg.content.strip():
            reply_text = msg.content.strip()
            images = list(msg.images or [])
            target_message = msg
            break

    if not reply_text:
        for msg in reversed(chat.messages):
            if msg.role == "user":
                break
            if msg.role == "assistant":
                images = list(msg.images or [])
                if images:
                    target_message = msg
                    break

    if target_message is not None and images:
        delivered = set(target_message.telegram_delivered_images or [])
        had_images_before_filter = bool(images)
        images = [image_path for image_path in images if image_path not in delivered]
    else:
        had_images_before_filter = False

    if images:
        sent_count = 0
        delivered_now = []
        reply_caption = strip_artifact_fences_for_telegram(reply_text) if reply_text else None
        for index, image_path in enumerate(images):
            if _send_telegram_photo_reference(bot_token, tg_chat_id, image_path, caption=reply_caption if index == 0 and reply_caption else None, topic_id=topic_id, vm_config=vm_config, ssh_client=ssh_client):
                sent_count += 1
                delivered_now.append(image_path)
        changed = _append_delivered_images(target_message, delivered_now) if target_message is not None else False
        logger.info("telegram reply: sent {} photos to topic={} tg_chat_id={}", sent_count, chat.topic, tg_chat_id)
        return changed
    elif reply_text and not had_images_before_filter:
        send_telegram_message(bot_token, tg_chat_id, strip_artifact_fences_for_telegram(reply_text), topic_id)
        logger.info("telegram reply: sent to topic={} tg_chat_id={}", chat.topic, tg_chat_id)
    return False


def _build_perplexity_messages(chat) -> list[dict]:
    messages = []
    for msg in chat.messages:
        if msg.role not in PERPLEXITY_ALLOWED_ROLES:
            continue
        if not isinstance(msg.content, str):
            continue
        content = msg.content.strip()
        if not content:
            continue
        messages.append({"role": msg.role, "content": content})
    return messages


def _build_openai_messages(chat) -> list[dict]:
    messages = []
    for msg in chat.messages:
        if msg.role not in OPENAI_ALLOWED_ROLES:
            continue
        if not isinstance(msg.content, str):
            continue
        content = msg.content.strip()
        if not content:
            continue
        messages.append({"role": msg.role, "content": content})
    return messages


async def _run_perplexity_inline(chat, chat_id: str, user_id: int, bot_config,
                                 post_hooks: list = None, trace_id: str = None,
                                 topic: str = None) -> None:
    from agent.perplexity import run_perplexity
    from storage.repository import chat as chat_repo
    from storage.repository.chat import set_chat_unread

    messages = _build_perplexity_messages(chat)
    if not messages or messages[-1]["role"] != "user":
        logger.error("No latest user message found for Perplexity chat {}", chat_id)
        chat.running = False
        await chat_repo.save_chat_by_id(chat)
        return

    try:
        await run_perplexity(
            messages,
            bot_config,
            lambda msg: message_callback(chat_id, msg),
            chat_id=chat_id,
            trace_id=trace_id,
            topic=topic,
        )
    finally:
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            await chat_repo.save_chat_by_id(fresh)

    fresh = await chat_service.get_chat_by_id(chat_id)
    if not fresh:
        return

    if not fresh.interrupted:
        set_chat_unread(chat_id, True)
        try:
            if _send_telegram_reply(fresh, user_id, trace_id):
                await chat_repo.save_chat_by_id(fresh)
        except Exception as e:
            logger.exception("telegram reply failed: {}", e)

        if post_hooks:
            _run_post_hooks(fresh, user_id, post_hooks, trace_id=trace_id)


async def _run_openai_inline(chat, chat_id: str, user_id: int, bot_config,
                             post_hooks: list = None, trace_id: str = None,
                             topic: str = None) -> None:
    from agent.openai_chat import run_openai
    from storage.repository import chat as chat_repo
    from storage.repository.chat import set_chat_unread

    messages = _build_openai_messages(chat)
    if not messages or messages[-1]["role"] != "user":
        logger.error("No latest user message found for OpenAI chat {}", chat_id)
        chat.running = False
        await chat_repo.save_chat_by_id(chat)
        return

    try:
        await run_openai(
            messages,
            bot_config,
            lambda msg: message_callback(chat_id, msg),
            chat_id=chat_id,
            trace_id=trace_id,
            topic=topic,
        )
    finally:
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            await chat_repo.save_chat_by_id(fresh)

    fresh = await chat_service.get_chat_by_id(chat_id)
    if not fresh:
        return

    if not fresh.interrupted:
        set_chat_unread(chat_id, True)
        try:
            if _send_telegram_reply(fresh, user_id, trace_id):
                await chat_repo.save_chat_by_id(fresh)
        except Exception as e:
            logger.exception("telegram reply failed: {}", e)

        if post_hooks:
            _run_post_hooks(fresh, user_id, post_hooks, trace_id=trace_id)


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, bot_tier: str = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, topic: str = None, skill: str = None, backend: str = None) -> str:
    """Execute a chat round. Perplexity runs inline; CLI backends detach to tmux.

    bot_name, user_id, vm_name, work_dir, and post_hooks are passed from the queue message.
    backend overrides bot_config.backend for routing (e.g. 'claude_code', 'codex', 'gemini_cli', 'perplexity', 'openai').
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

    # Phase 0: derive tier from skill, with bot_tier (e.g. --tier cli flag)
    # overriding the skill-derived tier. Unlisted skills and no-skill default
    # to tier3.
    effective_tier = agent_config.derive_tier(skill, bot_tier)

    # Guard bot resolution: a bad bot field/column (e.g. a new column not yet
    # migrated) must not crash the core chat chain. On any failure, fall back to
    # a hand-built default bot so the conversation keeps running.
    try:
        bot_config = agent_config.resolve_bot_config(
            user_id, bot_name, backend=chat.backend or backend, tier=effective_tier,
        )
    except Exception as e:
        fallback_backend = chat.backend or backend or "claude_tui"
        logger.exception(
            "Bot resolve failed for chat {} (user_id={} bot_name={} backend={}); "
            "falling back to default bot backend={}: {}",
            chat_id, user_id, bot_name, chat.backend or backend, fallback_backend, e,
        )
        bot_config = BotConfig(name=bot_name or fallback_backend, backend=fallback_backend)
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

    effective_backend = bot_config.backend or bot_config.api_type
    if effective_backend == "perplexity":
        await _run_perplexity_inline(chat, chat_id, user_id, bot_config,
                                     post_hooks=post_hooks, trace_id=trace_id, topic=topic)
        return "done"
    elif effective_backend == "openai":
        await _run_openai_inline(chat, chat_id, user_id, bot_config,
                                 post_hooks=post_hooks, trace_id=trace_id, topic=topic)
        return "done"

    try:
        await _start_detached(chat, chat_id, user_id, bot_config,
                               vm_name=vm_name, work_dir=work_dir,
                               post_hooks=post_hooks, trace_id=trace_id, topic=topic)
        return "detached"
    except Exception as e:
        logger.exception("Detached backend launch failed for chat {}: {}", chat_id, e)
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
        error_text = f"Backend launch failed: {type(e).__name__}: {str(e)}"
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            if fresh.running:
                fresh.running = False
                error_msg = Message(
                    id=generate_message_id(),
                    role="assistant",
                    content=error_text,
                    timestamp=get_utc_iso8601_timestamp(),
                    unix_timestamp=get_unix_timestamp(),
                )
                fresh.messages.append(error_msg)
                await chat_repo.save_chat_by_id(fresh)
                logger.info("Set running=False and appended error message for chat {} after launch failure", chat_id)
        raise



def _build_claude_code_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for claude-code. Returns dict with all params needed to run."""
    messages = list(chat.messages)

    # Extract all trailing user messages as the prompt
    user_prompt, user_images = _pending_user_text_and_images(messages)

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
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "-r", session_id, "--permission-mode", "bypassPermissions", "--tools", CLAUDE_TOOLS_ALLOWLIST, "--strict-mcp-config"]
    else:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions", "--tools", CLAUDE_TOOLS_ALLOWLIST, "--strict-mcp-config"]
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
            # Relay hosts are treated as third-party by the Claude Code CLI,
            # capping natively-1M models (e.g. fable) at a 200k context window.
            # This escape hatch restores the 1M window.
            env["_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"] = "1"
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


def build_codex_provider_args(bot_config) -> list:
    """Per-invocation codex `-c` flags that point codex at the bot's own relay.

    Returns ``[]`` when ``bot_config.base_url`` is empty (fallback to the host
    ``~/.codex/config.toml`` crs provider), preserving every existing codex bot
    with no config change. When ``base_url`` is set, returns the 5 ``-c`` flag
    pairs that define + select a custom ``y-codex`` provider, beating the host
    config. The API key rides on ``OPENAI_API_KEY`` (exported by
    ``build_codex_env``) via ``env_key`` and is sent as ``Authorization: Bearer``,
    so it never lands on the command line. If ``api_key`` is empty we skip the
    injection (and warn), since the provider would have no credential.

    NOTE on the base_url convention: codex treats ``base_url`` as a prefix and
    appends the wire path (``/responses`` for ``wire_api="responses"``). So a
    codex bot's ``base_url`` must be the crs-style prefix (e.g.
    ``https://<relay-host>/openai``), NOT a full endpoint and NOT the claude
    ``ANTHROPIC_BASE_URL`` messages-root semantics.
    """
    base_url = (bot_config.base_url or "").strip()
    if not base_url:
        return []
    if not (bot_config.api_key or "").strip():
        logger.warning(
            "codex bot {} has base_url but empty api_key; skipping provider injection "
            "(falling back to host config.toml)",
            getattr(bot_config, "name", "?"),
        )
        return []
    return [
        "-c", 'model_provider="y-codex"',
        "-c", 'model_providers.y-codex.name="y-codex"',
        "-c", f'model_providers.y-codex.base_url="{base_url}"',
        "-c", 'model_providers.y-codex.wire_api="responses"',
        "-c", 'model_providers.y-codex.env_key="OPENAI_API_KEY"',
    ]


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


def build_pi_resume_cmd(session_id: str, model: str = None, api_key: str = None) -> list:
    """pi resume command for a known session (used on fresh resume + steer restart)."""
    cmd = ["pi", "-p", "--mode", "json", "--session", session_id]
    if model:
        cmd.extend(["--model", model])
    if api_key:
        cmd.extend(["--api-key", api_key])
    return cmd


def build_pi_env(bot_config, chat_id: str = None, trace_id: str = None,
                 topic: str = None, last_message_id: str = None) -> dict:
    """pi subprocess env: trace/topic vars (auth goes via --api-key on the cmd)."""
    env = {}
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

    # Extract all trailing user messages as the prompt
    user_prompt, user_images = _pending_user_text_and_images(messages)

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None

    # Resume support: thread_id stored in chat.external_id
    thread_id = chat.external_id
    resume = bool(thread_id) and chat.work_dir == cwd

    # Per-bot relay override: [] when base_url empty -> host config.toml fallback.
    provider_args = build_codex_provider_args(bot_config)

    # Build cmd (resume subcommand doesn't support -C)
    if resume and thread_id:
        cmd = build_codex_resume_cmd(thread_id, model)
        cmd.extend(provider_args)
    else:
        cmd = ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox"]
        thread_id = None
        cmd.extend(provider_args)
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

    user_prompt, user_images = _pending_user_text_and_images(messages)

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


def _build_pi_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for pi."""
    messages = list(chat.messages)

    user_prompt, user_images = _pending_user_text_and_images(messages)

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None
    api_key = bot_config.api_key or None

    # base_url support: pi cannot point an existing provider at a custom gateway
    # via env, so when a custom (non-default) base_url is configured we register a
    # provider in ~/.pi/agent/models.json (written remotely before launch) and
    # address it as `--model <provider>/<model>`. Auth then lives in the provider
    # entry, so the --api-key flag is dropped to avoid a conflicting credential.
    model, models_provider = resolve_pi_model_and_provider(bot_config, model)
    if models_provider:
        api_key = None

    session_id = chat.external_id
    resume = bool(session_id) and chat.work_dir == cwd

    if resume and session_id:
        cmd = build_pi_resume_cmd(session_id, model, api_key)
    else:
        cmd = ["pi", "-p", "--mode", "json"]
        session_id = None
        if model:
            cmd.extend(["--model", model])
        if api_key:
            cmd.extend(["--api-key", api_key])

    if chat.skill and not resume:
        user_prompt = (
            f"IMPORTANT: Before doing anything else, you MUST use the Skill tool "
            f"to load the '{chat.skill}' skill.\n\n{user_prompt}"
        )

    env = build_pi_env(bot_config, chat_id, trace_id, topic, last_message_id)

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
        "models_provider": models_provider,
    }



def _build_claude_tui_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None, work_dir: str = None, trace_id: str = None, topic: str = None) -> dict:
    """Extract prompt, build cmd/env/cwd for the Claude Code TUI backend.

    Mirrors _build_claude_code_params but targets the interactive TUI: a fresh
    turn gets a generated `--session-id <uuid>`; a continue uses `--resume <uuid>`.
    No `--output-format`/`--input-format` (those are `claude -p` only). Shares the
    `--tools <CLAUDE_TOOLS_ALLOWLIST>` built-in subset with `-p`, plus
    `--strict-mcp-config` to disallow all MCP servers (no `--mcp-config` supplied).
    With no base_url/api_key the launch uses the EC2 subscription login.
    """
    import uuid as _uuid

    messages = list(chat.messages)
    user_prompt, user_images = _pending_user_text_and_images(messages)

    vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
    last_message_id = messages[-1].id if messages else None
    cwd = vm_config.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = bot_config.model.strip('"').strip() if bot_config.model else None
    model = model or None

    session_id = chat.external_id
    resume = bool(session_id) and chat.work_dir == cwd

    if resume and session_id:
        cmd = ["claude", "--resume", session_id, "--permission-mode", "bypassPermissions", "--tools", CLAUDE_TOOLS_ALLOWLIST, "--strict-mcp-config"]
    else:
        session_id = str(_uuid.uuid4())
        resume = False
        cmd = ["claude", "--session-id", session_id, "--permission-mode", "bypassPermissions", "--tools", CLAUDE_TOOLS_ALLOWLIST, "--strict-mcp-config"]

    if model:
        cmd.extend(["--model", model])
    if chat.skill and not resume:
        cmd.extend(["--append-system-prompt", f"IMPORTANT: Before doing anything else, you MUST use the Skill tool to load the '{chat.skill}' skill."])

    # Env: trace/topic/chat vars, plus ANTHROPIC overrides only when explicitly
    # configured (a subscription bot leaves both unset to use the EC2 login).
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
    elif effective_backend == "pi_cli":
        params = _build_pi_params(chat, chat_id, user_id, bot_config,
                                  vm_name=vm_name, work_dir=work_dir,
                                  trace_id=trace_id, topic=topic)
    elif effective_backend == "claude_code":
        params = _build_claude_code_params(chat, chat_id, user_id, bot_config,
                                            vm_name=vm_name, work_dir=work_dir,
                                            trace_id=trace_id, topic=topic)
    else:
        # None / unrecognized backends default to claude_tui (interactive tmux TUI =
        # subscription usage), not claude -p (programmatic -> dedicated credit pool).
        params = _build_claude_tui_params(chat, chat_id, user_id, bot_config,
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
    tui_initial_offset = 0
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
    elif effective_backend == "pi_cli":
        from agent.pi_cli import start_detached_pi_ssh
        session_id = await start_detached_pi_ssh(
            cmd=params["cmd"],
            prompt=params["prompt"],
            cwd=cwd,
            chat_id=chat_id,
            vm_config=params["vm_config"],
            env=params["env"],
            images=params.get("images"),
            models_provider=params.get("models_provider"),
        )
    elif effective_backend == "claude_tui":
        from agent.claude_tui import start_detached_claude_tui_ssh
        session_id, tui_initial_offset = await start_detached_claude_tui_ssh(
            cmd=params["cmd"],
            prompt=params["prompt"],
            cwd=cwd,
            chat_id=chat_id,
            vm_config=params["vm_config"],
            session_id=params["session_id"],
            resume=params["resume"],
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
    try:
        register_process(
            chat_id=chat_id, user_id=user_id, vm_name=params["vm_config"].name,
            bot_name=bot_config.name, trace_id=trace_id, topic=topic,
            post_hooks=post_hooks, work_dir=cwd, session_id=session_id,
            backend_type=effective_backend,
            initial_msg_count=len(chat.messages),
        )
        # claude_tui reads the session JSONL by line offset; start past any
        # pre-existing content (prior turn on resume / launch meta) so the tail
        # only streams this turn's lines.
        if effective_backend == "claude_tui" and tui_initial_offset:
            from worker.process_manager import update_process_offset
            update_process_offset(chat_id=chat_id, offset=tui_initial_offset, session_id=session_id)
    except Exception as e:
        logger.exception("register_process failed for chat {} (session_id={}): {}", chat_id, session_id, e)
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh and fresh.running:
            fresh.running = False
            error_msg = Message(
                id=generate_message_id(),
                role="assistant",
                content=f"Process registration failed: {type(e).__name__}: {str(e)}. The backend session may have started but cannot be monitored.",
                timestamp=get_utc_iso8601_timestamp(),
                unix_timestamp=get_unix_timestamp(),
            )
            fresh.messages.append(error_msg)
            from storage.repository import chat as chat_repo
            await chat_repo.save_chat_by_id(fresh)
        raise
