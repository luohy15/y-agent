import os

import jwt
from fastapi import APIRouter, HTTPException
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from pydantic import BaseModel

from storage.repository.user import get_or_create_user_by_email, get_user_by_email

router = APIRouter(prefix="/auth")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"


def _is_allowlisted(email: str) -> bool:
    """Gate new-account signup behind an invite allowlist.

    Fails closed: an unset/empty SIGNUP_ALLOWLIST allows no new signups (only
    already-existing users can log in), until Phase 1/3 intentionally opens it.
    """
    allowlist = {
        entry.strip().lower()
        for entry in os.environ.get("SIGNUP_ALLOWLIST", "").split(",")
        if entry.strip()
    }
    return email.lower() in allowlist


class GoogleLoginRequest(BaseModel):
    id_token: str


class LoginResponse(BaseModel):
    token: str
    email: str


@router.post("/google", response_model=LoginResponse)
async def google_login(req: GoogleLoginRequest):
    try:
        idinfo = id_token.verify_oauth2_token(
            req.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google ID token")

    email = idinfo.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    username = idinfo.get("name", email.split("@")[0])

    if not get_user_by_email(email) and not _is_allowlisted(email):
        raise HTTPException(
            status_code=403,
            detail="This email is not invited yet. Ask the admin for an invite.",
        )

    user = get_or_create_user_by_email(email, username)
    user_id = user.id

    token = jwt.encode(
        {"user_id": user_id, "email": email},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    return LoginResponse(token=token, email=email)
