from __future__ import annotations

import datetime
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field

from fava.util.date import parse_date

from storage.service import finance_config as finance_config_service
from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_positions as positions_service
from storage.service import finance_realtime_quote as realtime_quote_service
from storage.service import finance_transaction as transaction_service


TIME_RANGE_ALIASES = {
    "ytd": "year to day-1",
    "mtd": "month to day-1",
    "qtd": "quarter to day-1",
    "1m": "day-30 to day-1",
    "3m": "day-90 to day-1",
    "1y": "day-365 to day-1",
    "all": "",
}


class ConversionError(ValueError):
    pass


class PriceLookup:
    def __init__(self, rows, overlay: dict[str, float] | None = None):
        self._prices: dict[tuple[str, str], list[tuple[datetime.date, float]]] = defaultdict(list)
        self._overlay = {symbol.upper(): float(price) for symbol, price in (overlay or {}).items()}
        for row in rows:
            price_date = row.price_date if isinstance(row.price_date, datetime.date) else datetime.date.fromisoformat(row.price_date)
            self._prices[(row.symbol, row.currency)].append((price_date, float(row.price)))
        for prices in self._prices.values():
            prices.sort(key=lambda item: item[0])

    def latest(self, symbol: str, currency: str, as_of: datetime.date) -> float | None:
        if currency == "USD":
            overlay_price = self._overlay.get(symbol.upper())
            if overlay_price is not None:
                return overlay_price
        prices = self._prices.get((symbol, currency))
        if not prices:
            return None
        index = bisect_right(prices, (as_of, float("inf")))
        if index == 0:
            return None
        return prices[index - 1][1]


def _today() -> datetime.date:
    return datetime.date.today()


def _format_realtime_synced_at(value: datetime.datetime | None) -> str:
    return value.isoformat().replace("+00:00", "Z") if value else ""


def parse_time_range(time_filter: str, default: str | None = None) -> tuple[datetime.date | None, datetime.date | None]:
    value = (time_filter or default or "").strip()
    value = TIME_RANGE_ALIASES.get(value.lower(), value)
    if not value:
        return None, None
    return parse_date(value)


