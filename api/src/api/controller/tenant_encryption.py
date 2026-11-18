"""Maintainer-only tenant encryption lifecycle. Enable stays blocked until todo 4371."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage.crypto.tenant import TenantCryptoError
from storage.database.base import get_db
from storage.service.user import get_module_maintainer_user_id

router = APIRouter(prefix="/tenant-encryption", tags=["tenant-encryption"])


class UserBody(BaseModel):
    user_id: int


def _maintainer(request: Request) -> int:
    caller = getattr(request.state, "user_id", None)
    owner = get_module_maintainer_user_id()
    if owner is None or caller != owner:
        raise HTTPException(status_code=403, detail="tenant encryption is restricted to the maintainer")
    return caller


def _run(action):
    try:
        with get_db() as session:
            return action(session)
    except TenantCryptoError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc


@router.get("/status")
def status(request: Request, user_id: int):
    _maintainer(request)
    from storage.entity.tenant_key import TenantKeyEntity
    from storage.entity.user import UserEntity
    from storage.crypto.tenant import is_legacy_account

    def read(session):
        user = session.get(UserEntity, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="tenant_user_missing")
        rows = session.query(TenantKeyEntity).filter_by(user_id=user_id).all()
        active = next((row.key_id for row in rows if row.status == "active"), None)
        return {
            "user_id": user_id,
            "legacy_account": is_legacy_account(user),
            "encryption_eligible": bool(user.encryption_eligible),
            "enable_blocked": True,
            "active_key_id": active,
            "keys": [{"key_id": row.key_id, "status": row.status} for row in rows],
        }

    return _run(read)


@router.post("/enable")
def enable(body: UserBody, request: Request):
    _maintainer(request)
    from storage.crypto.tenant import enable_tenant

    _run(lambda session: enable_tenant(session, body.user_id))
    return {"enabled": False}


@router.post("/rotate-dek")
def rotate(body: UserBody, request: Request):
    _maintainer(request)
    from storage.crypto.tenant import rotate_dek

    key_id = _run(lambda session: rotate_dek(session, body.user_id))
    return {"key_id": key_id}


@router.post("/shred")
def shred(body: UserBody, request: Request):
    """Crypto-shred. Backups keep the wrapped DEK until retention expires."""
    _maintainer(request)
    from storage.crypto.tenant import shred_tenant

    deleted = _run(lambda session: shred_tenant(session, body.user_id))
    return {"deleted_keys": deleted}


@router.post("/rewrap")
def rewrap(request: Request):
    _maintainer(request)
    from storage.crypto.tenant import rewrap_keys

    count = _run(rewrap_keys)
    return {"rewrapped": count}
