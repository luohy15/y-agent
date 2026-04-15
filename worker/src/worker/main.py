"""Worker: starts Celery worker for processing chats (local dev)."""

import os

from loguru import logger
from dotenv import load_dotenv
from storage.global_config import load_global_config

load_dotenv()
load_global_config()


def _ensure_broker_dirs():
    """Create filesystem broker directories if they don't exist."""
    dirs = [
        "/tmp/celery/out",
        "/tmp/celery/processed",
        "/tmp/celery/results",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def main():
    _ensure_broker_dirs()

    # Import here so dotenv is loaded before any Celery/storage imports
    from worker.celery_app import app

    logger.info("Starting Celery worker with filesystem broker")
    app.worker_main(["worker", "--loglevel=info", "--pool=solo"])


if __name__ == "__main__":
    main()
