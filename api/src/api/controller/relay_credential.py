"""Owner status and maintainer provisioning for sealed per-user relay keys."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from storage.service import relay_credential as service
from storage.service.user import get_module_maintainer_user_id

router = APIRouter(prefix="/relay-credential")


class ProvisionBody(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["provision", "set", "rotate"]
    user_id: str | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    relay_origin: str | None = None
    relay_key_id: str | None = Field(default=None, max_length=128)
    key_name: str | None = Field(default=None, max_length=100)
    billing_mode: Literal["real", "notional"] | None = None


def _caller(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id


def _maintainer(request: Request) -> int:
    caller = _caller(request)
    owner = get_module_maintainer_user_id()
    if owner is None or caller != owner:
        raise HTTPException(status_code=403, detail="relay credentials are provisioned by the maintainer")
    return caller


@router.get("")
def get_status(request: Request):
    caller = _caller(request)
    try:
        return service.status_for(caller)
    except service.RelayProvisionError as exc:
        raise HTTPException(status_code=400, detail=exc.code) from exc


@router.post("")
def update_credential(request: Request, body: ProvisionBody):
    caller = _maintainer(request)
    try:
        if body.action == "set":
            user_id, public_id = service.resolve_owner(caller, body.user_id)
            return service.store_key(
                user_id,
                public_id,
                body.api_key or "",
                origin=body.relay_origin,
                relay_key_id=body.relay_key_id or "",
                billing_mode=body.billing_mode,
                key_name=body.key_name,
            )
        return service.provision(
            caller,
            body.user_id,
            rotate=body.action == "rotate",
            origin=body.relay_origin,
        )
    except service.RelayCredentialExists as exc:
        raise HTTPException(status_code=409, detail="relay_credential_exists") from exc
    except service.RelayProvisionError as exc:
        status = 404 if exc.code == "user_missing" else 400
        if exc.code == "relay_request_failed":
            status = 502
        raise HTTPException(status_code=status, detail=exc.code) from exc
