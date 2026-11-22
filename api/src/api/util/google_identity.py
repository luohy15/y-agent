"""Verify a Google ID token the same way login and access requests do."""

import os

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")


class GoogleIdentityError(ValueError):
    """The token is missing, invalid, or the email is not verified."""


def verify_google_id_token(raw: str) -> dict:
    if not raw or not GOOGLE_CLIENT_ID:
        raise GoogleIdentityError("invalid")
    try:
        idinfo = id_token.verify_oauth2_token(
            raw,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError as exc:
        raise GoogleIdentityError("invalid") from exc
    email = idinfo.get("email")
    if not email or idinfo.get("email_verified") is not True:
        raise GoogleIdentityError("unverified")
    normalized = str(email).strip().lower()
    name = idinfo.get("name") or normalized.split("@")[0]
    return {"email": normalized, "name": name}
