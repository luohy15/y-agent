"""Public-but-secret Anthropic Statuspage webhook receiver."""

from __future__ import annotations

import hmac
import json
import os

from fastapi import APIRouter, HTTPException, Request, Response
from loguru import logger

from storage.service import provider_status as status_service

router = APIRouter(prefix="/provider-status")


@router.post("/webhook/anthropic/{secret}", status_code=204)
async def anthropic_webhook(secret: str, request: Request):
    """Commit a validated Statuspage delivery before returning a 2xx response."""
    configured_secret = os.environ.get("ANTHROPIC_STATUS_WEBHOOK_SECRET", "")
    if not configured_secret or not hmac.compare_digest(secret, configured_secret):
        logger.warning("provider status webhook rejected: invalid endpoint credential")
        raise HTTPException(status_code=404, detail="Not found")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > status_service.MAX_EVENT_RAW_BYTES:
                raise HTTPException(status_code=413, detail="Payload too large")
        except ValueError as err:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from err
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > status_service.MAX_EVENT_RAW_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large")
    raw = bytes(body)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err
    try:
        inserted = status_service.ingest_envelope(payload, channel="webhook")
    except ValueError as err:
        logger.warning("provider status webhook rejected: {}", str(err))
        raise HTTPException(status_code=422, detail="Unsupported provider status payload") from err
    logger.info("provider status webhook accepted provider=anthropic duplicate={}", not inserted)
    return Response(status_code=204)
