"""Host-owned MCP connector state (todo 3796).

Connector configuration, central credential custody, OAuth transactions and
per-launch snapshots are runtime kernel tables: the worker and the API gateway
read them, the `mcp` module manages them only through the host contract.
Secret material exists only as an AES-GCM envelope (`ciphertext`, `nonce`,
`encrypted_data_key`, `key_id`); no normal projection reads those columns.
"""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint, text
)
from .base import Base, BaseEntity


class McpConnectorEntity(Base, BaseEntity):
    """One owner-scoped remote MCP server and its desired state.

    `identity_generation` changes whenever the server or the authentication
    identity changes (endpoint, auth mode, credentials, OAuth client,
    disconnect); that clears validation, discovery and approval. Every
    management mutation increments `config_revision`, the CAS token callers
    must echo back. `approved_tools` is an explicit JSON name list: empty
    means no tools, never all tools.
    """

    __tablename__ = "mcp_connector"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connector_id = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    preset = Column(String, nullable=True)
    auth_mode = Column(String, nullable=False)
    desired_enabled = Column(Boolean, nullable=False, default=False)
    config_revision = Column(Integer, nullable=False, default=1)
    identity_generation = Column(Integer, nullable=False, default=1)
    approved_tools = Column(Text, nullable=False, default="[]")
    discovery_revision = Column(Integer, nullable=False, default=0)
    catalog = Column(Text, nullable=True)
    validated_identity_generation = Column(Integer, nullable=True)
    auth_state = Column(String, nullable=False)
    last_test_at_unix = Column(BigInteger, nullable=True)
    last_test_status = Column(String, nullable=True)
    last_test_error_code = Column(String, nullable=True)
    deleted_at_unix = Column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint("auth_mode IN ('oauth', 'static', 'none')", name="ck_mcp_connector_auth_mode"),
        CheckConstraint(
            "auth_state IN ('not_required', 'not_configured', 'connected', 'reconnect_required')",
            name="ck_mcp_connector_auth_state",
        ),
        Index("uq_mcp_connector_live_name", "user_id", text("lower(name)"), unique=True,
              postgresql_where=text("deleted_at_unix IS NULL")),
    )


class McpCredentialEntity(Base, BaseEntity):
    """Encrypted credential material bound to one connector identity.

    `kind` is `static_headers`, `oauth_client` (manually supplied client
    registration) or `oauth_token` (access/refresh tokens plus the client that
    obtained them). `public_meta` holds only non-secret binding facts (issuer,
    token endpoint, client id, auth method, resource, header names).
    """

    __tablename__ = "mcp_credential"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connector_pk = Column(Integer, ForeignKey('mcp_connector.id', ondelete='CASCADE'), nullable=False)
    identity_generation = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    key_id = Column(String, nullable=False)
    encrypted_data_key = Column(Text, nullable=False)
    nonce = Column(Text, nullable=False)
    ciphertext = Column(Text, nullable=False)
    public_meta = Column(Text, nullable=False, default="{}")
    access_expires_at_unix = Column(BigInteger, nullable=True)
    credential_revision = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="usable")
    refresh_claim = Column(String, nullable=True)
    refresh_claim_deadline_unix = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("connector_pk", "kind", name="uq_mcp_credential_kind"),
        CheckConstraint("kind IN ('static_headers', 'oauth_client', 'oauth_token')",
                        name="ck_mcp_credential_kind"),
        CheckConstraint("status IN ('usable', 'reconnect_required')", name="ck_mcp_credential_status"),
    )


class McpOAuthTransactionEntity(Base, BaseEntity):
    """One authorization-code attempt. Only the state digest is stored; the
    PKCE verifier (and a dynamically registered client secret) are encrypted.
    Issuer, resource, redirect, client and token endpoint are immutable."""

    __tablename__ = "mcp_oauth_transaction"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    connector_pk = Column(Integer, ForeignKey('mcp_connector.id', ondelete='CASCADE'), nullable=False, index=True)
    identity_generation = Column(Integer, nullable=False)
    state_hash = Column(String, nullable=False, unique=True)
    key_id = Column(String, nullable=False)
    encrypted_data_key = Column(Text, nullable=False)
    nonce = Column(Text, nullable=False)
    ciphertext = Column(Text, nullable=False)
    issuer = Column(String, nullable=False)
    resource = Column(String, nullable=False)
    redirect_uri = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    token_endpoint = Column(String, nullable=False)
    binding_meta = Column(Text, nullable=False, default="{}")
    expires_at_unix = Column(BigInteger, nullable=False)
    consumed_at_unix = Column(BigInteger, nullable=True)
    status = Column(String, nullable=False, default="pending")
    error_code = Column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'exchanging', 'succeeded', 'denied', 'failed', 'expired', 'superseded')",
            name="ck_mcp_oauth_transaction_status",
        ),
    )


class McpLaunchEntity(Base, BaseEntity):
    """One actual Claude Code process launch and its hashed gateway grant."""

    __tablename__ = "mcp_launch"

    id = Column(Integer, primary_key=True, autoincrement=True)
    launch_id = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    run_seq = Column(Integer, nullable=True)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at_unix = Column(BigInteger, nullable=False)
    ended_at_unix = Column(BigInteger, nullable=True)
    status = Column(String, nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'ended', 'expired')", name="ck_mcp_launch_status"),
        Index("ix_mcp_launch_chat", "user_id", "chat_id"),
    )


class McpLaunchConnectorEntity(Base, BaseEntity):
    """Immutable per-launch connector snapshot (policy is never widened)."""

    __tablename__ = "mcp_launch_connector"

    id = Column(Integer, primary_key=True, autoincrement=True)
    launch_pk = Column(Integer, ForeignKey('mcp_launch.id', ondelete='CASCADE'), nullable=False)
    connector_pk = Column(Integer, ForeignKey('mcp_connector.id', ondelete='CASCADE'), nullable=False)
    config_revision = Column(Integer, nullable=False)
    identity_generation = Column(Integer, nullable=False)
    endpoint = Column(String, nullable=False)
    approved_tools = Column(Text, nullable=False, default="[]")
    tool_snapshot = Column(Text, nullable=False, default="[]")
    status = Column(String, nullable=False, default="pending")
    error_code = Column(String, nullable=True)
    upstream_session_id = Column(String, nullable=True)
    upstream_protocol_version = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("launch_pk", "connector_pk", name="uq_mcp_launch_connector"),
    )
