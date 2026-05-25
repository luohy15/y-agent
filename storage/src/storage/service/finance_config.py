"""Persisted finance configuration stored on vm_config.finance_config."""

from __future__ import annotations

from typing import Any

from storage.service import vm_config as vm_config_service

DEFAULT_FIRE_CONFIG = {
    "monthly_expense_usd": 5000.0,
    "withdrawal_rate": 0.04,
}
DEFAULT_ACCOUNT_ROOTS = {
    "assets": "Assets",
    "liabilities": "Liabilities",
    "income": "Income",
    "expenses": "Expenses",
}


def _config_name(vm_name: str | None) -> str:
    return vm_name or "default"


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_config(raw: dict | None, source: str = "db") -> dict:
    raw = dict(raw or {})
    monthly_expense = _coerce_float(raw.get("monthly_expense_usd"), DEFAULT_FIRE_CONFIG["monthly_expense_usd"])
    withdrawal_rate = _coerce_float(raw.get("withdrawal_rate"), DEFAULT_FIRE_CONFIG["withdrawal_rate"])
    target = _coerce_float(raw.get("target_usd"))
    if target is None:
        target = round(monthly_expense * 12 / withdrawal_rate, 2) if withdrawal_rate else 0.0
    account_roots = {**DEFAULT_ACCOUNT_ROOTS, **dict(raw.get("account_roots") or {})}
    config_source = raw.get("config_source") or raw.get("source") or source
    return {
        "monthly_expense_usd": float(monthly_expense or 0),
        "withdrawal_rate": float(withdrawal_rate or 0),
        "target_usd": float(target or 0),
        "account_roots": account_roots,
        "config_source": config_source,
    }


def get_for(user_id: int, vm_name: str | None) -> dict:
    config = vm_config_service.get_config(user_id, _config_name(vm_name))
    if not config and vm_name:
        config = vm_config_service.get_config(user_id, "default")
    if not config:
        return _normalize_config({}, source="default")
    raw = dict(config.finance_config or {})
    if not raw:
        return _normalize_config({}, source="default")
    return _normalize_config(raw, source="db")


def set_for(user_id: int, vm_name: str | None, partial_dict: dict) -> dict:
    name = _config_name(vm_name)
    config = vm_config_service.get_config(user_id, name)
    if not config:
        config = vm_config_service.get_config(user_id, "default")
    if not config:
        raise ValueError(f"VM config not found for {name!r}")
    merged = {**dict(config.finance_config or {}), **dict(partial_dict or {})}
    config.finance_config = _normalize_config(merged, source=merged.get("config_source") or "db")
    vm_config_service.set_config(user_id, config)
    return get_for(user_id, config.name)
