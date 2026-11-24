"""Run a single chat through the agent loop, writing messages to DB."""

import asyncio
import mimetypes
import os
import re
import threading

from loguru import logger

from agent.telegram_delivery import send_telegram_photo_reference
from storage.dto.bot import provider_base_url
from storage.entity.dto import BotConfig, Message, trailing_user_messages
from storage.dto.chat import validate_launch_env
from storage.service import chat as chat_service

import agent.config as agent_config


# Roles an inline (non-agentic) backend accepts in its request body.
INLINE_ALLOWED_ROLES = {"system", "user", "assistant"}

# Fixed built-in tool subset for the `claude -p` launch.
# ToolSearch prevents a deferred placeholder that OpenRouter rejects with 400.
CLAUDE_TOOLS_ALLOWLIST = "Bash,Edit,Glob,Grep,Read,Skill,TodoWrite,ToolSearch,Write"

ARTIFACT_FENCE_RE = re.compile(
    r"```(?P<lang>mermaid|vega-lite|artifact-svg)[^\n`]*\n.*?```",
    re.IGNORECASE | re.DOTALL,
)
ARTIFACT_PLACEHOLDERS = {
    "mermaid": "[diagram]",
    "vega-lite": "[chart]",
    "artifact-svg": "[svg]",
}


REASONING_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}
CODEX_REASONING_EFFORT_LEVELS = {"low", "medium", "high", "xhigh"}
SUPPORTED_REASONING_EFFORT_BACKENDS = agent_config.SUPPORTED_REASONING_EFFORT_BACKENDS


def explicit_launch_effort(messages) -> str | None:
    """Newest explicit effort among this launch's inputs, or None.

    Does not look at older turns and does not check the backend. Invalid text
    still raises: an explicit value is never dropped silently.
    """
    reasoning_effort = None
    for msg in messages:
        if getattr(msg, "reasoning_effort", None) is not None:
            reasoning_effort = str(msg.reasoning_effort).lower()
    if reasoning_effort is None:
        return None
    if reasoning_effort not in REASONING_EFFORT_LEVELS:
        raise ValueError(f"Unsupported reasoning effort '{reasoning_effort}'; expected low, medium, high, xhigh, or max")
    return reasoning_effort


def resolve_reasoning_effort(messages, backend: str) -> str | None:
    """Resolve and validate the newest explicit effort among these messages."""
    reasoning_effort = explicit_launch_effort(messages)
    if reasoning_effort is None:
        return None
    if backend not in SUPPORTED_REASONING_EFFORT_BACKENDS:
        raise ValueError(f"reasoning_effort is only supported for claude_code and codex, not {backend}")
    if backend == "codex" and reasoning_effort not in CODEX_REASONING_EFFORT_LEVELS:
        raise ValueError(
            f"Codex does not support reasoning_effort '{reasoning_effort}'; expected low, medium, high, or xhigh"
        )
    return reasoning_effort


def select_run_inputs(messages, continuation_from_id=None, handled_input_ids=None) -> list:
    """The user messages this run is being started to answer, in stored order.

    Default (a fresh turn): every trailing user message, so anything a previous
    turn left unanswered at the tail is folded in.

    Continuation (`continuation_from_id` set): every unanswered user message
    from the previous run's first input onward, *including* ones that already
    have assistant or tool output after them. The incident shape is
    `initial user, late user, old assistant`, which a trailing-suffix scan
    misses entirely. Selection is re-evaluated here, against the chat as loaded
    at launch, so a message accepted between the closeout decision and this
    launch is picked up too instead of being treated as pre-existing.
    """
    if not continuation_from_id:
        return list(trailing_user_messages(messages))
    handled = set(handled_input_ids or ())
    start = next((i for i, m in enumerate(messages) if m.id == continuation_from_id), None)
    if start is None:
        return list(trailing_user_messages(messages))
    return [m for m in messages[start:]
            if m.role == "user" and m.id and m.id not in handled]


def with_codex_skill_preamble(prompt: str, skill: str = None, resume: bool = False) -> str:
    """Fresh Codex launches have no native skill flag. A resume keeps the thread's prompt."""
    if skill and not resume:
        return (
            "IMPORTANT: Before doing anything else, read "
            f"~/.agents/skills/{skill}/SKILL.md and follow it.\n\n{prompt}"
        )
    return prompt


def codex_resume_thread(stored_backend, external_id, work_dir_matches: bool):
    """Thread id to resume, or None. A foreign backend raises and does not clear the id."""
    if stored_backend and stored_backend != "codex":
        raise agent_config.BackendMismatchError(chat_backend=stored_backend, other_backend="codex")
    if external_id and work_dir_matches:
        return external_id
    return None


def render_file_references(paths) -> str:
    """One text line per stored file. Empty input is an empty string.

    Files stay text. They are not image content blocks: a PDF or other
    non-image would be mislabeled by the image path.
    """
    lines = []
    for path in paths or []:
        name = os.path.basename(path) or str(path)
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        lines.append(f"[attached file] {name} ({mime}) at {path}")
    return "\n".join(lines)


def _prompt_from_inputs(selected) -> tuple[str, list]:
    """Concatenated text plus merged image paths for one launch prompt."""
    texts = []
    images = []
    files = []
    for msg in selected:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if content:
            texts.append(content)
        images.extend(msg.images or [])
        files.extend(getattr(msg, "files", None) or [])
    text = "\n\n".join(texts)
    refs = render_file_references(files)
    if refs:
        text = f"{text}\n\n{refs}" if text else refs
    return text, images


def message_callback(chat_id: str, message: Message, user_id: int = None):
    logger.info("Event: role={} tool={} content_length={}", message.role, message.tool, len(message.content) if message.content else 0)
    chat_service.append_message_sync(chat_id, message, user_id=user_id)


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
                    refs = render_file_references(getattr(msg, "files", None) or [])
                    if refs:
                        content = f"{content}\n\n{refs}" if content else refs
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
    """Resolve Telegram target for a chat. Returns (bot_token, tg_chat_id) or None.

    Only the manager role (the owner's DM) is eligible for automatic
    session-reply delivery. Non-manager named sessions and anonymous chats
    never route here; their detail surface is web, not Telegram.
    """
    from storage.service.telegram import resolve_target

    if chat.role != "manager":
        return None
    return resolve_target(user_id, role=chat.role)


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


