from decimal import Decimal

import click

BQL = """\
SELECT
  units(sum(position)) as units,
  safediv(number(only(first(cost_currency), cost(sum(position)))), number(only(first(currency), units(sum(position))))) as average_cost,
  first(getprice(currency, cost_currency)) as price,
  cost(sum(position)) as book_value,
  value(sum(position)) as market_value,
  safediv((abs(sum(number(value(position)))) - abs(sum(number(cost(position))))), sum(number(cost(position)))) * 100 as unrealized_profit_pct
WHERE account_sortkey(account) ~ "^0"
GROUP BY currency, cost_currency
ORDER BY currency, cost_currency"""

BQL_TOTALS = """\
SELECT
  cost(sum(position)) as book_value,
  value(sum(position)) as market_value,
  safediv((abs(sum(number(value(position)))) - abs(sum(number(cost(position))))), sum(number(cost(position)))) * 100 as unrealized_profit_pct
WHERE account_sortkey(account) ~ "^0"
  AND currency != cost_currency
GROUP BY cost_currency
ORDER BY cost_currency"""


def _serialize(val):
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    # Amount (has number + currency)
    if hasattr(val, "number") and hasattr(val, "currency"):
        return {"number": float(val.number), "currency": val.currency}
    # Inventory (iterable of Position)
    if hasattr(val, "is_empty"):
        positions = list(val)
        if len(positions) == 1:
            u = positions[0].units
            return {"number": float(u.number), "currency": u.currency}
        return [{"number": float(p.units.number), "currency": p.units.currency} for p in positions]
    return val


@click.command("holdings")
@click.pass_context
def holdings(ctx):
    """Print holdings with cost basis and unrealized P&L as JSON."""
    import beanquery
    from beanquery.sources.beancount import attach

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]

    conn = beanquery.Connection()
    attach(conn, "", entries=entries, errors=[], options=options)

    cursor = conn.execute(BQL)
    col_names = [d.name for d in cursor.description]
    rows = [
        {name: _serialize(val) for name, val in zip(col_names, row)}
        for row in cursor
    ]

    cursor_totals = conn.execute(BQL_TOTALS)
    total_names = [d.name for d in cursor_totals.description]
    totals = [
        {name: _serialize(val) for name, val in zip(total_names, row)}
        for row in cursor_totals
    ]

    import json

    click.echo(json.dumps({"rows": rows, "totals": totals}))
