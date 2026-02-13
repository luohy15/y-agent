"""Celery tasks for y-agent worker."""

import asyncio

from loguru import logger

from storage.service import chat as chat_service
from worker.celery_app import app
from worker.runner import run_chat


@app.task(name="worker.tasks.process_chat")
def process_chat(chat_id: str):
    """Fetch chat from DB, claim it, and run the agent loop."""
    chat = asyncio.run(chat_service.get_chat_by_id(chat_id))
    if chat is None:
        logger.warning("Chat {} not found in DB, skipping", chat_id)
        return

    status = chat.status
    if status not in ("pending", "approved", "denied"):
        logger.warning("Chat {} has status={}, skipping", chat_id, status)
        return

    if status == "pending":
        asyncio.run(chat_service.update_chat_status(chat_id, "running"))
        logger.info("Claimed chat {} via Celery task", chat_id)

    try:
        asyncio.run(run_chat(chat_id, status))
        logger.info("Finished chat {}", chat_id)
    except Exception as e:
        logger.exception("Chat {} failed: {}", chat_id, e)
        asyncio.run(chat_service.update_chat_status(chat_id, "failed"))
