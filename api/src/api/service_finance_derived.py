from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass

from fava.util.date import parse_date

from storage.service import finance_config as finance_config_service
from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_transaction as transaction_service


class ConversionError(ValueError):
    pass


def _today() -> datetime.date:
    return datetime.date.today()


def parse_time_range(time_filter: str, default: str | None = None) -> tuple[datetime.date | None, datetime.date | None]:
    value = time_filter or default or ""
    if not value:
        return None, None
    return parse_date(value)


def period_boundaries(start_date: datetime.date, end_date: datetime.date, granularity: str):
    periods = []
    if granularity == "monthly":
        cur = start_date.replace(day=1)
        while cur < end_date:
            next_period = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            periods.append((cur, min(next_period, end_date), cur.strftime("%Y-%m")))
            cur = next_period
    else:
        cur = start_date.replace(month=1, day=1)
        while cur < end_date:
            next_period = cur.replace(year=cur.year + 1)
            periods.append((cur, min(next_period, end_date), str(cur.year)))
            cur = next_period
    return periods


def convert(user_id: int, vm_name: str, amount: float, from_ccy: str, to_ccy: str, as_of: datetime.date | None) -> float:
    from_currency = from_ccy or to_ccy
    to_currency = to_ccy or from_currency
    if from_currency == to_currency:
        return amount
    price_date = as_of or _today()
    direct = price_service.latest_pair(user_id, vm_name, from_currency, to_currency, price_date)
    if direct:
        return amount * float(direct.price)
    inverse = price_service.latest_pair(user_id, vm_name, to_currency, from_currency, price_date)
    if inverse and inverse.price:
        return amount / float(inverse.price)
    raise ConversionError(f"No price found for {from_currency} -> {to_currency}")


def convert_balance(user_id: int, vm_name: str, balance: dict[str, float], target_currency: str, as_of: datetime.date | None) -> dict[str, float]:
    total = 0.0
    for currency, amount in balance.items():
        total += convert(user_id, vm_name, amount, currency, target_currency, as_of)
    return {target_currency: round(total, 2)}


def _parse_snapshot_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    return datetime.date.fromisoformat(value[:10])


def _tree_total(node: dict) -> float:
    return sum(node["balance"].values()) + sum(_tree_total(child) for child in node["children"])


def _has_nonzero_balance(balance: dict[str, float]) -> bool:
    return any(abs(amount) > 0.005 for amount in balance.values())


def prune_zero_balance_accounts(node: dict) -> dict:
    children = [prune_zero_balance_accounts(child) for child in node["children"]]
    children = [child for child in children if _has_nonzero_balance(_aggregate_balance(child))]
    return {"account": node["account"], "balance": node["balance"], "children": children}


def _aggregate_balance(node: dict) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for currency, amount in node["balance"].items():
        result[currency] += amount
    for child in node["children"]:
        for currency, amount in _aggregate_balance(child).items():
            result[currency] += amount
    return dict(result)


def build_tree(rows: list[tuple[str, str, float]], root_account: str, base_currency: str | None = None) -> dict:
    nodes: dict[str, dict] = {}

    def node_for(account: str) -> dict:
        if account not in nodes:
            nodes[account] = {"account": account, "balance": {}, "children": []}
        return nodes[account]

    root = node_for(root_account)
    accounts = {account for account, _currency, _amount in rows if account == root_account or account.startswith(f"{root_account}:")}
    for account in sorted(accounts):
        parts = account.split(":")
        for index in range(1, len(parts) + 1):
            current = ":".join(parts[:index])
            node_for(current)
            if index > 1:
                parent = node_for(":".join(parts[:index - 1]))
                child = node_for(current)
                if child not in parent["children"]:
                    parent["children"].append(child)
    for account, currency, amount in rows:
        if account not in nodes:
            continue
        balance = nodes[account]["balance"]
        key = base_currency or currency
        balance[key] = round(balance.get(key, 0.0) + amount, 2)
    for node in nodes.values():
        node["children"].sort(key=lambda child: child["account"])
    return root


def convert_tree(user_id: int, vm_name: str, node: dict, target_currency: str, as_of: datetime.date | None) -> dict:
    children = [convert_tree(user_id, vm_name, child, target_currency, as_of) for child in node["children"]]
    children.sort(key=lambda child: abs(_tree_total(child)), reverse=True)
    return {
        "account": node["account"],
        "balance": convert_balance(user_id, vm_name, node["balance"], target_currency, as_of) if node["balance"] else {},
        "children": children,
    }


def _posting_amount(row) -> tuple[str, float] | None:
    if row.amount is None:
        return None
    currency = row.amount_currency or row.symbol or row.cost_currency or row.price_currency
    if not currency:
        return None
    return currency, float(row.amount)


