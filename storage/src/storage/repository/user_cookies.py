from typing import List, Optional

from storage.database.base import get_db
from storage.dto.user_cookies import UserCookies
from storage.entity.user_cookies import UserCookiesEntity


def _entity_to_dto(entity: UserCookiesEntity, *, count: int = 0) -> UserCookies:
    return UserCookies(
        domain=entity.domain,
        cookies_txt=entity.cookies_txt,
        count=count,
        expires_at=entity.expires_at_unix,
        updated_at=entity.updated_at,
        updated_at_unix=entity.updated_at_unix,
    )


def upsert_for_user_domain(
    user_id: int,
    domain: str,
    cookies_txt: str,
    expires_at_unix: Optional[int],
    count: int,
) -> UserCookies:
    with get_db() as session:
        entity = session.query(UserCookiesEntity).filter_by(user_id=user_id, domain=domain).first()
        if entity:
            entity.cookies_txt = cookies_txt
            entity.expires_at_unix = expires_at_unix
        else:
            entity = UserCookiesEntity(
                user_id=user_id,
                domain=domain,
                cookies_txt=cookies_txt,
                expires_at_unix=expires_at_unix,
            )
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity, count=count)


def get_for_user_domain(user_id: int, domain: str) -> Optional[UserCookies]:
    with get_db() as session:
        entity = session.query(UserCookiesEntity).filter_by(user_id=user_id, domain=domain).first()
        if not entity:
            return None
        return _entity_to_dto(entity)


def list_for_user(user_id: int) -> List[UserCookies]:
    with get_db() as session:
        rows = session.query(UserCookiesEntity).filter_by(user_id=user_id).order_by(UserCookiesEntity.domain).all()
        return [_entity_to_dto(row) for row in rows]


def delete_for_user_domain(user_id: int, domain: str) -> bool:
    with get_db() as session:
        count = session.query(UserCookiesEntity).filter_by(user_id=user_id, domain=domain).delete()
        session.flush()
        return count > 0
