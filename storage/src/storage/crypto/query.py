"""Exact-match helpers. Inactive tenants keep the plaintext comparison."""

from __future__ import annotations

from sqlalchemy import false

from storage.crypto.tenant import blind_for_user, encryption_active


def match_bidx(session, user_id: int, column, bidx_column, purpose: str, value: str):
    token = blind_for_user(session, user_id, purpose, value)
    if token is None:
        return column == value
    return bidx_column == token


def prefix_or_exact(session, user_id: int, column, bidx_column, purpose: str, value: str, prefix: bool):
    """Prefix search is exact-only once a tenant is encrypted; plaintext tenants keep LIKE."""
    if prefix and encryption_active(session, user_id):
        return false()
    if prefix:
        return column.like(f"{value}%")
    return match_bidx(session, user_id, column, bidx_column, purpose, value)


def active(session, user_id: int) -> bool:
    return encryption_active(session, user_id)
