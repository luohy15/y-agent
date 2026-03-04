import datetime
import json

import click

from .helpers import extract_tree, sum_tree, convert_balance, convert_tree, filter_by_date, period_boundaries


@click.command("income-statement")
@click.pass_context
def income_statement(ctx):
    """Print income statement as JSON for a beancount file."""
    from beancount.core import realization

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]
    price_map, convert = obj["price_map"], obj["convert"]
    start_date, end_date = obj["start_date"], obj["end_date"]

    if not obj["history"]:
        filtered = filter_by_date(entries, start_date, end_date)
        real = realization.realize(filtered)
        result = {
            "income": extract_tree(realization, real, options["name_income"]),
            "expenses": extract_tree(realization, real, options["name_expenses"]),
        }
        if convert:
            date = end_date - datetime.timedelta(days=1) if end_date else None
            result = {k: convert_tree(v, price_map, convert, date) for k, v in result.items()}
        click.echo(json.dumps(result))
        return

    periods = period_boundaries(start_date, end_date, obj["granularity"])

    result = []
    for p_start, p_end, label in periods:
        filtered = filter_by_date(entries, p_start, p_end)
        real = realization.realize(filtered)
        row = {
            "period": label,
            "income": sum_tree(realization, real, options["name_income"]),
            "expenses": sum_tree(realization, real, options["name_expenses"]),
        }
        if convert:
            date = p_end - datetime.timedelta(days=1)
            for key in ("income", "expenses"):
                row[key] = convert_balance(row[key], price_map, convert, date)
        result.append(row)

    click.echo(json.dumps(result))
