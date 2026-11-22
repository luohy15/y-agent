import os

import jwt
from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.util.access_http import access_json
from api.util.google_identity import GoogleIdentityError, verify_google_id_token
from storage.repository.user import get_or_create_user_by_email
from storage.service.user_access import admission_state

router = APIRouter(prefix="/auth")

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"

_REFUSAL = {
    "access_pending": "Your access request is pending approval.",
    "access_required": "This email is not approved. Request access to continue.",
}


class GoogleLoginRequest(BaseModel):
    id_token: str


class LoginResponse(BaseModel):
    token: str
    email: str


@router.post("/google", response_model=LoginResponse)
async def google_login(req: GoogleLoginRequest):
    try:
        identity = verify_google_id_token(req.id_token)
    except GoogleIdentityError as exc:
        raise HTTPException(status_code=401, detail="Invalid Google ID token") from exc

    email = identity["email"]
    state = admission_state(email)
    if state != "approved":
        code = "access_pending" if state == "pending" else "access_required"
        logger.info("access denied email={} code={}", email, code)
        return access_json(403, _REFUSAL[code], code)

    user = get_or_create_user_by_email(email, identity["name"])
    token = jwt.encode(
        {"user_id": user.id, "email": email},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    return LoginResponse(token=token, email=email)