def manager_delivery_plan(role, source) -> tuple[bool, bool]:
    """Return gateway (mirror, reply) flags; WeChat-origin replies use only the outbox."""
    return role == "manager" and source not in ("wechat", "telegram"), role == "manager" and source != "wechat"


def _send_manager_text(user_id, text, kind):
    from storage.service import gateway

    result = gateway.send(user_id, text)
    if result.ok:
        logger.info("manager {} accepted via {}", kind, result.channel)
    else:
        logger.warning("manager {} gateway send failed for user {}", kind, user_id)


def _send_manager_user_message(chat, user_id, vm_name, work_dir):
    from storage.repository.user import get_user_by_id

    msg = next((msg for msg in reversed(chat.messages) if msg.role == "user"), None)
    if not msg or not manager_delivery_plan(chat.role, msg.source)[0]:
        return
    text = msg.content.strip() if isinstance(msg.content, str) else ""
    if text:
        if not text.startswith('[trace:'):
            user = get_user_by_id(user_id)
            display_name = (user.username or user.email.split('@')[0]) if user else 'unknown'
            text = f"{display_name}: {text}"
        _send_manager_text(user_id, text, "mirror")

    if msg.images and (target := _resolve_telegram_target(chat, user_id)):
        vm_config = agent_config.resolve_vm_config(user_id, vm_name, work_dir=work_dir)
        for image_path in msg.images:
            _send_telegram_photo_reference(*target, image_path, vm_config=vm_config)


def _deliver_manager_reply(chat, user_id: int, vm_config=None, ssh_client=None) -> bool:
    from storage.service.wechat import enqueue_reply

    user_msg = next((msg for msg in reversed(chat.messages) if msg.role == "user"), None)
    if not user_msg or chat.role != "manager":
        return False
    if not manager_delivery_plan(chat.role, user_msg.source)[1]:
        enqueue_reply(chat, user_id)
        return False

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

    if reply_text:
        _send_manager_text(user_id, strip_artifact_fences_for_telegram(reply_text), "reply")
    if images:
        delivered = set(target_message.telegram_delivered_images or [])
        images = [image_path for image_path in images if image_path not in delivered]

    if images and (target := _resolve_telegram_target(chat, user_id)):
        delivered_now = []
        for image_path in images:
            if _send_telegram_photo_reference(*target, image_path, vm_config=vm_config, ssh_client=ssh_client):
                delivered_now.append(image_path)
        return _append_delivered_images(target_message, delivered_now)
    return False


def _build_inline_messages(chat) -> list[dict]:
    messages = []
    for msg in chat.messages:
        if msg.role not in INLINE_ALLOWED_ROLES:
            continue
        if not isinstance(msg.content, str):
            continue
        content = msg.content.strip()
        if not content:
            continue
        messages.append({"role": msg.role, "content": content})
    return messages


def _inline_runner(backend: str):
    """Return the inline (non-agentic) runner for a backend value, or None.

    Imports stay lazy so a claude_code turn never pulls an HTTP backend in.
    """
    if not backend:
        return None
    if backend == "perplexity":
        from agent.perplexity import run_perplexity
        return run_perplexity
    if backend == "openai":
        from agent.openai_chat import run_openai
        return run_openai
    if backend.startswith("xai_"):
        from agent.xai_search import SEARCH_TOOLS, run_xai_search
        if backend in SEARCH_TOOLS:
            return run_xai_search
    return None


async def _run_inline(chat, chat_id: str, user_id: int, bot_config, backend: str,
                      post_hooks: list = None, trace_id: str = None,
                      role: str = None) -> None:
    """Run one turn on an inline backend and close the chat out.

    perplexity, openai and the xai_* search backends differ only in the
    callable, so message shaping, the running flag, manager reply delivery and the
    post-hooks live here once.
    """
    from storage.repository import chat as chat_repo

    run_backend = _inline_runner(backend)
    if not run_backend:
        raise ValueError(f"No inline runner for backend '{backend}'")

    messages = _build_inline_messages(chat)
    if not messages or messages[-1]["role"] != "user":
        logger.error("No latest user message found for inline backend {} chat {}", backend, chat_id)
        chat.running = False
        await chat_repo.save_chat_by_id(chat)
        return

    error_message = None
    try:
        await run_backend(
            messages,
            bot_config,
            lambda msg: message_callback(chat_id, msg),
            chat_id=chat_id,
            trace_id=trace_id,
            role=role,
        )
    except Exception as e:
        # run_chat's handler only appends its error message while the chat is
        # still running, and the clause below clears that flag first, so an
        # inline failure has to record its own message or the turn ends with no
        # assistant reply at all (a --wait caller just blocks until timeout).
        from storage.util import generate_message_id, get_unix_timestamp, get_utc_iso8601_timestamp
        logger.exception("Inline backend {} failed for chat {}: {}", backend, chat_id, e)
        error_message = Message(
            id=generate_message_id(),
            role="assistant",
            content=f"Backend call failed: {type(e).__name__}: {str(e)}",
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
        )
        raise
    finally:
        fresh = await chat_service.get_chat_by_id(chat_id)
        if fresh:
            fresh.running = False
            if error_message is not None:
                fresh.messages.append(error_message)
            await chat_repo.save_chat_by_id(fresh)

    fresh = await chat_service.get_chat_by_id(chat_id)
    if not fresh:
        return

    if not fresh.interrupted:
        chat_service.mark_chat_completion_unread(user_id, chat_id)
        try:
            if _deliver_manager_reply(fresh, user_id):
                await chat_repo.save_chat_by_id(fresh)
        except Exception as e:
            logger.exception("manager reply failed: {}", e)

        if post_hooks:
            _run_post_hooks(fresh, user_id, post_hooks, trace_id=trace_id)


def _launch_auth_mode(user_id: int, chat, backend: str = None) -> str | None:
    if _inline_runner(backend):
        return None
    from agent.chat_target import layout
    return layout(user_id, getattr(chat, "execution_target", None)).auth_mode or "relay"


