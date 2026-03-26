import datetime
import glob
import json
import os
import re

import click

from .helpers import save_and_echo


@click.command("price-history")
@click.pass_context
def price_history(ctx):
    """Output stock price history JSON for current holdings."""
    from beancount.core import realization

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]

    # Get current holdings from Assets:Stock accounts
    real = realization.realize(entries)
    stock_acc = realization.get(real, "Assets:Stock")
    held_symbols = set()
    if stock_acc is not None:
        def _walk(acc):
            for pos in acc.balance:
                if pos.units.number != 0:
                    held_symbols.add(pos.units.currency)
            for child in acc.values():
                _walk(child)
        _walk(stock_acc)

    if not held_symbols:
        save_and_echo("price-history", {})
        return

    # Parse price files
    home = os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))
    price_dir = os.path.join(home, "finance", "beancount", "price", "stock")
    pattern = os.path.join(price_dir, "*.bean")
    line_re = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+price\s+(\w+)\s+([\d.]+)\s+\w+")

    cutoff = datetime.date.today() - datetime.timedelta(days=730)  # 2 years
    result = {}

    for filepath in glob.glob(pattern):
        for line in open(filepath):
            m = line_re.match(line.strip())
            if not m:
                continue
            date_str, symbol, price_str = m.group(1), m.group(2), m.group(3)
            if symbol not in held_symbols:
                continue
            date = datetime.date.fromisoformat(date_str)
            if date < cutoff:
                continue
            if symbol not in result:
                result[symbol] = []
            result[symbol].append({"date": date_str, "price": float(price_str)})

    # Sort each symbol's data by date ascending
    for symbol in result:
        result[symbol].sort(key=lambda x: x["date"])

    save_and_echo("price-history", result)
