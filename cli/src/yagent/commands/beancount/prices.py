import json

import click


@click.command("prices")
@click.option("--symbol", default="", help="Filter prices by commodity symbol")
@click.pass_context
def prices(ctx, symbol: str):
    """Print beancount price directives as normalized rows."""
    from beancount.core.data import Price

    rows = []
    for entry in ctx.obj["entries"]:
        if not isinstance(entry, Price):
            continue
        if symbol and entry.currency != symbol:
            continue
        rows.append({
            "symbol": entry.currency,
            "price_date": entry.date.isoformat(),
            "price": float(entry.amount.number),
            "currency": entry.amount.currency,
        })
    rows.sort(key=lambda row: (row["symbol"], row["price_date"]))
    click.echo(json.dumps(rows))