def _resolve_rebot_target(user_id: int, bot_name: str, tier: str, chat_id: str, current_bot: str,
                          auth_mode: str = "relay", effort: str = None):
    """Resolve a mid-chat bot change, or None when the request cannot be honored.

    Only an affirmative pin counts as a re-bot. resolve_bot_config never fails a
    request: an unknown name, a disabled bot, or a name outside the requested
    tier all fall back to the tier2 pool, and that bot is claude_code too, so
    the caller's backend check would pass and the chat would be moved onto a bot
    nobody asked for. Resolving the pin on its own keeps "honored"
    distinguishable from "fell back". Subscription pins are the exception:
    an eligible pin excluded by its tier filter uses the tier2 subscription
    fallback, while auth ineligibility and explicit effort failures abort.

    A raising pin (a broken alias chain) is swallowed here rather than left to
    run_chat's outer handler: that handler's hand-built fallback config carries
    no model and no credentials, so the turn would run degraded. Returning None
    instead sends the caller down the ordinary sticky path, which re-resolves
    the chat's own bot with its real config.
    """
    try:
        requested = agent_config.resolve_pinned_bot_config(user_id, bot_name, tier=tier, auth_mode=auth_mode)
        if requested is None and tier and auth_mode == "subscription":
            # An eligible pin outside its requested tier loses the pin, not
            # its auth eligibility. Use the same tier2 fallback as a fresh run.
            requested = agent_config.resolve_bot_config(
                user_id, bot_name, tier=tier, effort=effort, auth_mode=auth_mode,
            )
    except (agent_config.BotAuthModeError, agent_config.EffortCapabilityError):
        raise
    except Exception as e:
        logger.warning(
            "Ignoring bot_name change for chat {}: resolving requested={} raised {}: {}; keeping existing={}",
            chat_id, bot_name, type(e).__name__, e, current_bot,
        )
        return None
    if not requested:
        logger.warning(
            "Ignoring bot_name change for chat {}: requested={} (tier={}) is not a runnable bot "
            "(unknown, disabled, or outside that tier); keeping existing={}",
            chat_id, bot_name, tier, current_bot,
        )
    return requested


def _declared_efforts(bot_config) -> list:
    from storage.dto.bot import effective_effort_levels
    return effective_effort_levels(bot_config)


def _abort_unlaunched(chat, chat_id: str, user_id: int, exc: Exception) -> None:
    """Stop a run that never spawned. Routing is left as it was."""
    from storage.repository import chat as chat_repo
    from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
    error_text = f"Backend launch failed: {type(exc).__name__}: {exc}"

    def fail_launch(current):
        if current.running and current.run_seq == chat.run_seq:
            current.running = False
            current.messages.append(Message(
                id=generate_message_id(), role="assistant", content=error_text,
                timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
            ))

    chat_repo.mutate_chat_locked(chat_id, fail_launch, user_id=user_id)


