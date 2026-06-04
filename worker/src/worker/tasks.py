"""Celery tasks for y-agent worker."""

import asyncio
import uuid

from loguru import logger

from worker.celery_app import app
from worker.monitor import _monitor_loop
from worker.runner import run_chat


async def _run_chat_with_monitor(chat_id, bot_name, user_id, vm_name, work_dir,
                                  post_hooks, trace_id, topic, skill, backend):
    result = await run_chat(
        user_id, chat_id, bot_name=bot_name, vm_name=vm_name, work_dir=work_dir,
        post_hooks=post_hooks, trace_id=trace_id, topic=topic, skill=skill, backend=backend,
    )
    if result in ("detached", "continuation"):
        req_id = f"celery-{uuid.uuid4().hex[:8]}"
        await _monitor_loop(deadline_at=None, lambda_req_id=req_id)


@app.task(name="worker.tasks.process_chat")
def process_chat(chat_id: str, bot_name: str = None, user_id: int = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, topic: str = None, skill: str = None, backend: str = None):
    """Run the agent loop for a chat."""
    try:
        asyncio.run(_run_chat_with_monitor(
            chat_id, bot_name, user_id, vm_name, work_dir,
            post_hooks, trace_id, topic, skill, backend,
        ))
        logger.info("Finished chat {}", chat_id)
    except Exception as e:
        logger.exception("Chat {} failed: {}", chat_id, e)
        # Defense-in-depth: if run_chat raised before setting running=False,
        # the chat would be stuck as running=True. Try to clear it.
        try:
            from storage.service import chat as chat_service
            from storage.repository.chat import _save_chat_by_id_sync
            from storage.util import generate_message_id, get_utc_iso8601_timestamp, get_unix_timestamp
            from storage.entity.dto import Message
            chat = chat_service.get_chat_by_id_sync(chat_id)
            if chat and chat.running:
                chat.running = False
                error_msg = Message(
                    id=generate_message_id(),
                    role="assistant",
                    content=f"Worker process crashed: {type(e).__name__}. The chat service will attempt to recover on the next message.",
                    timestamp=get_utc_iso8601_timestamp(),
                    unix_timestamp=get_unix_timestamp(),
                )
                chat.messages.append(error_msg)
                _save_chat_by_id_sync(chat)
                logger.info("Defense-in-depth: cleared running=True for stuck chat {}", chat_id)
        except Exception as inner_e:
            logger.exception("Failed to clear stuck running state for chat {}: {}", chat_id, inner_e)


@app.task(name="worker.tasks.trigger_batch_download")
def trigger_batch_download():
    """Run batch_download_links once; pipeline lock dedupes concurrent runs."""
    try:
        from worker.steps.batch_download_links import handle_batch_download_links
        asyncio.run(handle_batch_download_links())
    except Exception as e:
        logger.exception("trigger_batch_download failed: {}", e)
