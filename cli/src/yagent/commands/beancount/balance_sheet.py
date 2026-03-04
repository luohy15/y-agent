import datetime
import json

import click

from .helpers import extract_tree, sum_tree, convert_balance, convert_tree, period_boundaries


@click.command("balance-sheet")
@click.pass_context
def balance_sheet(ctx):
    """Print balance sheet as JSON for a beancount file."""
    from beancount.core import realization

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]
    price_map, convert = obj["price_map"], obj["convert"]
    start_date, end_date = obj["start_date"], obj["end_date"]

    if not obj["history"]:
        filtered = [e for e in entries if not hasattr(e, "date") or (
            (start_date is None or e.date >= start_date) and
            (end_date is None or e.date < end_date)
        )]
        real = realization.realize(filtered)
        result = {
            "assets": extract_tree(realization, real, options["name_assets"]),
            "liabilities": extract_tree(realization, real, options["name_liabilities"]),
        }
        if convert:
            date = end_date - datetime.timedelta(days=1) if end_date else None
            result = {k: convert_tree(v, price_map, convert, date) for k, v in result.items()}
        click.echo(json.dumps(result))
        return

    periods = period_boundaries(start_date, end_date, obj["granularity"])

    result = []
    for _p_start, p_end, label in periods:
        filtered = [e for e in entries if not hasattr(e, "date") or e.date < p_end]
        real = realization.realize(filtered)
        row = {
            "period": label,
            "assets": sum_tree(realization, real, options["name_assets"]),
            "liabilities": sum_tree(realization, real, options["name_liabilities"]),
        }
        if convert:
            date = p_end - datetime.timedelta(days=1)
            for key in ("assets", "liabilities"):
                row[key] = convert_balance(row[key], price_map, convert, date)
        result.append(row)

    click.echo(json.dumps(result))
