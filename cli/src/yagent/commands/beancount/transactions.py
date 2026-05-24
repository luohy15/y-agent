import hashlib
import json

import click


def _num(value):
    return float(value) if value is not None else None


def _entry_id(entry) -> str:
    meta = getattr(entry, "meta", {}) or {}
    filename = meta.get("filename", "")
    lineno = meta.get("lineno", "")
    raw = f"{entry.date}|{filename}|{lineno}|{getattr(entry, 'payee', '')}|{getattr(entry, 'narration', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _posting_side(entry, posting) -> str:
    narration = (getattr(entry, "narration", "") or "").lower()
    payee = (getattr(entry, "payee", "") or "").lower()
    account = posting.account.lower()
    amount = _num(posting.units.number)
    if "dividend" in narration or "dividend" in payee or "income:dividend" in account:
        return "Dividend"
    if "interest" in narration or "interest" in payee or "income:interest" in account:
        return "Interest"
    if "split" in narration:
        return "Split"
    if posting.cost is None and posting.price is not None:
        return "FxConversion"
    if account.startswith("expenses:") and ("tax" in account or "tax" in narration or "fee" in account or "fee" in narration or "commission" in account):
        return "Taxes and fees"
    if account.startswith("assets:") and amount is not None and posting.cost is None:
        if amount > 0:
            return "Deposit"
        if amount < 0:
            return "Withdrawal"
    if amount is not None and amount > 0:
        return "Buy"
    if amount is not None and amount < 0:
        return "Sell"
    return "Unknown"


def _price(posting):
    if posting.price is not None:
        return _num(posting.price.number), posting.price.currency
    if posting.cost is not None:
        return _num(posting.cost.number), posting.cost.currency
    return None, ""


def _cost(posting):
    if posting.cost is None:
        return None, ""
    return _num(posting.units.number) * _num(posting.cost.number), posting.cost.currency


@click.command("transactions")
@click.pass_context
def transactions(ctx):
    """Print beancount postings as normalized transaction rows."""
    from beancount.core.data import Transaction

    rows = []
    for entry in ctx.obj["entries"]:
        if not isinstance(entry, Transaction):
            continue
        entry_id = _entry_id(entry)
        for index, posting in enumerate(entry.postings):
            amount = _num(posting.units.number)
            price, price_currency = _price(posting)
            cost, cost_currency = _cost(posting)
            rows.append({
                "transaction_date": entry.date.isoformat(),
                "entry_id": entry_id,
                "posting_index": index,
                "account": posting.account,
                "symbol": posting.units.currency,
                "side": _posting_side(entry, posting),
                "quantity": amount,
                "price": price,
                "price_currency": price_currency,
                "amount": amount,
                "amount_currency": posting.units.currency,
                "cost": cost,
                "cost_currency": cost_currency,
                "commission": None,
                "commission_currency": "",
                "payee": entry.payee or "",
                "narration": entry.narration or "",
                "tags": sorted(entry.tags or []),
                "links": sorted(entry.links or []),
            })
    click.echo(json.dumps(rows))
