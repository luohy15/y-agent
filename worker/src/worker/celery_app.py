"""Celery application for y-agent worker (local dev with filesystem broker)."""

from celery import Celery
from storage.celery_config import BROKER_URL, BROKER_TRANSPORT_OPTIONS, RESULT_BACKEND

app = Celery("worker")
app.conf.update(
    broker_url=BROKER_URL,
    broker_transport_options=BROKER_TRANSPORT_OPTIONS,
    result_backend=RESULT_BACKEND,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
)

# Auto-discover tasks module
app.autodiscover_tasks(["worker"])