def _sum_rows(rows) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        amount = _posting_amount(row)
        if not amount:
            continue
        currency, value = amount
        totals[row.account][currency] += value
    return {account: dict(balance) for account, balance in totals.items()}


def _tree_rows(totals: dict[str, dict[str, float]], root: str, user_id: int, vm_name: str, convert_to: str | None, as_of: datetime.date | None):
    rows = []
    for account, balances in totals.items():
        if account != root and not account.startswith(f"{root}:"):
            continue
        for currency, amount in balances.items():
            if not amount:
                continue
            if convert_to:
                amount = convert(user_id, vm_name, amount, currency, convert_to, as_of)
                currency = convert_to
            rows.append((account, currency, amount))
    return rows


def _root_sum(totals: dict[str, dict[str, float]], root: str) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for account, balances in totals.items():
        if account == root or account.startswith(f"{root}:"):
            for currency, amount in balances.items():
                result[currency] += amount
    return dict(result)


def _synced_at(user_id: int, vm_name: str) -> str:
    return transaction_service.latest_synced_at(user_id, vm_name) or ""


@dataclass
class DerivedResult:
    data: dict | list
    synced_at: str


def balance_sheet(user_id: int, vm_name: str, time_filter: str, history: bool, granularity: str, convert_to: str | None) -> DerivedResult:
    start_date, end_date = parse_time_range(time_filter)
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    assets_root = roots["assets"]
    liabilities_root = roots["liabilities"]
    if not history:
        rows = transaction_service.list_between(user_id, vm_name, end_date=end_date)
        totals = _sum_rows(rows)
        as_of = end_date - datetime.timedelta(days=1) if end_date else _today()
        result = {
            "assets": prune_zero_balance_accounts(build_tree(_tree_rows(totals, assets_root, user_id, vm_name, convert_to, as_of), assets_root, convert_to)),
            "liabilities": prune_zero_balance_accounts(build_tree(_tree_rows(totals, liabilities_root, user_id, vm_name, convert_to, as_of), liabilities_root, convert_to)),
        }
        return DerivedResult(result, _synced_at(user_id, vm_name))

    if start_date is None or end_date is None:
        end_date = end_date or _today() + datetime.timedelta(days=1)
        start_date = start_date or end_date.replace(year=end_date.year - 1)
    rows = transaction_service.list_between(user_id, vm_name, end_date=end_date)
    result = []
    for _p_start, period_end, label in period_boundaries(start_date, end_date, granularity):
        totals = _sum_rows(row for row in rows if datetime.date.fromisoformat(row.transaction_date) < period_end)
        item = {"period": label, "assets": _root_sum(totals, assets_root), "liabilities": _root_sum(totals, liabilities_root)}
        if convert_to:
            as_of = period_end - datetime.timedelta(days=1)
            item["assets"] = convert_balance(user_id, vm_name, item["assets"], convert_to, as_of) if item["assets"] else {convert_to: 0.0}
            item["liabilities"] = convert_balance(user_id, vm_name, item["liabilities"], convert_to, as_of) if item["liabilities"] else {convert_to: 0.0}
        result.append(item)
    return DerivedResult(result, _synced_at(user_id, vm_name))


def income_statement(user_id: int, vm_name: str, time_filter: str, history: bool, granularity: str, convert_to: str | None) -> DerivedResult:
    start_date, end_date = parse_time_range(time_filter, default="month")
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    income_root = roots["income"]
    expenses_root = roots["expenses"]
    if not history:
        rows = transaction_service.list_between(user_id, vm_name, start_date=start_date, end_date=end_date)
        totals = _sum_rows(rows)
        as_of = end_date - datetime.timedelta(days=1) if end_date else _today()
        result = {
            "income": build_tree(_tree_rows(totals, income_root, user_id, vm_name, convert_to, as_of), income_root, convert_to),
            "expenses": build_tree(_tree_rows(totals, expenses_root, user_id, vm_name, convert_to, as_of), expenses_root, convert_to),
        }
        return DerivedResult(result, _synced_at(user_id, vm_name))

    if start_date is None or end_date is None:
        end_date = end_date or _today() + datetime.timedelta(days=1)
        start_date = start_date or end_date.replace(year=end_date.year - 1)
    rows = transaction_service.list_between(user_id, vm_name, start_date=start_date, end_date=end_date)
    result = []
    for period_start, period_end, label in period_boundaries(start_date, end_date, granularity):
        totals = _sum_rows(row for row in rows if period_start <= datetime.date.fromisoformat(row.transaction_date) < period_end)
        item = {"period": label, "income": _root_sum(totals, income_root), "expenses": _root_sum(totals, expenses_root)}
        if convert_to:
            as_of = period_end - datetime.timedelta(days=1)
            item["income"] = convert_balance(user_id, vm_name, item["income"], convert_to, as_of) if item["income"] else {convert_to: 0.0}
            item["expenses"] = convert_balance(user_id, vm_name, item["expenses"], convert_to, as_of) if item["expenses"] else {convert_to: 0.0}
        result.append(item)
    return DerivedResult(result, _synced_at(user_id, vm_name))