async def run_chat(user_id: int, chat_id: str, bot_name: str = None, bot_tier: str = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, role: str = None, skill: str = None, resume_5xx_retries: int = 0, run_seq: int = None, continuation_from_id: str = None, handled_input_ids=None, codex_refusal_retries: int = 0) -> str:
    """Execute a chat round. Inline backends run in-process; claude_code, codex and pi detach to tmux.

    bot_name, user_id, vm_name, work_dir, and post_hooks are passed from the queue message.
    The launch backend is chat.backend, or the resolved bot's preferred backend when
    the chat has none yet. A queued backend override is not accepted.

    `run_seq` is the reservation this entry is claiming (see
    `chat_repo.claim_chat_run`): a second delivery of the same reservation is
    dropped here rather than starting a second backend. `continuation_from_id` /
    `handled_input_ids` scope the prompt when a closeout relaunched this run to
    answer input the previous one did not.
    """
    logger.info("run_chat start chat_id={} bot_name={} user_id={} vm_name={} work_dir={} post_hooks={}", chat_id, bot_name, user_id, vm_name, work_dir, post_hooks)

    from storage.repository import chat as chat_repo

    # Claim the reservation before touching anything: an unclaimed duplicate
    # must not even re-persist routing identity.
    if not chat_repo.claim_chat_run(user_id, chat_id, run_seq):
        logger.info("run_chat skipped chat_id={}: run_seq={} already claimed", chat_id, run_seq)
        return "done"

    # Load chat from DB (with user_id access check)
    chat = await chat_service.get_chat(user_id, chat_id)
    if not chat:
        logger.error("Chat {} not found", chat_id)
        return "done"

    receipt = chat.closeout_receipt or {}
    if receipt.get("run_seq") == run_seq and receipt.get("pending_ids"):
        continuation_from_id = receipt["pending_ids"][0]
        handled_input_ids = receipt.get("handled_ids", [])
        resume_5xx_retries = receipt.get("resume_5xx_retries", 0)
        post_hooks = receipt.get("post_hooks")
        if isinstance(post_hooks, str):
            import json
            post_hooks = json.loads(post_hooks)

    # Fallback: read trace_id from chat if not passed via queue
    if not trace_id and chat.trace_id:
        trace_id = chat.trace_id
        logger.info("Using trace_id from chat: {}", trace_id)

    # Persist trace context on the chat. Root-role chats (today: 'manager')
    # deliberately don't carry a trace_id: a root is a long-lived inbox that
    # participates in many traces over its lifetime, so binding it to a single
    # trace would be wrong. The data model has one trace_id column per chat, so
    # we just skip persisting on root and let trace context flow through the
    # per-message metadata instead. A proper many-to-many chat↔trace table is
    # the right long-term shape but is deferred (see plan-1876 §4).
    chat, _ = chat_repo.accept_or_start_chat(
        user_id, chat_id, trace_id=trace_id, role=role, skill=skill,
    )
    role = chat.role
    skill = chat.skill
    if chat.interrupted:
        chat_repo.mutate_chat_locked(
            chat_id, lambda current: setattr(current, "running", False)
            if current.run_seq == chat.run_seq and current.interrupted else None,
            user_id=user_id,
        )
        return "done"

    try:
        _send_manager_user_message(chat, user_id, vm_name, work_dir)
    except Exception as e:
        logger.exception("manager user mirror failed: {}", e)

    # A chat is not sticky to its bot: a bot change requested mid-conversation is
    # honored when the request resolves to a runnable bot on the same backend.
    # For claude_code the model and the relay credentials are per-invocation, so
    # the existing session (chat.external_id) resumes fine under a different
    # --model / relay key (smoke-tested in todo 2930). Two things are refused,
    # both by keeping the chat's own bot: a cross-backend change (the inline
    # backends have no session at all, so an agentic chat moved onto one would
    # strand its session), and a request that does not resolve
    # (see _resolve_rebot_target). Refusing keeps the chat's bot. The
    # continuation resolver below still refuses to launch that bot when it is
    # no longer on the stored backend.
    explicit_bot = bot_name
    try:
        prospective = chat.backend
        if not prospective and (bot_name or chat.bot_name):
            try:
                pinned = agent_config.resolve_pinned_bot_config(user_id, bot_name or chat.bot_name)
                prospective = agent_config.preferred_backend(pinned) if pinned else None
            except Exception as exc:
                logger.warning("Cannot inspect pinned backend for chat {}: {}", chat_id, exc)
        auth_mode = _launch_auth_mode(user_id, chat, prospective)
    except Exception as exc:
        _abort_unlaunched(chat, chat_id, user_id, exc)
        raise

    repooled = False
    rebot = bool(chat.bot_name and bot_name and bot_name != chat.bot_name)
    if chat.bot_name and not rebot:
        bot_name = chat.bot_name
        logger.info("Using bot_name from chat: {}", bot_name)

    # Effort is taken from this launch's inputs, not the whole history, and is
    # gated before routing is persisted. A failure here must not become the
    # synthetic fallback bot.
    selected_inputs = select_run_inputs(list(chat.messages), continuation_from_id, handled_input_ids)
    try:
        explicit_effort = explicit_launch_effort(selected_inputs)
    except ValueError as exc:
        _abort_unlaunched(chat, chat_id, user_id, exc)
        raise

    # Guard bot resolution: a bad bot field/column (e.g. a new column not yet
    # migrated) must not crash the core chat chain. On any failure, fall back to
    # a hand-built default bot so the conversation keeps running. Explicit effort,
    # an auth-mode miss, a cross-backend continuation, and a missing per-user
    # relay credential fail the launch instead of running on a bot that was not
    # asked for.
    from storage.crypto.tenant import TenantCryptoError
    from storage.service.relay_credential import RelayCredentialMissing, resolve_for_launch

    try:
        if rebot:
            requested = _resolve_rebot_target(
                user_id, bot_name, bot_tier, chat_id, chat.bot_name,
                auth_mode=auth_mode, effort=explicit_effort,
            )
            if requested and explicit_effort and explicit_effort not in _declared_efforts(requested):
                raise agent_config.EffortCapabilityError(explicit_effort, requested.name)
            requested_names = agent_config.entry_names(requested) if requested else []
            if not requested:
                if explicit_effort:
                    raise agent_config.EffortCapabilityError(explicit_effort, bot_name)
                rebot = False
            elif chat.backend and chat.backend not in requested_names:
                logger.warning(
                    "Refusing cross-backend bot change for chat {}: existing={} backend={} requested={} backends={}",
                    chat_id, chat.bot_name, chat.backend, bot_name, requested_names,
                )
                rebot = False
            else:
                bot_config = requested
                logger.info(
                    "Re-botting chat {}: {} -> {} (backends {})",
                    chat_id, chat.bot_name, requested.name, requested_names,
                )
            if not rebot:
                bot_name = chat.bot_name
        if not rebot:
            if auth_mode == "subscription" and chat.bot_name and not explicit_bot:
                sticky = agent_config.resolve_pinned_bot_config(user_id, chat.bot_name)
                if sticky is None or not agent_config.bot_supports_auth_mode(sticky, auth_mode):
                    bot_name = None
                    repooled = True
            if chat.backend and bot_name and not chat.bot_name:
                # A creation-time -b alias is not in the universe; resolve it to
                # its target so the pinned backend runs the bot the caller named.
                pinned_target = agent_config.resolve_pinned_bot_config(
                    user_id, bot_name, auth_mode=auth_mode,
                )
                if pinned_target is not None:
                    bot_name = pinned_target.name
            if chat.backend:
                bot_config = agent_config.resolve_continuation_bot_config(
                    user_id, chat_id, chat_backend=chat.backend, bot_name=bot_name,
                    tier=bot_tier, effort=explicit_effort, auth_mode=auth_mode,
                )
            else:
                bot_config = agent_config.resolve_bot_config(
                    user_id, bot_name, tier=bot_tier,
                    effort=explicit_effort, auth_mode=auth_mode,
                )
        entry = agent_config.launch_entry(chat.backend, bot_config)
        launch = entry["backend"]
        if auth_mode == "subscription":
            if chat.backend and chat.backend != "claude_code":
                raise agent_config.BotAuthModeError(
                    f"subscription auth runs claude_code only, not {launch}"
                )
            entry = agent_config.launch_entry("claude_code", bot_config)
            launch = entry["backend"]
        if explicit_effort:
            resolve_reasoning_effort(selected_inputs, launch)
        bot_config = resolve_for_launch(user_id, bot_config, entry)
        entry = agent_config.launch_entry(launch, bot_config)
        launch = entry["backend"]
    except Exception as e:
        if explicit_effort or isinstance(e, (
            agent_config.BotAuthModeError,
            agent_config.BackendMismatchError,
            RelayCredentialMissing,
            TenantCryptoError,
        )):
            _abort_unlaunched(chat, chat_id, user_id, e)
            raise
        # The fallback config below is synthetic, so it must never be persisted
        # as an accepted re-bot, no matter what later edits raise inside the try.
        rebot = False
        repooled = False
        fallback_backend = chat.backend or "claude_code"
        logger.exception(
            "Bot resolve failed for chat {} (user_id={} bot_name={} backend={}); "
            "falling back to default bot backend={}: {}",
            chat_id, user_id, bot_name, chat.backend, fallback_backend, e,
        )
        bot_config = BotConfig(name=bot_name or fallback_backend, backend=fallback_backend)
        entry = agent_config.launch_entry(chat.backend, bot_config)
        launch = entry["backend"]
    if chat.backend:
        logger.info("Using backend from chat: {}", chat.backend)
    resolved_tier = agent_config.served_tier(bot_config, bot_tier, auth_mode=auth_mode)
    logger.info("Resolved bot config: name={} backend={} model={} tier={}", bot_config.name, bot_config.backend or bot_config.api_type, bot_config.model, resolved_tier)

    from storage.service.resume_gate import (
        decision_clock, effective_limit, limit_bounds, policy_refusal, resolve_measurement,
    )
    measurement = None
    current_limit = None
    pending_limit = None
    if chat.backend == "claude_code" and chat.external_id:
        pending_ids = [message.id for message in selected_inputs if getattr(message, "id", None)]
        boundary_reliable = all(getattr(message, "id", None) for message in selected_inputs)
        current_limit, _pending_limit = limit_bounds(user_id, chat)
        if rebot or repooled:
            pending_limit = effective_limit(bot_config)
        applicable = current_limit is not None or pending_limit is not None
        measurement = resolve_measurement(
            user_id, chat, pending_input_ids=pending_ids, limit_applicable=applicable,
            boundary_reliable=boundary_reliable, now=decision_clock(),
        )
        # This clock, not the measurement clock above, decides the age. It is
        # still before routing is persisted, and it keeps the original bot.
        refusal = policy_refusal(
            user_id, chat, measurement, current_limit, pending_limit, now=decision_clock(),
        )
    else:
        refusal = None
    if refusal:
        error = RuntimeError(f"chat_read_only:{refusal.reason}: {refusal}")
        _abort_unlaunched(chat, chat_id, user_id, error)
        raise error

    # Routing is computed here but not written yet. The detached path has one
    # more age check after work-dir resolution, and a refusal there must leave
    # the original bot and tier in place. The handoff reads this chat object.
    next_backend = launch
    next_bot = bot_config.name if (not chat.bot_name or rebot or repooled) else chat.bot_name
    next_tier = resolved_tier if (not chat.tier or rebot or repooled) else chat.tier
    try:
        resolve_reasoning_effort(selected_inputs, next_backend)
        if _inline_runner(next_backend):
            chat, _ = _persist_routing(chat_id, user_id, next_backend, next_bot, next_tier)
            await _run_inline(chat, chat_id, user_id, bot_config, next_backend,
                              post_hooks=post_hooks, trace_id=trace_id, role=role)
            return "done"
        await _start_detached(chat, chat_id, user_id, bot_config,
                               vm_name=vm_name, work_dir=work_dir,
                               post_hooks=post_hooks, trace_id=trace_id, role=role,
                               resume_5xx_retries=resume_5xx_retries,
                               continuation_from_id=continuation_from_id,
                               handled_input_ids=handled_input_ids,
                               measurement=measurement,
                               current_limit=current_limit, pending_limit=pending_limit,
                               next_backend=next_backend, next_bot=next_bot, next_tier=next_tier,
                               entry=entry,
                               codex_refusal_retries=codex_refusal_retries)
        return "detached"
    except Exception as e:
        logger.exception("Detached backend launch failed for chat {}: {}", chat_id, e)
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
        error_text = f"Backend launch failed: {type(e).__name__}: {str(e)}"
        def fail_launch(current):
            if current.running and current.run_seq == chat.run_seq:
                current.running = False
                current.messages.append(Message(
                    id=generate_message_id(), role="assistant", content=error_text,
                    timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
                ))
        chat_repo.mutate_chat_locked(chat_id, fail_launch, user_id=user_id)
        raise



