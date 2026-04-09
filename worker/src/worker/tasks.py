"""Celery tasks for y-agent worker."""

import asyncio

from loguru import logger

from worker.celery_app import app
from worker.runner import run_chat
from worker.link_downloader import run_link_download


@app.task(name="worker.tasks.process_chat")
def process_chat(chat_id: str, bot_name: str = None, user_id: int = None, vm_name: str = None, work_dir: str = None, post_hooks: list = None, trace_id: str = None, skill: str = None, backend: str = None):
    """Run the agent loop for a chat."""
    try:
        asyncio.run(run_chat(user_id, chat_id, bot_name=bot_name, vm_name=vm_name, work_dir=work_dir, post_hooks=post_hooks, trace_id=trace_id, skill=skill, backend=backend))
        logger.info("Finished chat {}", chat_id)
    except Exception as e:
        logger.exception("Chat {} failed: {}", chat_id, e)


@app.task(name="worker.tasks.process_link_download")
def process_link_download(user_id: int = None, link_id: str = None, url: str = None, activity_id: str = None, **kwargs):
    """Download link content via fetcher service."""
    try:
        asyncio.run(run_link_download(user_id=user_id, link_id=link_id, url=url, activity_id=activity_id))
        logger.info("Finished link download {}", link_id)
    except Exception as e:
        logger.exception("Link download {} failed: {}", link_id, e)
