import os

import click

from .balance_sheet import balance_sheet
from .holdings import holdings
from .income_statement import income_statement
from .invest_plan import invest_plan
from .position import position

from .price_history import price_history
from .target_holdings import target_holdings
from .target_position import target_position
from .update_market_data import update_market_data


@click.group("beancount")
@click.option("--time", default="", help="Time filter (e.g. month, 2024, 2024-q2, day-1 - day)")
@click.option("--history", is_flag=True, help="Output time-series metrics instead of detail")
@click.option("--granularity", type=click.Choice(["monthly", "yearly"]), default="monthly")
@click.option("--convert", default="", help="Convert all amounts to this currency (e.g. USD)")
@click.pass_context
def beancount_group(ctx, time: str, history: bool, granularity: str, convert: str):
    """Beancount financial reporting commands."""
    ctx.ensure_object(dict)

    # Skip beancount loading for commands that don't need it
    if ctx.invoked_subcommand in ("update-market-data", "target-position"):
        return

    from beancount import loader
    from beancount.core import prices
    from fava.util.date import parse_date

    home = os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))
    if not home:
        raise click.ClickException("Y_AGENT_HOME environment variable is not set")
    path = os.path.join(home, "finance", "beancount", "main.bean")

    if time:
        start_date, end_date = parse_date(time)
    else:
        start_date, end_date = None, None

    entries, _errors, options = loader.load_file(path)
    price_map = prices.build_price_map(entries) if convert else None

    ctx.obj["entries"] = entries
    ctx.obj["options"] = options
    ctx.obj["price_map"] = price_map
    ctx.obj["start_date"] = start_date
    ctx.obj["end_date"] = end_date
    ctx.obj["history"] = history
    ctx.obj["granularity"] = granularity
    ctx.obj["convert"] = convert


beancount_group.add_command(income_statement)
beancount_group.add_command(update_market_data)
beancount_group.add_command(balance_sheet)
beancount_group.add_command(holdings)
beancount_group.add_command(invest_plan)
beancount_group.add_command(position)
beancount_group.add_command(price_history)
beancount_group.add_command(target_holdings)
beancount_group.add_command(target_position)