# Relay credentials. Subscription mode removes every one of these and unsets
# them in the remote shell so a stale tmux environment cannot keep the relay.
_RELAY_AUTH_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL",
)


def _apply_auth_mode(env: dict, auth_mode: str | None) -> tuple[dict, list]:
    """Return the launch env and the names the remote shell must unset.

    NULL and ``relay`` keep the env (today's relay injection). ``subscription``,
    and any other value, drops the four relay keys and names them for an
    explicit ``unset``, so an unexpected mode never ships relay credentials.
    The input dict is not mutated.
    """
    if auth_mode in (None, "", "relay"):
        return env, []
    cleaned = {key: value for key, value in env.items() if key not in _RELAY_AUTH_KEYS}
    return cleaned, list(_RELAY_AUTH_KEYS)


def _entry_model(entry, bot_config) -> str | None:
    raw = (entry or {}).get("model") or (getattr(bot_config, "model", None) or "")
    model = raw.strip('"').strip() if raw else None
    return model or None


def _build_claude_code_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None,
                              work_dir: str = None, trace_id: str = None, role: str = None,
                              continuation_from_id: str = None,
                              handled_input_ids=None, measurement=None,
                              current_limit=None, pending_limit=None,
                              limits_from_launch: bool = False, entry: dict = None) -> dict:
    """Extract prompt, build cmd/env/cwd for claude-code. Returns dict with all params needed to run."""
    messages = list(chat.messages)

    selected_inputs = select_run_inputs(messages, continuation_from_id, handled_input_ids)
    user_prompt, user_images = _prompt_from_inputs(selected_inputs)
    reasoning_effort = resolve_reasoning_effort(selected_inputs, "claude_code")

    from agent.chat_target import layout
    node = layout(user_id, getattr(chat, "execution_target", None))
    last_message_id = messages[-1].id if messages else None
    cwd = work_dir or node.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = _entry_model(entry, bot_config)

    # Build session_id / resume
    session_id = chat.external_id
    resume = bool(session_id) and chat.work_dir == cwd
    if resume:
        from storage.service.resume_gate import (
            decision_clock, effective_limit, limit_bounds, policy_refusal, resolve_measurement,
        )

        if not limits_from_launch:
            current_limit, _ignored = limit_bounds(user_id, chat)
            supplied = effective_limit(bot_config)
            if bot_config is not None and bot_config.name != chat.bot_name:
                pending_limit = supplied
        if measurement is None:
            measurement = resolve_measurement(
                user_id, chat,
                pending_input_ids=[message.id for message in selected_inputs if message.id],
                limit_applicable=current_limit is not None or pending_limit is not None,
                boundary_reliable=all(message.id for message in selected_inputs),
                now=decision_clock(),
            )
        refusal = policy_refusal(
            user_id, chat, measurement, current_limit, pending_limit, now=decision_clock(),
        )
        if refusal:
            raise RuntimeError(f"chat_read_only:{refusal.reason}: {refusal}")

    # Build cmd
    if resume and session_id:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "-r", session_id, "--permission-mode", "bypassPermissions", "--tools", CLAUDE_TOOLS_ALLOWLIST, "--strict-mcp-config"]
    else:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions", "--tools", CLAUDE_TOOLS_ALLOWLIST, "--strict-mcp-config"]
        session_id = None

    if model:
        cmd.extend(["--model", model])
    if reasoning_effort:
        cmd.extend(["--effort", reasoning_effort])
    if chat.skill and not resume:
        cmd.extend(["--append-system-prompt", f"IMPORTANT: Before doing anything else, you MUST use the Skill tool to load the '{chat.skill}' skill."])

    # Build env
    api_base_url = provider_base_url(
        (entry or {}).get("base_url") or bot_config.base_url, "claude_code", bot_config.api_key,
    ) or None
    api_key = bot_config.api_key if bot_config.api_key else None
    env = {
        **validate_launch_env(getattr(chat, "launch_env", None), strict=False),
        **_workspace_env(),
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        # Agent shells report local time. Bare `date` is Hangzhou, not UTC.
        "TZ": os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai",
        # Global override so bot model config stays a plain model id (no [1m]
        # suffix): Claude Code only fills in this window for model ids it has
        # no registry entry for, so known Claude models are unaffected.
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000",
    }
    if api_base_url:
        env["ANTHROPIC_BASE_URL"] = api_base_url
        # Relay hosts are treated as third-party by the Claude Code CLI,
        # capping natively-1M models (e.g. fable) at a 200k context window.
        # This escape hatch restores the 1M window.
        env["_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"] = "1"
    if api_key:
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
    if chat.context_window and chat.context_window > 0:
        env["Y_CONTEXT_WINDOW"] = str(chat.context_window)
    if chat_id:
        env["Y_CHAT_ID"] = chat_id
    if trace_id:
        env["Y_TRACE_ID"] = trace_id
    if role:
        env["Y_ROLE"] = role
        env["Y_TOPIC"] = role  # transition mirror for old sessions/tools
    if last_message_id:
        env["Y_MESSAGE_ID"] = last_message_id
    env, unset_env = _apply_auth_mode(env, getattr(node, "auth_mode", None))

    return {
        "prompt": user_prompt,
        "images": user_images,
        "input_ids": [m.id for m in selected_inputs if m.id],
        "cmd": cmd,
        "env": env,
        "unset_env": unset_env,
        "cwd": cwd,
        "node": node,
        "session_id": session_id,
        "resume": resume,
        "last_message_id": last_message_id,
        "model": model,
        "messages": messages,
    }



