"""Host-owned normalized upstream provider status records."""

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from .base import Base


class ProviderStatusSourceEntity(Base):
    __tablename__ = "provider_status_source"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False, unique=True)
    page_id = Column(String(128), nullable=False)
    page_url = Column(String(512), nullable=False)
    indicator = Column(String(32), nullable=True)
    description = Column(Text, nullable=True)
    source_updated_at = Column(DateTime(timezone=True), nullable=True)
    last_webhook_receipt_at = Column(DateTime(timezone=True), nullable=True)
    last_reconciled_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)


class ProviderStatusComponentEntity(Base):
    __tablename__ = "provider_status_component"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    source_id = Column(String(128), nullable=False)
    name = Column(String(512), nullable=False)
    status = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    source_updated_at = Column(DateTime(timezone=True), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "source_id"),
        Index("ix_provider_status_component_provider_updated", "provider", "source_updated_at"),
    )


class ProviderStatusComponentTransitionEntity(Base):
    __tablename__ = "provider_status_component_transition"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    component_source_id = Column(String(128), nullable=False)
    component_name = Column(String(512), nullable=False)
    status = Column(String(64), nullable=False)
    source_timestamp = Column(DateTime(timezone=True), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "component_source_id", "status", "source_timestamp"),
        Index(
            "ix_provider_status_component_transition_provider_time",
            "provider",
            "source_timestamp",
        ),
    )


class ProviderStatusIncidentEntity(Base):
    __tablename__ = "provider_status_incident"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    source_id = Column(String(128), nullable=False)
    name = Column(String(1024), nullable=False)
    status = Column(String(64), nullable=False)
    impact = Column(String(64), nullable=True)
    shortlink = Column(String(1024), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    source_updated_at = Column(DateTime(timezone=True), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "source_id"),
        Index("ix_provider_status_incident_provider_status_updated", "provider", "status", "source_updated_at"),
    )


class ProviderStatusIncidentUpdateEntity(Base):
    __tablename__ = "provider_status_incident_update"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    source_id = Column(String(128), nullable=False)
    incident_source_id = Column(String(128), nullable=False)
    status = Column(String(64), nullable=False)
    body = Column(Text, nullable=True)
    affected_components_json = Column(Text, nullable=True)
    source_created_at = Column(DateTime(timezone=True), nullable=False)
    source_updated_at = Column(DateTime(timezone=True), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "source_id"),
        Index("ix_provider_status_incident_update_incident_time", "provider", "incident_source_id", "source_updated_at"),
    )


class ProviderStatusEventEntity(Base):
    __tablename__ = "provider_status_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    event_key = Column(String(128), nullable=False)
    channel = Column(String(32), nullable=False)
    event_kind = Column(String(64), nullable=False)
    incident_source_id = Column(String(128), nullable=True)
    component_source_id = Column(String(128), nullable=True)
    status = Column(String(64), nullable=True)
    source_timestamp = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False)
    raw_sha256 = Column(String(64), nullable=False)
    raw_json = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "event_key"),
        Index("ix_provider_status_event_expires_at", "expires_at"),
        Index("ix_provider_status_event_provider_received", "provider", "received_at"),
    )