def period_boundaries(start_date: datetime.date, end_date: datetime.date, granularity: str):
    periods = []
    if granularity == "weekly":
        cur = start_date - datetime.timedelta(days=start_date.weekday())
        while cur < end_date:
            next_period = cur + datetime.timedelta(days=7)
            iso_year, iso_week, _ = cur.isocalendar()
            periods.append((cur, min(next_period, end_date), f"{iso_year}-W{iso_week:02d}"))
            cur = next_period
    elif granularity == "monthly":
        cur = start_date.replace(day=1)
        while cur < end_date:
            next_period = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            periods.append((cur, min(next_period, end_date), cur.strftime("%Y-%m")))
            cur = next_period
    elif granularity == "quarterly":
        start_month = ((start_date.month - 1) // 3) * 3 + 1
        cur = start_date.replace(month=start_month, day=1)
        while cur < end_date:
            next_year = cur.year + ((cur.month + 2) // 12)
            next_month = ((cur.month + 2) % 12) + 1
            next_period = cur.replace(year=next_year, month=next_month, day=1)
            quarter = ((cur.month - 1) // 3) + 1
            periods.append((cur, min(next_period, end_date), f"{cur.year}-Q{quarter}"))
            cur = next_period
    else:
        cur = start_date.replace(month=1, day=1)
        while cur < end_date:
            next_period = cur.replace(year=cur.year + 1)
            periods.append((cur, min(next_period, end_date), str(cur.year)))
            cur = next_period
    return periods


def convert(user_id: int, vm_name: str, amount: float, from_ccy: str, to_ccy: str, as_of: datetime.date | None, lookup: PriceLookup | None = None) -> float:
    from_currency = from_ccy or to_ccy
    to_currency = to_ccy or from_currency
    if from_currency == to_currency:
        return amount
    price_date = as_of or _today()
    if lookup:
        direct_price = lookup.latest(from_currency, to_currency, price_date)
        if direct_price is not None:
            return amount * direct_price
        inverse_price = lookup.latest(to_currency, from_currency, price_date)
        if inverse_price:
            return amount / inverse_price
    direct = price_service.latest_pair(from_currency, to_currency, price_date)
    if direct:
        return amount * float(direct.price)
    inverse = price_service.latest_pair(to_currency, from_currency, price_date)
    if inverse and inverse.price:
        return amount / float(inverse.price)
    raise ConversionError(f"No price found for {from_currency} -> {to_currency}")


def convert_balance(user_id: int, vm_name: str, balance: dict[str, float], target_currency: str, as_of: datetime.date | None, lookup: PriceLookup | None = None) -> dict[str, float]:
    total = 0.0
    for currency, amount in balance.items():
        total += convert(user_id, vm_name, amount, currency, target_currency, as_of, lookup)
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


def convert_tree(user_id: int, vm_name: str, node: dict, target_currency: str, as_of: datetime.date | None, lookup: PriceLookup | None = None) -> dict:
    children = [convert_tree(user_id, vm_name, child, target_currency, as_of, lookup) for child in node["children"]]
    children.sort(key=lambda child: abs(_tree_total(child)), reverse=True)
    return {
        "account": node["account"],
        "balance": convert_balance(user_id, vm_name, node["balance"], target_currency, as_of, lookup) if node["balance"] else {},
        "children": children,
    }


def _posting_amount(row) -> tuple[str, float] | None:
    if row.amount is None:
        return None
    currency = row.amount_currency or row.symbol or row.cost_currency or row.price_currency
    if not currency:
        return None
    return currency, float(row.amount)


def _position_amount(row) -> tuple[str, float] | None:
    if row.quantity is not None and row.symbol:
        return row.symbol, float(row.quantity)
    return _posting_amount(row)


def _sum_rows(rows) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        amount = _posting_amount(row)
        if not amount:
            continue
        currency, value = amount
        totals[row.account][currency] += value
    return {account: dict(balance) for account, balance in totals.items()}


def _tree_rows(totals: dict[str, dict[str, float]], root: str, user_id: int, vm_name: str, convert_to: str | None, as_of: datetime.date | None, lookup: PriceLookup | None = None):
    rows = []
    for account, balances in totals.items():
        if account != root and not account.startswith(f"{root}:"):
            continue
        for currency, amount in balances.items():
            if not amount:
                continue
            if convert_to:
                amount = convert(user_id, vm_name, amount, currency, convert_to, as_of, lookup)
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


def _sum_balances(balances_by_key: dict[str, dict[str, float]]) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for balances in balances_by_key.values():
        for currency, amount in balances.items():
            result[currency] += amount
    return dict(result)


def _add_posting_total(totals: dict[str, dict[str, float]], row) -> None:
    amount = _posting_amount(row)
    if not amount:
        return
    currency, value = amount
    totals[row.account][currency] += value


def _add_position_total(totals: dict[str, dict[str, float]], row, root: str) -> None:
    if row.account != root and not row.account.startswith(f"{root}:"):
        return
    amount = _position_amount(row)
    if not amount:
        return
    symbol, value = amount
    totals[symbol][symbol] += value


def _parsed_transaction_rows(rows) -> list[tuple[datetime.date, object]]:
    return [(transaction_date, row) for transaction_date, _index, row in sorted((datetime.date.fromisoformat(row.transaction_date), index, row) for index, row in enumerate(rows))]


def _copy_balances(balances: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {key: dict(value) for key, value in balances.items()}


def _build_realtime_overlay(user_id: int) -> tuple[dict[str, float], str, str]:
    symbols = sorted({
        row.symbol.upper()
        for row in holding_service.list_for(user_id)
        if not getattr(row, "is_cash", False)
        and getattr(row, "symbol", None)
        and (getattr(row, "cost_currency", "") or "").upper() == "USD"
        and getattr(row, "quantity", None) is not None
    })
    if not symbols:
        return {}, "", "none"
    try:
        result = realtime_quote_service.fetch_bulk(symbols)
    except Exception:
        return {}, "", "none"
    return {symbol: float(quote.close) for symbol, quote in result.quotes.items()}, _format_realtime_synced_at(result.fetched_at), result.source


def _realtime_meta(synced_at: str, source: str) -> dict:
    return {"realtime_synced_at": synced_at or "", "realtime_source": source or "none"}


def _should_build_realtime_overlay(convert_to: str | None, end_date: datetime.date | None) -> bool:
    return (convert_to or "").upper() == "USD" and (end_date is None or end_date >= _today())


def _price_lookup_for_balances(user_id: int, vm_name: str, balances: dict[str, dict[str, float]], target_currency: str | None, as_of: datetime.date, overlay: dict[str, float] | None = None) -> PriceLookup | None:
    if not target_currency:
        return None
    pairs = set()
    for balance in balances.values():
        for currency in balance:
            if currency and currency != target_currency:
                pairs.add((currency, target_currency))
                pairs.add((target_currency, currency))
    return PriceLookup(price_service.list_for_pairs(pairs, as_of), overlay=overlay)


def _price_lookup_for_roots(user_id: int, vm_name: str, totals: dict[str, dict[str, float]], roots: tuple[str, ...], target_currency: str | None, as_of: datetime.date, overlay: dict[str, float] | None = None) -> PriceLookup | None:
    if not target_currency:
        return None
    balances = {root: _root_sum(totals, root) for root in roots}
    return _price_lookup_for_balances(user_id, vm_name, balances, target_currency, as_of, overlay=overlay)


def _position_totals(rows, root: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if row.account != root and not row.account.startswith(f"{root}:"):
            continue
        amount = _position_amount(row)
        if not amount:
            continue
        symbol, value = amount
        result[symbol][symbol] += value
    return {symbol: dict(balance) for symbol, balance in result.items()}


def _convert_account_balances(user_id: int, vm_name: str, accounts: dict[str, dict[str, float]], target_currency: str, as_of: datetime.date | None, lookup: PriceLookup | None = None) -> dict[str, dict[str, float]]:
    return {
        account: convert_balance(user_id, vm_name, balance, target_currency, as_of, lookup) if balance else {target_currency: 0.0}
        for account, balance in accounts.items()
    }


def _synced_at(user_id: int, vm_name: str) -> str:
    return transaction_service.latest_synced_at(user_id) or ""


@dataclass
class DerivedResult:
    data: dict | list
    synced_at: str
    meta: dict = field(default_factory=dict)


def balance_sheet(user_id: int, vm_name: str, time_filter: str, history: bool, granularity: str, convert_to: str | None) -> DerivedResult:
    start_date, end_date = parse_time_range(time_filter)
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    assets_root = roots["assets"]
    liabilities_root = roots["liabilities"]
    if not history:
        rows = transaction_service.list_between(user_id, end_date=end_date)
        totals = _sum_rows(rows)
        as_of = end_date - datetime.timedelta(days=1) if end_date else _today()
        overlay, realtime_synced_at, realtime_source = _build_realtime_overlay(user_id) if _should_build_realtime_overlay(convert_to, end_date) else ({}, "", "none")
        lookup = _price_lookup_for_roots(user_id, vm_name, totals, (assets_root,), convert_to, as_of, overlay=overlay) if convert_to else None
        result = {
            "assets": prune_zero_balance_accounts(build_tree(_tree_rows(totals, assets_root, user_id, vm_name, convert_to, as_of, lookup), assets_root, convert_to)),
            "liabilities": prune_zero_balance_accounts(build_tree(_tree_rows(totals, liabilities_root, user_id, vm_name, convert_to, as_of), liabilities_root, convert_to)),
        }
        return DerivedResult(result, _synced_at(user_id, vm_name), _realtime_meta(realtime_synced_at, realtime_source))

    if start_date is None or end_date is None:
        end_date = end_date or _today() + datetime.timedelta(days=1)
        start_date = start_date or end_date.replace(year=end_date.year - 1)
    rows = transaction_service.list_between(user_id, end_date=end_date)
    result = []
    dated_rows = _parsed_transaction_rows(rows)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    row_index = 0
    lookup = None
    if convert_to:
        all_totals = _sum_rows(rows)
        lookup = _price_lookup_for_roots(user_id, vm_name, all_totals, (assets_root, liabilities_root), convert_to, end_date - datetime.timedelta(days=1))
    for _p_start, period_end, label in period_boundaries(start_date, end_date, granularity):
        while row_index < len(dated_rows) and dated_rows[row_index][0] < period_end:
            _add_posting_total(totals, dated_rows[row_index][1])
            row_index += 1
        item = {"period": label, "assets": _root_sum(totals, assets_root), "liabilities": _root_sum(totals, liabilities_root)}
        if convert_to:
            as_of = period_end - datetime.timedelta(days=1)
            item["assets"] = convert_balance(user_id, vm_name, item["assets"], convert_to, as_of, lookup) if item["assets"] else {convert_to: 0.0}
            item["liabilities"] = convert_balance(user_id, vm_name, item["liabilities"], convert_to, as_of, lookup) if item["liabilities"] else {convert_to: 0.0}
        result.append(item)
    return DerivedResult(result, _synced_at(user_id, vm_name))



def balance_sheet_positions(user_id: int, vm_name: str, time_filter: str, granularity: str, convert_to: str | None, risky_only: bool = False) -> DerivedResult:
    start_date, end_date = parse_time_range(time_filter)
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    assets_root = roots["assets"]
    risky_symbols = {row.symbol for row in holding_service.list_for(user_id, risky_only=True)}
    if start_date is None or end_date is None:
        end_date = end_date or _today() + datetime.timedelta(days=1)
        start_date = start_date or end_date.replace(year=end_date.year - 1)
    rows = transaction_service.list_between(user_id, end_date=end_date)
    result = []
    dated_rows = _parsed_transaction_rows(rows)
    positions: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    row_index = 0
    lookup = None
    if convert_to:
        all_positions = _position_totals(rows, assets_root)
        overlay, realtime_synced_at, realtime_source = _build_realtime_overlay(user_id) if _should_build_realtime_overlay(convert_to, end_date) else ({}, "", "none")
        lookup = _price_lookup_for_balances(user_id, vm_name, all_positions, convert_to, end_date - datetime.timedelta(days=1), overlay=overlay)
    else:
        realtime_synced_at, realtime_source = "", "none"
    for _p_start, period_end, label in period_boundaries(start_date, end_date, granularity):
        while row_index < len(dated_rows) and dated_rows[row_index][0] < period_end:
            _add_position_total(positions, dated_rows[row_index][1], assets_root)
            row_index += 1
        period_positions = _copy_balances(positions)
        total_positions = period_positions
        risky_positions = {symbol: balance for symbol, balance in period_positions.items() if symbol in risky_symbols}
        if risky_only:
            period_positions = risky_positions
        if convert_to:
            as_of = period_end - datetime.timedelta(days=1)
            total_positions = _convert_account_balances(user_id, vm_name, total_positions, convert_to, as_of, lookup)
            period_positions = _convert_account_balances(user_id, vm_name, period_positions, convert_to, as_of, lookup)
            risky_positions = _convert_account_balances(user_id, vm_name, risky_positions, convert_to, as_of, lookup)
        total = _sum_balances(total_positions)
        risky_total = _sum_balances(risky_positions)
        result.append({"period": label, "positions": period_positions, "total": total if total else ({convert_to: 0.0} if convert_to else {}), "risky": risky_total if risky_total else ({convert_to: 0.0} if convert_to else {})})
    return DerivedResult(result, _synced_at(user_id, vm_name), _realtime_meta(realtime_synced_at, realtime_source))


def income_statement(user_id: int, vm_name: str, time_filter: str, history: bool, granularity: str, convert_to: str | None) -> DerivedResult:
    start_date, end_date = parse_time_range(time_filter, default="month")
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    income_root = roots["income"]
    expenses_root = roots["expenses"]
    if not history:
        rows = transaction_service.list_between(user_id, start_date=start_date, end_date=end_date)
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
    rows = transaction_service.list_between(user_id, start_date=start_date, end_date=end_date)
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


def _expense_category(account: str, expenses_root: str) -> str | None:
    prefix = f"{expenses_root}:"
    if not account.startswith(prefix):
        return None
    child = account[len(prefix):].split(":", 1)[0]
    return f"{expenses_root}:{child}" if child else None


def _expense_category_totals(rows, expenses_root: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        category = _expense_category(row.account, expenses_root)
        if not category:
            continue
        amount = _posting_amount(row)
        if not amount:
            continue
        currency, value = amount
        result[category][currency] += value
    return {category: dict(balance) for category, balance in result.items()}


def income_statement_categories(user_id: int, vm_name: str, time_filter: str, granularity: str, convert_to: str | None) -> DerivedResult:
    start_date, end_date = parse_time_range(time_filter, default="month")
    roots = finance_config_service.get_for(user_id, vm_name)["account_roots"]
    expenses_root = roots["expenses"]
    if start_date is None or end_date is None:
        end_date = end_date or _today() + datetime.timedelta(days=1)
        start_date = start_date or end_date.replace(year=end_date.year - 1)
    rows = transaction_service.list_between(user_id, start_date=start_date, end_date=end_date)
    result = []
    lookup = None
    if convert_to:
        all_categories = _expense_category_totals(rows, expenses_root)
        lookup = _price_lookup_for_balances(user_id, vm_name, all_categories, convert_to, end_date - datetime.timedelta(days=1))
    for period_start, period_end, label in period_boundaries(start_date, end_date, granularity):
        period_rows = (row for row in rows if period_start <= datetime.date.fromisoformat(row.transaction_date) < period_end)
        categories = _expense_category_totals(period_rows, expenses_root)
        if convert_to:
            as_of = period_end - datetime.timedelta(days=1)
            categories = _convert_account_balances(user_id, vm_name, categories, convert_to, as_of, lookup)
        total = _sum_balances(categories)
        result.append({"period": label, "categories": categories, "total": total if total else ({convert_to: 0.0} if convert_to else {})})
    return DerivedResult(result, _synced_at(user_id, vm_name))


def holding_positions(user_id: int, vm_name: str, at: str | None = None, risky_only: bool = False, base_currency: str = "USD") -> DerivedResult:
    result = positions_service.derive_positions(user_id, snapshot_date=at, risky_only=risky_only, base_currency=base_currency)
    return DerivedResult(result["data"], result["synced_at"], {"summary": result["summary"]})


def fire_progress(user_id: int, vm_name: str) -> DerivedResult:
    base_currency = "USD"
    today = _today()
    year_start = datetime.date(today.year, 1, 1)
    tomorrow = today + datetime.timedelta(days=1)
    config = finance_config_service.get_for(user_id, vm_name)
    roots = config["account_roots"]
    balance_rows = transaction_service.list_between(user_id, end_date=tomorrow)
    balance_totals = _sum_rows(balance_rows)
    overlay, realtime_synced_at, realtime_source = _build_realtime_overlay(user_id)
    assets_lookup = _price_lookup_for_roots(user_id, vm_name, balance_totals, (roots["assets"],), base_currency, today, overlay=overlay)
    assets_usd = convert_balance(user_id, vm_name, _root_sum(balance_totals, roots["assets"]), base_currency, today, assets_lookup).get(base_currency, 0)
    liabilities_usd = convert_balance(user_id, vm_name, _root_sum(balance_totals, roots["liabilities"]), base_currency, today).get(base_currency, 0)
    net_worth_usd = round(assets_usd + liabilities_usd, 2)

    rows = transaction_service.list_between(user_id, start_date=year_start, end_date=tomorrow)
    totals = _sum_rows(rows)
    ytd_income_usd = round(abs(convert_balance(user_id, vm_name, _root_sum(totals, roots["income"]), base_currency, today).get(base_currency, 0)), 2)
    ytd_expense_usd = round(convert_balance(user_id, vm_name, _root_sum(totals, roots["expenses"]), base_currency, today).get(base_currency, 0), 2)

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
    }, _synced_at(user_id, vm_name), _realtime_meta(realtime_synced_at, realtime_source))