class CodexProviderConfigError(ValueError):
    """A codex bot has no relay base_url or api_key. There is no host-config fallback."""


def build_codex_resume_cmd(thread_id: str, model: str = None, exam_isolation: bool = False) -> list:
    """`codex exec resume` for a known thread. The thread id is argv[3]."""
    cmd = ["codex", "exec", "resume", thread_id, "--json"]
    if not exam_isolation:
        cmd.extend(["--dangerously-bypass-approvals-and-sandbox", "--ignore-user-config"])
    cmd.append("--skip-git-repo-check")
    if model:
        cmd.extend(["-m", model])
    return cmd


def build_codex_provider_args(bot_config, entry: dict = None) -> list:
    """Five `-c` pairs that point Codex at this entry's relay. The key stays off argv."""
    base_url = provider_base_url(
        (entry or {}).get("base_url") or getattr(bot_config, "base_url", None),
        "codex",
        getattr(bot_config, "api_key", None),
    )
    api_key = (getattr(bot_config, "api_key", None) or "").strip()
    missing = []
    if not base_url:
        missing.append("base_url")
    if not api_key:
        missing.append("api_key")
    if missing:
        name = getattr(bot_config, "name", None) or "?"
        raise CodexProviderConfigError(
            f"codex bot {name!r} requires {' and '.join(missing)} (no host config fallback)"
        )
    return [
        "-c", 'model_provider="y-codex"',
        "-c", 'model_providers.y-codex.name="y-codex"',
        "-c", f'model_providers.y-codex.base_url="{base_url}"',
        "-c", 'model_providers.y-codex.wire_api="responses"',
        "-c", 'model_providers.y-codex.env_key="OPENAI_API_KEY"',
    ]


def _workspace_env() -> dict:
    """Forward the deployment workspace. Empty or unset forwards nothing."""
    value = os.environ.get("Y_AGENT_WORKSPACE")
    if value is None or not value.strip():
        return {}
    return {"Y_AGENT_WORKSPACE": value}


def build_codex_env(bot_config, chat_id: str = None, trace_id: str = None,
                    role: str = None, last_message_id: str = None) -> dict:
    """Codex subprocess env. OPENAI_API_KEY is the relay credential, never an argv flag."""
    env = {
        "OPENAI_API_KEY": bot_config.api_key,
        "TZ": os.getenv("Y_AGENT_TIMEZONE") or "Asia/Shanghai",
        **_workspace_env(),
    }
    if chat_id:
        env["Y_CHAT_ID"] = chat_id
    if trace_id:
        env["Y_TRACE_ID"] = trace_id
    if role:
        env["Y_ROLE"] = role
        env["Y_TOPIC"] = role
    if last_message_id:
        env["Y_MESSAGE_ID"] = last_message_id
    return env


