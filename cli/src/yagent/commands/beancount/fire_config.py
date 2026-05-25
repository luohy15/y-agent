import json

import click

from storage.service import finance_config as finance_config_service
from storage.service.user import get_cli_user_id

from .fire_progress import _load_fire_config


@click.group("fire-config")
def fire_config():
    """Manage persisted FIRE configuration."""


@fire_config.command("push")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to update")
@click.option("--vm-name", default="", help="VM config name key")
def push(user_id: int | None, vm_name: str):
    """Push local FIRE config files into vm_config.finance_config."""
    target_user_id = user_id or get_cli_user_id()
    cfg, source = _load_fire_config()
    payload = {
        "monthly_expense_usd": cfg.get("monthly_expense_usd"),
        "withdrawal_rate": cfg.get("withdrawal_rate"),
        "target_usd": cfg.get("target_usd"),
        "config_source": source,
    }
    saved = finance_config_service.set_for(target_user_id, vm_name, payload)
    click.echo(json.dumps(saved))