def holding_positions(user_id: int, vm_name: str, at: str | None = None, risky_only: bool = False, base_currency: str = "USD") -> DerivedResult:
    holdings = holding_service.list_at(user_id, vm_name, at, risky_only=risky_only) if at else holding_service.list_for(user_id, vm_name, risky_only=risky_only)
    rows = holding_service.with_effective_values(holdings)
    base_values = []
    for holding, row in zip(holdings, rows):
        market_value = row.get("market_value")
        if market_value is None:
            base_values.append(None)
            continue
        currency = row.get("cost_currency") or row.get("symbol") or base_currency
        as_of = _parse_snapshot_date(row.get("snapshot_date") or getattr(holding, "snapshot_date", None)) or _today()
        base_values.append(convert(user_id, vm_name, float(market_value), currency, base_currency, as_of))

    total_base_market_value = sum(value for value in base_values if value is not None)
    for row, base_value in zip(rows, base_values):
        row["allocation_base_currency"] = base_currency
        row["market_value_base"] = round(base_value, 2) if base_value is not None else None
        row["allocation_pct"] = round(base_value / total_base_market_value * 100, 4) if base_value is not None and total_base_market_value else None

    return DerivedResult(rows, holdings[0].synced_at if holdings else "")


def fire_progress(user_id: int, vm_name: str) -> DerivedResult:
    base_currency = "USD"
    today = _today()
    holdings = holding_service.list_for(user_id, vm_name)
    net_worth = 0.0
    for row in holdings:
        amount = float(row.market_value or 0)
        currency = row.cost_currency or row.symbol or base_currency
        net_worth += convert(user_id, vm_name, amount, currency, base_currency, today)
    net_worth_usd = round(net_worth, 2)

    year_start = datetime.date(today.year, 1, 1)
    tomorrow = today + datetime.timedelta(days=1)
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    rows = transaction_service.list_between(user_id, vm_name, start_date=year_start, end_date=tomorrow)
    totals = _sum_rows(rows)
    ytd_income_usd = round(abs(convert_balance(user_id, vm_name, _root_sum(totals, roots["income"]), base_currency, today).get(base_currency, 0)), 2)
    ytd_expense_usd = round(convert_balance(user_id, vm_name, _root_sum(totals, roots["expenses"]), base_currency, today).get(base_currency, 0), 2)

    config = finance_config_service.get_for(user_id, vm_name)
    monthly_expense_usd = float(config["monthly_expense_usd"])
    withdrawal_rate = float(config["withdrawal_rate"])
    target_usd = float(config["target_usd"])
    ytd_savings_rate = round((ytd_income_usd - ytd_expense_usd) / ytd_income_usd, 4) if ytd_income_usd > 0 else None
    gap_usd = round(target_usd - net_worth_usd, 2)
    progress_pct = round(net_worth_usd / target_usd * 100, 2) if target_usd > 0 else None
    days_elapsed = max((today - year_start).days + 1, 1)
    months_elapsed = days_elapsed / 30.44
    monthly_savings = (ytd_income_usd - ytd_expense_usd) / months_elapsed if months_elapsed > 0 else 0
    if gap_usd <= 0:
        projected_months = 0
        projected_date = today.isoformat()
    elif monthly_savings > 0:
        months = gap_usd / monthly_savings
        projected_months = round(months, 1)
        projected_date = (today + datetime.timedelta(days=months * 30.44)).isoformat()
    else:
        projected_months = None
        projected_date = None
    return DerivedResult({
        "net_worth_usd": net_worth_usd,
        "target_usd": round(target_usd, 2),
        "gap_usd": gap_usd,
        "progress_pct": progress_pct,
        "ytd_income_usd": ytd_income_usd,
        "ytd_expense_usd": ytd_expense_usd,
        "ytd_savings_rate": ytd_savings_rate,
        "monthly_expense_usd": monthly_expense_usd,
        "withdrawal_rate": withdrawal_rate,
        "projected_months_to_target": projected_months,
        "projected_date": projected_date,
        "config_source": config["config_source"],
    }, holdings[0].synced_at if holdings else _synced_at(user_id, vm_name))
