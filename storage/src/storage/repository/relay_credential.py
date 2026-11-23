"""Owner-scoped relay credential rows. The api_key column is sealed on flush."""

import secrets

from storage.database.base import get_db
from storage.dto.relay_credential import RelayCredential
from storage.entity.relay_credential import RelayCredentialEntity


def _to_dto(row: RelayCredentialEntity) -> RelayCredential:
    return RelayCredential(
        credential_id=row.credential_id,
        user_id=row.user_id,
        relay_origin=row.relay_origin,
        relay_key_id=row.relay_key_id or "",
        key_name=row.key_name,
        billing_mode=row.billing_mode or "real",
        api_key=row.api_key or "",
    )


def get_for_user_origin(user_id: int, relay_origin: str) -> RelayCredential | None:
    with get_db() as session:
        row = (
            session.query(RelayCredentialEntity)
            .filter_by(user_id=user_id, relay_origin=relay_origin)
            .one_or_none()
        )
        return _to_dto(row) if row else None


def upsert(
    user_id: int,
    relay_origin: str,
    api_key: str,
    *,
    key_name: str,
    billing_mode: str,
    relay_key_id: str = "",
) -> RelayCredential:
    with get_db() as session:
        row = (
            session.query(RelayCredentialEntity)
            .filter_by(user_id=user_id, relay_origin=relay_origin)
            .one_or_none()
        )
        if row is None:
            row = RelayCredentialEntity(
                credential_id=f"rc_{secrets.token_hex(16)}",
                user_id=user_id,
                relay_origin=relay_origin,
                relay_key_id=relay_key_id,
                key_name=key_name,
                billing_mode=billing_mode,
                api_key=api_key,
            )
            session.add(row)
        else:
            row.api_key = api_key
            row.relay_key_id = relay_key_id
            row.key_name = key_name
            row.billing_mode = billing_mode
        session.flush()
        return _to_dto(row)
