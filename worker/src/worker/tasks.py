"""Celery tasks for y-agent worker."""

import asyncio
import uuid

from loguru import logger

from worker.celery_app import app
from worker.monitor import _monitor_loop
from worker.runner import run_chat


async def _run_chat_with_monitor(chat_id, bot_name, user_id, vm_name, work_dir,
                                  post_hooks, trace_id, role, topic, skill, backend):
    result = await run_chat(
        user_id, chat_id, bot_name=bot_name, vm_name=vm_name, work_dir=work_dir,
        post_hooks=post_hooks, trace_id=trace_id, role=role, topic=topic, skill=skill, backend=backend,
    )
    if result in ("detached", "continuation"):
        req_id = f"celery-{uuid.uuid4().hex[:8]}"
        await _monitor_loop(deadline_at=None, lambda_req_id=req_id)


@app.task(name="worker.tasks.process_chat")
def process_chat(chat_id: str, bot_name: str = None, user_id: int = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, role: str = None, topic: str = None, skill: str = None, backend: str = None):
    """Run the agent loop for a chat."""
    try:
        asyncio.run(_run_chat_with_monitor(
            chat_id, bot_name, user_id, vm_name, work_dir,
            post_hooks, trace_id, role, topic, skill, backend,
        ))
        logger.info("Finished chat {}", chat_id)
    except Exception as e:
        logger.exception("Chat {} failed: {}", chat_id, e)


@app.task(name="worker.tasks.trigger_batch_download")
def trigger_batch_download():
    """Run batch_download_links once; pipeline lock dedupes concurrent runs."""
    try:
        from worker.steps.batch_download_links import handle_batch_download_links
        asyncio.run(handle_batch_download_links())
    except Exception as e:
        logger.exception("trigger_batch_download failed: {}", e)
