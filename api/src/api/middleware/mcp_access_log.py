"""Redact the MCP OAuth callback query (code, state) from Uvicorn access records."""

import logging

MCP_OAUTH_CALLBACK_PATH = "/api/mcp/oauth/callback"


class McpCallbackAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3 or not isinstance(args[2], str):
            return True
        route, separator, _ = args[2].partition("?")
        if separator and (route.rstrip("/") == MCP_OAUTH_CALLBACK_PATH
                          or route.startswith("/api/mcp/runtime/")):
            record.args = (*args[:2], f"{route}?[redacted]", *args[3:])
        return True


def install_mcp_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, McpCallbackAccessLogFilter) for item in logger.filters):
        logger.addFilter(McpCallbackAccessLogFilter())
