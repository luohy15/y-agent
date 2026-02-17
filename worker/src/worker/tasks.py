"""Celery tasks for y-agent worker."""

import asyncio

from loguru import logger

from worker.celery_app import app
from worker.runner import run_chat


@app.task(name="worker.tasks.process_chat")
def process_chat(chat_id: str, bot_name: str = None, user_id: int = None, vm_name: str = None):
    """Run the agent loop for a chat."""
    try:
        asyncio.run(run_chat(user_id, chat_id, bot_name=bot_name, vm_name=vm_name))
        logger.info("Finished chat {}", chat_id)
    except Exception as e:
        logger.exception("Chat {} failed: {}", chat_id, e)
