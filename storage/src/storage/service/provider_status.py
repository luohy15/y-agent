"""Validation, normalization, reads, and retention for provider status sources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from storage.repository import provider_status as repo

ANTHROPIC_PROVIDER = "anthropic"
ANTHROPIC_PAGE_ID = "tymt9n04zgry"
ANTHROPIC_PAGE_URL = "https://status.claude.com"
MAX_EVENT_RAW_BYTES = 256 * 1024
EVENT_RETENTION = timedelta(days=30)
NORMALIZED_RETENTION = timedelta(days=366)
WEBHOOK_STALE_AFTER = timedelta(hours=2)
SOURCE_STALE_AFTER = timedelta(hours=2)
COMPONENT_STATUSES = frozenset({"operational", "degraded_performance", "partial_outage", "major_outage"})
INCIDENT_STATUSES = frozenset({"investigating", "identified", "monitoring", "resolved", "postmortem"})
INDICATORS = frozenset({"none", "minor", "major", "critical"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any, field: str, *, required: bool = True) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from err
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _text(value: Any, field: str, limit: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"invalid {field}")
    return value


def _canonical_page(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("missing status page")
    page_id = value.get("id") or value.get("page_id")
    if page_id != ANTHROPIC_PAGE_ID:
        raise ValueError("unsupported status page")
    page_url = value.get("url") or value.get("page_url") or ANTHROPIC_PAGE_URL
    if not isinstance(page_url, str) or urlparse(page_url).hostname != "status.claude.com":
        raise ValueError("unsupported status page")
    return {"page_id": page_id, "page_url": ANTHROPIC_PAGE_URL}


def _sanitize(value: Any, *, key: str = "") -> Any:
    """Preserve debug provenance without retaining credentials or query-bearing URLs."""
    lowered = key.lower()
    if any(token in lowered for token in ("unsubscribe", "secret", "token", "password", "email")):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        if parsed.query or parsed.fragment:
            return "[redacted-url]"
    return value


def _source_url(incident: dict) -> str | None:
    url = incident.get("shortlink") or incident.get("url")
    if not isinstance(url, str) or len(url) > 1024:
        return None
    parsed = urlparse(url)
    return url if parsed.hostname in {"status.claude.com", "stspg.io"} and not parsed.query and not parsed.fragment else None


def _component_ref(component: dict) -> tuple[str, str]:
    """Statuspage API incident updates use `code`; webhook components use `id`."""
    source_id = component.get("id") or component.get("code")
    name = component.get("name") or component.get("code")
    return (
        _text(source_id, "affected component id", 128),
        _text(name, "affected component name", 512),
    )


def _component(component: dict, observed_at: datetime, update: dict | None = None) -> dict:
    """Statuspage component deliveries keep state in `component` and the transition in `component_update`."""
    update = update or {}
    source_id = _text(component.get("id") or update.get("component_id"), "component id", 128)
    status = _text(component.get("status") or update.get("new_status"), "component status", 64)
    if status not in COMPONENT_STATUSES:
        raise ValueError("unsupported component status")
    return {
        "provider": ANTHROPIC_PROVIDER,
        "source_id": source_id,
        "name": _text(component.get("name"), "component name", 512),
        "status": status,
        "description": _text(component.get("description"), "component description", 16_384, required=False),
        "source_updated_at": _parse_time(component.get("updated_at") or update.get("created_at"), "component updated_at"),
        "observed_at": observed_at,
    }


def _incident(incident: dict, observed_at: datetime) -> dict:
    source_id = _text(incident.get("id"), "incident id", 128)
    status = _text(incident.get("status"), "incident status", 64)
    if status not in INCIDENT_STATUSES:
        raise ValueError("unsupported incident status")
    impact = _text(incident.get("impact"), "incident impact", 64, required=False)
    if impact is not None and impact not in INDICATORS:
        raise ValueError("unsupported incident impact")
    return {
        "provider": ANTHROPIC_PROVIDER,
        "source_id": source_id,
        "name": _text(incident.get("name") or incident.get("title"), "incident name", 1024),
        "status": status,
        "impact": impact,
        "shortlink": _source_url(incident),
        "started_at": _parse_time(incident.get("started_at") or incident.get("created_at"), "incident started_at", required=False),
        "resolved_at": _parse_time(incident.get("resolved_at"), "incident resolved_at", required=False),
        "source_updated_at": _parse_time(incident.get("updated_at"), "incident updated_at"),
        "observed_at": observed_at,
    }


def _update(update: dict, incident_source_id: str, observed_at: datetime) -> dict:
    source_id = _text(update.get("id"), "incident update id", 128)
    status = _text(update.get("status"), "incident update status", 64)
    if status not in INCIDENT_STATUSES:
        raise ValueError("unsupported incident update status")
    components = update.get("affected_components") or []
    if not isinstance(components, list):
        raise ValueError("incident affected_components must be a list")
    safe_components = [
        {"id": component_id, "name": component_name}
        for component_id, component_name in (_component_ref(item) for item in components if isinstance(item, dict))
    ]
    if len(safe_components) != len(components):
        raise ValueError("invalid affected component")
    updated_at = _parse_time(update.get("updated_at") or update.get("created_at"), "incident update timestamp")
    return {
        "provider": ANTHROPIC_PROVIDER,
        "source_id": source_id,
        "incident_source_id": incident_source_id,
        "status": status,
        "body": _text(update.get("body") or update.get("message"), "incident update body", 65_536, required=False),
        "affected_components_json": json.dumps(safe_components, separators=(",", ":")),
        "source_created_at": _parse_time(update.get("created_at") or update.get("updated_at"), "incident update created_at"),
        "source_updated_at": updated_at,
        "observed_at": observed_at,
    }


def _event_key(kind: str, identifier: str | None, sanitized: dict) -> str:
    material = identifier or json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{ANTHROPIC_PROVIDER}:{kind}:{material}".encode()).hexdigest()


def normalize_envelope(envelope: dict, *, channel: str, observed_at: datetime | None = None) -> dict:
    """Normalize official current and legacy Statuspage envelopes before one DB transaction."""
    if not isinstance(envelope, dict):
        raise ValueError("webhook body must be a JSON object")
    observed_at = observed_at or _now()
    page = _canonical_page(envelope.get("statuspage") or envelope.get("page"))
    meta = envelope.get("meta") or {}
    if meta and not isinstance(meta, dict):
        raise ValueError("invalid webhook meta")
    generated_at = _parse_time(meta.get("generated_at"), "meta generated_at", required=False)
    incident = envelope.get("incident")
    component = envelope.get("component")
    component_update = envelope.get("component_update")
    incident_id = envelope.get("incident_ID") or envelope.get("incident_id")
    kind = "incident" if isinstance(incident, dict) else "component" if isinstance(component, dict) or isinstance(component_update, dict) else None
    if kind is None:
        raise ValueError("unsupported provider status event")
    sanitized = _sanitize(envelope)
    raw_json = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    raw_sha256 = hashlib.sha256(raw_json.encode()).hexdigest()
    components: list[dict] = []
    incidents: list[dict] = []
    updates: list[dict] = []
    event_identifier = None
    event_status = None
    source_timestamp = generated_at
    if incident:
        normalized_incident = _incident(incident, observed_at)
        if incident_id is not None and incident_id != normalized_incident["source_id"]:
            raise ValueError("incident identity mismatch")
        incidents.append(normalized_incident)
        event_identifier = normalized_incident["source_id"]
        event_status = normalized_incident["status"]
        source_timestamp = normalized_incident["source_updated_at"]
        raw_updates = incident.get("incident_updates") or []
        if not isinstance(raw_updates, list):
            raise ValueError("incident updates must be a list")
        updates = [_update(item, normalized_incident["source_id"], observed_at) for item in raw_updates if isinstance(item, dict)]
        if len(updates) != len(raw_updates):
            raise ValueError("invalid incident update")
        components = [_component(item, observed_at) for item in incident.get("components", [])]
    else:
        if not isinstance(component, dict):
            raise ValueError("missing component state")
        normalized_component = _component(component, observed_at, component_update if isinstance(component_update, dict) else None)
        components.append(normalized_component)
        event_identifier = normalized_component["source_id"]
        event_status = normalized_component["status"]
        source_timestamp = normalized_component["source_updated_at"]
    source = {
        "provider": ANTHROPIC_PROVIDER,
        **page,
        "source_updated_at": source_timestamp,
        "last_webhook_receipt_at": observed_at if channel == "webhook" else None,
        "last_reconciled_at": observed_at if channel == "reconciliation" else None,
        "last_success_at": observed_at,
    }
    transition_components = list(components)
    if incident and not transition_components:
        for update in raw_updates:
            for affected in update.get("affected_components") or []:
                if not isinstance(affected, dict):
                    raise ValueError("invalid affected component")
                component_id, component_name = _component_ref(affected)
                status = affected.get("new_status") or affected.get("status")
                if status not in COMPONENT_STATUSES:
                    continue
                transition_components.append({
                    "source_id": component_id,
                    "name": component_name,
                    "status": status,
                    "source_timestamp": _parse_time(
                        update.get("updated_at") or update.get("created_at"),
                        "incident update timestamp",
                    ),
                })
    transitions = [
        {
            "provider": ANTHROPIC_PROVIDER,
            "component_source_id": item["source_id"],
            "component_name": item["name"],
            "status": item["status"],
            "source_timestamp": item.get("source_timestamp", source_timestamp),
            "observed_at": observed_at,
        }
        for item in transition_components
    ]
    return {
        "source": source,
        "components": components,
        "transitions": transitions,
        "incidents": incidents,
        "updates": updates,
        "event": {
            "provider": ANTHROPIC_PROVIDER,
            "event_key": _event_key(kind, f"{event_identifier}:{source_timestamp.isoformat() if source_timestamp else raw_sha256}", sanitized),
            "channel": channel,
            "event_kind": kind,
            "incident_source_id": incidents[0]["source_id"] if incidents else None,
            "component_source_id": components[0]["source_id"] if kind == "component" else None,
            "status": event_status,
            "source_timestamp": source_timestamp,
            "received_at": observed_at,
            "raw_sha256": raw_sha256,
            "raw_json": raw_json,
            "expires_at": observed_at + EVENT_RETENTION,
        },
    }


def ingest_envelope(envelope: dict, *, channel: str, observed_at: datetime | None = None) -> bool:
    return repo.ingest(normalize_envelope(envelope, channel=channel, observed_at=observed_at))


def _unhandled_receipt(envelope: dict, page: dict, observed_at: datetime) -> dict:
    """Keep bounded redacted provenance for a canonical delivery this normalizer cannot map."""
    sanitized = _sanitize(envelope)
    raw_json = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    raw_sha256 = hashlib.sha256(raw_json.encode()).hexdigest()
    return {
        "source": {
            "provider": ANTHROPIC_PROVIDER, **page,
            "source_updated_at": None, "last_webhook_receipt_at": observed_at,
            "last_reconciled_at": None, "last_success_at": None,
        },
        "components": [],
        "transitions": [],
        "incidents": [],
        "updates": [],
        "event": {
            "provider": ANTHROPIC_PROVIDER,
            "event_key": _event_key("unhandled", raw_sha256, sanitized),
            "channel": "webhook",
            "event_kind": "unhandled",
            "incident_source_id": None,
            "component_source_id": None,
            "status": None,
            "source_timestamp": None,
            "received_at": observed_at,
            "raw_sha256": raw_sha256,
            "raw_json": raw_json,
            "expires_at": observed_at + EVENT_RETENTION,
        },
    }


def ingest_webhook(envelope: Any, *, observed_at: datetime | None = None) -> str:
    """Statuspage deactivates an endpoint that answers non-2xx, so acknowledge every canonical delivery.

    Page identity is still enforced: only a body this normalizer cannot map is downgraded from a
    rejection to a redacted `unhandled` receipt that records the webhook path is alive without
    claiming fresh provider state.
    """
    if not isinstance(envelope, dict):
        raise ValueError("webhook body must be a JSON object")
    observed_at = observed_at or _now()
    page = _canonical_page(envelope.get("statuspage") or envelope.get("page"))
    try:
        normalized = normalize_envelope(envelope, channel="webhook", observed_at=observed_at)
    except ValueError as err:
        logger.warning("provider status webhook delivery not normalized: {}", str(err))
        repo.ingest(_unhandled_receipt(envelope, page, observed_at))
        return "unhandled"
    return "ingested" if repo.ingest(normalized) else "duplicate"


def ingest_snapshot(summary: dict, incidents: list[dict], *, observed_at: datetime | None = None) -> int:
    """Import a validated Statuspage API snapshot as idempotent normalized events."""
    if not isinstance(summary, dict) or not isinstance(incidents, list):
        raise ValueError("invalid provider status snapshot")
    observed_at = observed_at or _now()
    page = _canonical_page(summary.get("page"))
    status = summary.get("status") or {}
    if not isinstance(status, dict) or status.get("indicator") not in INDICATORS:
        raise ValueError("invalid provider summary")
    components = summary.get("components") or []
    if not isinstance(components, list):
        raise ValueError("invalid provider components")
    normalized_incidents = [
        normalize_envelope({"page": page, "incident": item}, channel="reconciliation", observed_at=observed_at)
        for item in incidents
    ]
    sanitized = _sanitize(summary)
    raw_json = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    raw_sha256 = hashlib.sha256(raw_json.encode()).hexdigest()
    snapshot = {
        "source": {
            "provider": ANTHROPIC_PROVIDER, **page, "indicator": status["indicator"],
            "description": _text(status.get("description"), "summary description", 16_384, required=False),
            "source_updated_at": observed_at, "last_webhook_receipt_at": None,
            "last_reconciled_at": observed_at, "last_success_at": observed_at,
        },
        "components": [_component(item, observed_at) for item in components],
        "transitions": [
            {
                "provider": ANTHROPIC_PROVIDER,
                "component_source_id": item["id"],
                "component_name": item["name"],
                "status": item["status"],
                "source_timestamp": _parse_time(item.get("updated_at"), "component updated_at"),
                "observed_at": observed_at,
            }
            for item in components
        ],
        "incidents": [],
        "updates": [],
        "event": {
            "provider": ANTHROPIC_PROVIDER,
            "event_key": hashlib.sha256(f"summary:{raw_json}".encode()).hexdigest(),
            "channel": "reconciliation",
            "event_kind": "summary",
            "incident_source_id": None,
            "component_source_id": None,
            "status": status["indicator"],
            "source_timestamp": observed_at,
            "received_at": observed_at,
            "raw_sha256": raw_sha256,
            "raw_json": raw_json,
            "expires_at": observed_at + EVENT_RETENTION,
        },
    }
    return repo.ingest_batch([*normalized_incidents, snapshot])


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _as_utc(value)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def overview(provider: str = ANTHROPIC_PROVIDER, *, now: datetime | None = None) -> dict:
    _require_provider(provider)
    now = now or _now()
    source = repo.overview(provider)
    components = repo.list_components(provider, 100)
    if source is None:
        return {"provider": provider, "available": False, "components": [], "webhook_stale": True, "source_stale": True}
    last_webhook_receipt_at = _as_utc(source.last_webhook_receipt_at)
    last_success_at = _as_utc(source.last_success_at)
    webhook_stale = last_webhook_receipt_at is None or now - last_webhook_receipt_at > WEBHOOK_STALE_AFTER
    source_stale = last_success_at is None or now - last_success_at > SOURCE_STALE_AFTER
    return {"provider": provider, "available": True, "page_id": source.page_id, "source_url": source.page_url, "indicator": source.indicator, "description": source.description, "source_updated_at": _iso(source.source_updated_at), "last_webhook_receipt_at": _iso(source.last_webhook_receipt_at), "last_reconciled_at": _iso(source.last_reconciled_at), "last_success_at": _iso(source.last_success_at), "webhook_stale": webhook_stale, "source_stale": source_stale, "components": [{"source_id": row.source_id, "name": row.name, "status": row.status, "description": row.description, "source_updated_at": _iso(row.source_updated_at), "observed_at": _iso(row.observed_at)} for row in components]}


def incidents(provider: str, start: datetime, end: datetime, limit: int) -> dict:
    _require_provider(provider); _require_range(start, end); _require_limit(limit, 100)
    return {"provider": provider, "incidents": [_incident_dict(row) for row in repo.list_incidents(provider, start, end, limit)]}


def incident(provider: str, source_id: str) -> dict:
    _require_provider(provider)
    row, updates = repo.get_incident(provider, _text(source_id, "incident id", 128))
    if row is None:
        raise ValueError("incident not found")
    return {**_incident_dict(row), "updates": [{"source_id": item.source_id, "status": item.status, "body": item.body, "affected_components": json.loads(item.affected_components_json), "source_created_at": _iso(item.source_created_at), "source_updated_at": _iso(item.source_updated_at), "observed_at": _iso(item.observed_at)} for item in updates]}


def history(provider: str, start: datetime, end: datetime, limit: int) -> dict:
    _require_provider(provider); _require_range(start, end); _require_limit(limit, 500)
    transitions = repo.list_component_transitions(provider, start, end, limit)
    return {"provider": provider, "coverage_start": _iso(start), "coverage_end": _iso(end), "coverage_limited": repo.overview(provider) is None, "component_events": [{"component_source_id": row.component_source_id, "component_name": row.component_name, "status": row.status, "source_timestamp": _iso(row.source_timestamp), "observed_at": _iso(row.observed_at)} for row in transitions]}


def retention(now: datetime | None = None, batch_size: int = 1000) -> dict[str, int]:
    if not 1 <= batch_size <= 10_000:
        raise ValueError("invalid retention batch size")
    now = now or _now()
    return repo.retention(now, now - NORMALIZED_RETENTION, batch_size)


def _incident_dict(row) -> dict:
    return {"source_id": row.source_id, "name": row.name, "status": row.status, "impact": row.impact, "source_url": row.shortlink, "started_at": _iso(row.started_at), "resolved_at": _iso(row.resolved_at), "source_updated_at": _iso(row.source_updated_at), "observed_at": _iso(row.observed_at)}


def _require_provider(provider: str) -> None:
    if provider != ANTHROPIC_PROVIDER:
        raise ValueError("unsupported provider")


def _require_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None or not start < end or end - start > timedelta(days=366):
        raise ValueError("invalid closed time range")


def _require_limit(limit: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
