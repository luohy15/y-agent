"""Host MCP routes (todo 3796).

`GET /api/mcp/oauth/callback` is the only anonymous MCP route: a provider
redirect cannot carry y-agent's Bearer token, so the single-use state is the
credential. Connector management stays behind the authenticated `mcp`
module. The response is a redirect to the deployment-fixed web location with
only a closed outcome and the opaque transaction id; provider codes, errors and
descriptions are never echoed, logged or placed in a Referer.
"""

import asyncio
import html
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

from agent.mcp import manager
from storage.service.mcp import McpError, validate_https_url

router = APIRouter(prefix="/mcp")

OAUTH_CALLBACK_PATH = "/api/mcp/oauth/callback"
_CALLBACK_PARAMS = ("state", "code", "error", "iss")
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_OUTCOME_TEXT = {
    "connected": "Connector authorized. You can close this page.",
    "denied": "Authorization was cancelled.",
    "expired": "Authorization expired. Start Connect again.",
    "invalid": "This authorization link is invalid or was already used.",
    "failed": "Authorization failed. Start Connect again.",
    "superseded": "The connector changed during authorization. Start Connect again.",
}


def _return_url() -> str | None:
    configured = os.environ.get("Y_AGENT_MCP_WEB_RETURN_URL", "").strip()
    if not configured:
        return None
    try:
        return validate_https_url(configured, allow_query=True)
    except McpError:
        return None


def _outcome_response(outcome: str, transaction_id: str | None):
    outcome = outcome if outcome in _OUTCOME_TEXT else "failed"
    target = _return_url()
    if target:
        query = {"mcp_oauth": outcome}
        if transaction_id:
            query["transaction_id"] = transaction_id
        separator = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{separator}{urlencode(query)}", status_code=303,
                                headers=_NO_STORE_HEADERS)
    body = ("<!doctype html><meta charset=utf-8><title>y-agent</title>"
            f"<p>{html.escape(_OUTCOME_TEXT[outcome])}</p>")
    return HTMLResponse(body, headers=_NO_STORE_HEADERS)


@router.get("/oauth/callback")
async def oauth_callback(request: Request):
    params = {key: request.query_params.get(key) for key in _CALLBACK_PARAMS
              if request.query_params.get(key) is not None}
    try:
        result = await asyncio.to_thread(manager.handle_callback, params)
    except Exception as err:  # never leak provider/DB detail through the redirect
        logger.warning("mcp oauth callback failed: {}", type(err).__name__)
        result = {"outcome": "failed", "transaction_id": None}
    logger.info("mcp oauth callback outcome={}", result["outcome"])
    return _outcome_response(result["outcome"], result.get("transaction_id"))
