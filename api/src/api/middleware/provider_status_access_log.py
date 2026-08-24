"""Redact the provider webhook credential from Uvicorn access records."""

import logging

PROVIDER_STATUS_WEBHOOK_PREFIX = "/api/provider-status/webhook/anthropic/"
_REDACTED_WEBHOOK_PATH = f"{PROVIDER_STATUS_WEBHOOK_PREFIX}[redacted]"


class ProviderStatusAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3 or not isinstance(args[2], str):
            return True

        path = args[2]
        route, separator, query = path.partition("?")
        if route.startswith(PROVIDER_STATUS_WEBHOOK_PREFIX):
            redacted = _REDACTED_WEBHOOK_PATH
            if separator:
                redacted = f"{redacted}?{query}"
            record.args = (*args[:2], redacted, *args[3:])
        return True


def install_provider_status_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, ProviderStatusAccessLogFilter) for item in logger.filters):
        logger.addFilter(ProviderStatusAccessLogFilter())
