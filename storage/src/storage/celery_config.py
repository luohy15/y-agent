"""Shared Celery broker configuration for local dev (filesystem broker)."""

BROKER_URL = "filesystem://"
BROKER_TRANSPORT_OPTIONS = {
    "data_folder_in": "/tmp/celery/out",
    "data_folder_out": "/tmp/celery/out",
    "data_folder_processed": "/tmp/celery/processed",
}
RESULT_BACKEND = "file:///tmp/celery/results"