def _build_codex_params(chat, chat_id: str, user_id: int, bot_config, vm_name: str = None,
                        work_dir: str = None, trace_id: str = None, role: str = None,
                        continuation_from_id: str = None, handled_input_ids=None,
                        entry: dict = None) -> dict:
    """Extract prompt, build cmd/env/cwd for codex. Resume only when work_dir still matches."""
    messages = list(chat.messages)
    selected_inputs = select_run_inputs(messages, continuation_from_id, handled_input_ids)
    user_prompt, user_images = _prompt_from_inputs(selected_inputs)
    reasoning_effort = resolve_reasoning_effort(selected_inputs, "codex")

    from agent.chat_target import layout
    node = layout(user_id, getattr(chat, "execution_target", None))
    last_message_id = messages[-1].id if messages else None
    cwd = work_dir or node.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    model = _entry_model(entry, bot_config)

    thread_id = codex_resume_thread(getattr(chat, "backend", None) or "codex", chat.external_id, chat.work_dir == cwd)
    resume = bool(thread_id)
    provider_args = build_codex_provider_args(bot_config, entry)
    env = validate_launch_env(getattr(chat, "launch_env", None), strict=False)
    # Exam runs use the sandbox policy in their per-run CODEX_HOME config.
    exam_isolation = env.get("CODEX_ISOLATION") == "exam"

    # The catalog launch uses this window for both report and compaction. A
    # missing row or a failed read leaves the launch on the bundled catalog.
    context_window = None
    if model and not exam_isolation:
        try:
            from storage.service import model_context

            context_window = model_context.get_context_window(model)
        except Exception as exc:
            logger.warning(
                "codex context window query failed: chat_id={} error={}",
                chat_id, type(exc).__name__,
            )

    if resume and thread_id:
        cmd = build_codex_resume_cmd(thread_id, model, exam_isolation=exam_isolation)
        cmd.extend(provider_args)
    else:
        cmd = ["codex", "exec", "--json"]
        if not exam_isolation:
            cmd.extend(["--dangerously-bypass-approvals-and-sandbox", "--ignore-user-config"])
        cmd.append("--skip-git-repo-check")
        thread_id = None
        cmd.extend(provider_args)
        if cwd:
            cmd.extend(["-C", cwd])
        if model:
            cmd.extend(["-m", model])

    if reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])

    user_prompt = with_codex_skill_preamble(user_prompt, chat.skill, resume)

    env.update(build_codex_env(bot_config, chat_id, trace_id, role, last_message_id))
    return {
        "prompt": user_prompt,
        "images": user_images,
        "input_ids": [m.id for m in selected_inputs if m.id],
        "cmd": cmd,
        "env": env,
        "unset_env": [],
        "cwd": cwd,
        "node": node,
        "thread_id": thread_id,
        "session_id": thread_id,
        "resume": resume,
        "last_message_id": last_message_id,
        "model": model,
        "context_window": context_window,
        "messages": messages,
    }


def pi_resume_session(stored_backend, external_id, work_dir_matches):
    """Never pass a foreign backend's handle to pi."""
    if stored_backend and stored_backend != "pi":
        raise agent_config.BackendMismatchError(chat_backend=stored_backend, other_backend="pi")
    return external_id if external_id and work_dir_matches else None


def build_pi_cmd(provider, session_id=None):
    name, definition = provider
    cmd = ["pi", "-p", "--mode", "json", "--approve",
           "--model", f"{name}/{definition['models'][0]['id']}"]
    if session_id:
        cmd.extend(["--session", session_id])
    return cmd


def build_pi_env(bot_config, chat_id=None, trace_id=None, role=None, last_message_id=None):
    env = build_codex_env(bot_config, chat_id, trace_id, role, last_message_id)
    env["Y_PI_API_KEY"] = env.pop("OPENAI_API_KEY")
    return env


def _build_pi_params(chat, chat_id, user_id, bot_config, vm_name=None,
                     work_dir=None, trace_id=None, role=None,
                     continuation_from_id=None, handled_input_ids=None, entry=None):
    from agent.chat_target import layout
    from agent.pi_models import build_pi_provider

    messages = list(chat.messages)
    selected = select_run_inputs(messages, continuation_from_id, handled_input_ids)
    prompt, images = _prompt_from_inputs(selected)
    resolve_reasoning_effort(selected, "pi")
    node = layout(user_id, getattr(chat, "execution_target", None))
    cwd = work_dir or node.work_dir or os.path.expanduser(os.environ.get("VM_WORK_DIR_CLI") or os.getcwd())
    session_id = pi_resume_session(chat.backend, chat.external_id, chat.work_dir == cwd)
    model = _entry_model(entry, bot_config)
    context_window = None
    if model:
        try:
            from storage.service import model_context
            context_window = model_context.get_context_window(model)
        except Exception as exc:
            logger.warning("pi context window query failed: chat_id={} error={}", chat_id, type(exc).__name__)
    provider = build_pi_provider(bot_config, entry, model, context_window)
    cmd = build_pi_cmd(provider, session_id)
    last_message_id = messages[-1].id if messages else None
    env = validate_launch_env(getattr(chat, "launch_env", None), strict=False)
    env.update(build_pi_env(bot_config, chat_id, trace_id, role, last_message_id))
    return {
        "prompt": with_codex_skill_preamble(prompt, chat.skill, bool(session_id)),
        "images": images, "input_ids": [m.id for m in selected if m.id],
        "cmd": cmd, "env": env, "unset_env": [], "cwd": cwd, "node": node,
        "session_id": session_id, "resume": bool(session_id),
        "last_message_id": last_message_id, "model": model,
        "provider": provider, "messages": messages,
    }


def _persist_routing(chat_id, user_id, backend, bot_name, tier):
    """Write the accepted bot only after the last refusal check has passed."""
    from storage.repository import chat as chat_repo

    def patch(current):
        current.backend = backend
        current.bot_name = bot_name
        current.tier = tier
    return chat_repo.mutate_chat_locked(chat_id, patch, user_id=user_id)


