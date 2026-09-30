"""MCP connector repository (todo 3796).

Session-level row access only; ownership, CAS and state transitions live in
`storage.service.mcp`. Every lookup by public id is owner-scoped, so a guessed
id of another owner behaves exactly like a missing one.
"""

from typing import List, Optional

from storage.entity.mcp import (
    McpConnectorEntity, McpCredentialEntity, McpLaunchConnectorEntity, McpLaunchEntity,
    McpOAuthTransactionEntity,
)
from storage.entity.user import UserEntity


def public_user_id(session, user_pk: int) -> Optional[str]:
    return session.query(UserEntity.user_id).filter(UserEntity.id == user_pk).scalar()


def list_live_connectors(session, user_id: int) -> List[McpConnectorEntity]:
    return (session.query(McpConnectorEntity)
            .filter(McpConnectorEntity.user_id == user_id,
                    McpConnectorEntity.deleted_at_unix.is_(None))
            .order_by(McpConnectorEntity.id).all())


def get_live_connector(session, user_id: int, connector_id: str, *, lock: bool = False
                       ) -> Optional[McpConnectorEntity]:
    query = session.query(McpConnectorEntity).filter(
        McpConnectorEntity.user_id == user_id,
        McpConnectorEntity.connector_id == connector_id,
        McpConnectorEntity.deleted_at_unix.is_(None),
    )
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def get_connector_by_pk(session, connector_pk: int, *, lock: bool = False
                        ) -> Optional[McpConnectorEntity]:
    query = session.query(McpConnectorEntity).filter(McpConnectorEntity.id == connector_pk)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def live_name_taken(session, user_id: int, name: str, exclude_pk: Optional[int] = None) -> bool:
    from sqlalchemy import func

    query = session.query(McpConnectorEntity.id).filter(
        McpConnectorEntity.user_id == user_id,
        McpConnectorEntity.deleted_at_unix.is_(None),
        func.lower(McpConnectorEntity.name) == name.lower(),
    )
    if exclude_pk is not None:
        query = query.filter(McpConnectorEntity.id != exclude_pk)
    return query.first() is not None


def get_credential(session, connector_pk: int, kind: str, *, lock: bool = False
                   ) -> Optional[McpCredentialEntity]:
    query = session.query(McpCredentialEntity).filter_by(connector_pk=connector_pk, kind=kind)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def list_credentials(session, connector_pk: int) -> List[McpCredentialEntity]:
    return session.query(McpCredentialEntity).filter_by(connector_pk=connector_pk).all()


def delete_credentials(session, connector_pk: int, kinds) -> int:
    return (session.query(McpCredentialEntity)
            .filter(McpCredentialEntity.connector_pk == connector_pk,
                    McpCredentialEntity.kind.in_(tuple(kinds)))
            .delete(synchronize_session=False))


def supersede_pending_transactions(session, connector_pk: int) -> int:
    return (session.query(McpOAuthTransactionEntity)
            .filter(McpOAuthTransactionEntity.connector_pk == connector_pk,
                    McpOAuthTransactionEntity.status.in_(("pending", "exchanging")))
            .update({"status": "superseded"}, synchronize_session=False))


def get_transaction_by_state(session, state_hash: str, *, lock: bool = False
                             ) -> Optional[McpOAuthTransactionEntity]:
    query = session.query(McpOAuthTransactionEntity).filter_by(state_hash=state_hash)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def get_transaction(session, transaction_id: str, *, user_id: Optional[int] = None,
                    lock: bool = False) -> Optional[McpOAuthTransactionEntity]:
    query = session.query(McpOAuthTransactionEntity).filter_by(transaction_id=transaction_id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def get_launch(session, launch_id: str, *, lock: bool = False) -> Optional[McpLaunchEntity]:
    query = session.query(McpLaunchEntity).filter_by(launch_id=launch_id)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def launch_connectors(session, launch_pk: int) -> List[McpLaunchConnectorEntity]:
    return (session.query(McpLaunchConnectorEntity)
            .filter_by(launch_pk=launch_pk).order_by(McpLaunchConnectorEntity.id).all())


def latest_launch_for_chat(session, user_id: int, chat_id: str) -> Optional[McpLaunchEntity]:
    return (session.query(McpLaunchEntity)
            .filter_by(user_id=user_id, chat_id=chat_id)
            .order_by(McpLaunchEntity.id.desc()).first())
