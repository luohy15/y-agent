"""Reconcile the official Claude Status API into host-owned provider status state."""

from __future__ import annotations

import json
import os

import httpx
from loguru import logger

from storage.service import pipeline_lock as pipeline_lock_service
from storage.service import provider_status as status_service

LOCK_NAME = "reconcile_provider_status"
SUMMARY_URL = "https://status.claude.com/api/v2/summary.json"
INCIDENTS_URL = "https://status.claude.com/api/v2/incidents.json"
MAX_RESPONSE_BYTES = 512 * 1024


async def _get_json(client: httpx.AsyncClient, url: str) -> dict:
    async with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("provider status response exceeds local limit")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ValueError("provider status response is not JSON") from err
    if not isinstance(payload, dict):
        raise ValueError("provider status response is not a JSON object")
    return payload


async def handle_reconcile_provider_status() -> dict:
    if not pipeline_lock_service.try_acquire_lock(LOCK_NAME):
        return {"status": "skip", "action": LOCK_NAME, "reason": "lock held"}
    try:
        timeout = float(os.getenv("PROVIDER_STATUS_FETCH_TIMEOUT_SECONDS", "10"))
        async with httpx.AsyncClient(timeout=timeout, headers={"Accept": "application/json"}) as client:
            summary = await _get_json(client, SUMMARY_URL)
            recent = await _get_json(client, INCIDENTS_URL)
        incidents = recent.get("incidents") if isinstance(recent, dict) else None
        imported = status_service.ingest_snapshot(summary, incidents)
        retained = status_service.retention()
        logger.info("provider status reconciliation imported={} retained={}", imported, retained)
        return {"status": "ok", "action": LOCK_NAME, "imported": imported, "retained": retained}
    except Exception as err:
        logger.warning("provider status reconciliation failed: {}", str(err))
        return {"status": "error", "action": LOCK_NAME, "error": "provider status reconciliation failed"}
    finally:
        pipeline_lock_service.release_lock(LOCK_NAME)
