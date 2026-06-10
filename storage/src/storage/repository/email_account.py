"""Function-based email account repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.email_account import EmailAccountEntity
from storage.dto.email_account import EmailAccount
from storage.database.base import get_db


def _entity_to_dto(entity: EmailAccountEntity) -> EmailAccount:
    return EmailAccount(
        address=entity.address,
        app_password=entity.app_password,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
    )


def list_accounts(user_id: int) -> List[EmailAccount]:
    with get_db() as session:
        rows = session.query(EmailAccountEntity).filter_by(user_id=user_id).order_by(EmailAccountEntity.address).all()
        return [_entity_to_dto(row) for row in rows]


def get_account(user_id: int, address: str) -> Optional[EmailAccount]:
    with get_db() as session:
        row = session.query(EmailAccountEntity).filter_by(user_id=user_id, address=address).first()
        if not row:
            return None
        return _entity_to_dto(row)


def add_account(user_id: int, address: str, app_password: str) -> EmailAccount:
    """Insert or update an account (upsert on address)."""
    with get_db() as session:
        entity = session.query(EmailAccountEntity).filter_by(user_id=user_id, address=address).first()
        if entity:
            entity.app_password = app_password
        else:
            entity = EmailAccountEntity(user_id=user_id, address=address, app_password=app_password)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)


def delete_account(user_id: int, address: str) -> bool:
    with get_db() as session:
        count = session.query(EmailAccountEntity).filter_by(user_id=user_id, address=address).delete()
        session.flush()
        return count > 0
