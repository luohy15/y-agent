"""Email account service."""

from typing import List, Optional
from storage.dto.email_account import EmailAccount
from storage.repository import email_account as email_account_repo


def list_accounts(user_id: int) -> List[EmailAccount]:
    return email_account_repo.list_accounts(user_id)


def get_account(user_id: int, address: str) -> Optional[EmailAccount]:
    return email_account_repo.get_account(user_id, address)


def add_account(user_id: int, address: str, app_password: str) -> EmailAccount:
    return email_account_repo.add_account(user_id, address, app_password)


def delete_account(user_id: int, address: str) -> bool:
    return email_account_repo.delete_account(user_id, address)