async def _start_detached(chat, chat_id: str, user_id: int, bot_config,
                           vm_name: str = None, work_dir: str = None,
                           post_hooks: list = None, trace_id: str = None,
                           role: str = None, resume_5xx_retries: int = 0,
                           continuation_from_id: str = None,
                           handled_input_ids=None, measurement=None,
                           current_limit=None, pending_limit=None,
                           next_backend=None, next_bot=None, next_tier=None,
                           entry: dict = None,
                           codex_refusal_retries: int = 0) -> None:
    """Start claude_code, codex or pi as a detached tmux process on the chat node.

    Called from run_chat after chat loading, trace setup, and running flag are done.
    Starts tmux, registers in DynamoDB, returns immediately.
    Monitoring happens in the handler event loop.
    """
    from agent.ec2_wake import ensure_and_touch_vm
    from worker.process_manager import register_process

    # The caller supplies the launch backend. Do not re-derive it from the bot,
    # whose preferred backend may differ from the chat pin.
    effective_backend = next_backend
    if effective_backend == "codex":
        params = _build_codex_params(chat, chat_id, user_id, bot_config,
                                     vm_name=vm_name, work_dir=work_dir,
                                     trace_id=trace_id, role=role,
                                     continuation_from_id=continuation_from_id,
                                     handled_input_ids=handled_input_ids,
                                     entry=entry)
    elif effective_backend == "pi":
        params = _build_pi_params(chat, chat_id, user_id, bot_config,
                                  vm_name=vm_name, work_dir=work_dir, trace_id=trace_id, role=role,
                                  continuation_from_id=continuation_from_id,
                                  handled_input_ids=handled_input_ids, entry=entry)
    elif effective_backend == "claude_code":
        params = _build_claude_code_params(chat, chat_id, user_id, bot_config,
                                            vm_name=vm_name, work_dir=work_dir,
                                            trace_id=trace_id, role=role,
                                            continuation_from_id=continuation_from_id,
                                            handled_input_ids=handled_input_ids,
                                            measurement=measurement,
                                            current_limit=current_limit, pending_limit=pending_limit,
                                            limits_from_launch=True,
                                            entry=entry)
    else:
        raise ValueError(f"Unsupported detached backend: {effective_backend!r}")
    chat, _ = _persist_routing(
        chat_id, user_id,
        next_backend or chat.backend,
        next_bot or chat.bot_name,
        next_tier or chat.tier,
    )

    if not params["prompt"]:
        logger.error("No user message found in chat {}", chat_id)
        return

    # Set work_dir early
    cwd = params["cwd"]
    if not chat.work_dir:
        from storage.repository import chat as chat_repo
        chat_repo.mutate_chat_locked(
            chat_id, lambda current: setattr(current, "work_dir", current.work_dir or cwd),
            user_id=user_id,
        )

    # Wake the anchor node if needed. It stays the tunnel host when the chat
    # itself runs on a jump node.
    node = params["node"]
    ensure_and_touch_vm(node.anchor)
    from agent.chat_target import apply_launch, prepare_jump_launch
    if node.transport == "jump":
        prepare_jump_launch(node)
    params["cmd"], params["env"] = apply_launch(node, params["cmd"], params["env"])

    # The launch prompt is one input group. Claude completes it from
    # command_lifecycle; Codex completes it from turn.completed. Either way the
    # monitor rebuilds the ledger from this record.
    from agent.input_ledger import COMPLETED, SUBMITTED, native_input_uuid

    input_ids = params["input_ids"]
    launch_uuid = native_input_uuid(chat_id, f"launch:{chat.run_seq}:{input_ids[-1] if input_ids else 'none'}")
    mcp_material = None
    if effective_backend == "codex":
        from agent.codex import start_detached_codex_ssh
        session_id = await start_detached_codex_ssh(
            cmd=params["cmd"],
            prompt=params["prompt"],
            cwd=cwd,
            chat_id=chat_id,
            node=node,
            env=params["env"],
            images=params.get("images"),
            unset_env=params.get("unset_env"),
            model=params.get("model"),
            context_window=params.get("context_window"),
        )
    elif effective_backend == "pi":
        from agent.pi_cli import start_detached_pi_ssh
        session_id = await start_detached_pi_ssh(
            cmd=params["cmd"], prompt=params["prompt"], cwd=cwd, chat_id=chat_id,
            node=node, env=params["env"], images=params.get("images"),
            unset_env=params.get("unset_env"), provider=params["provider"],
        )
    else:
        from agent.claude_code import start_detached_ssh
        from agent.mcp import launch as mcp_launch
        mcp_material = await asyncio.to_thread(mcp_launch.prepare, user_id, chat_id, chat.run_seq)
        try:
            session_id = await start_detached_ssh(
                cmd=params["cmd"],
                prompt=params["prompt"],
                cwd=cwd,
                chat_id=chat_id,
                node=node,
                env=params["env"],
                images=params.get("images"),
                input_uuid=launch_uuid,
                mcp_material=mcp_material,
                unset_env=params.get("unset_env"),
            )
        except Exception:
            mcp_launch.end(mcp_material)
            raise
    if mcp_material is not None and mcp_material.warning:
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
        from storage.repository import chat as chat_repo
        def warn_mcp(current):
            if current.running and current.run_seq == chat.run_seq:
                current.messages.append(Message(
                    id=generate_message_id(), role="assistant", content=mcp_material.warning,
                    timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
                ))
        chat_repo.mutate_chat_locked(chat_id, warn_mcp, user_id=user_id)

    logger.info("_start_detached: tmux started chat_id={} session_id={}", chat_id, session_id)

    # Register in DynamoDB for monitoring
    try:
        register_process(
            chat_id=chat_id, user_id=user_id, vm_name=node.anchor.name,
            bot_name=bot_config.name, trace_id=trace_id, role=role,
            post_hooks=post_hooks, work_dir=cwd, session_id=session_id,
            backend_type=effective_backend,
            model=params.get("model"),
            initial_msg_count=len(chat.messages),
            resume_5xx_retries=resume_5xx_retries,
            input_groups={launch_uuid: input_ids},
            delivery_states={**{mid: COMPLETED for mid in (handled_input_ids or ())},
                             **{message_id: SUBMITTED for message_id in input_ids}},
            scope_first_id=input_ids[0] if input_ids else None,
            initial_message_ids=[m.id for m in chat.messages if m.id],
            run_seq=chat.run_seq,
            mcp_launch_id=mcp_material.launch_id if mcp_material is not None else None,
            target_id=node.name,
            codex_refusal_retries=codex_refusal_retries,
            resume_thread_id=params.get("thread_id") if params.get("resume") else None,
        )
    except Exception as e:
        if mcp_material is not None:
            from agent.mcp import launch as mcp_launch
            mcp_launch.end(mcp_material)
        logger.exception("register_process failed for chat {} (session_id={}): {}", chat_id, session_id, e)
        from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
        from storage.repository import chat as chat_repo
        failure_message = f"Process registration failed: {type(e).__name__}: {str(e)}. The backend session may have started but cannot be monitored."
        def fail_registration(current):
            if current.running and current.run_seq == chat.run_seq:
                current.running = False
                current.messages.append(Message(
                    id=generate_message_id(), role="assistant",
                    content=failure_message,
                    timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
                ))
        chat_repo.mutate_chat_locked(chat_id, fail_registration, user_id=user_id)
        raise
