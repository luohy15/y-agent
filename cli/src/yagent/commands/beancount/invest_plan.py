"""Generate beancount transaction guide by comparing current holdings to target."""

import csv
import datetime
import json
import os
from pathlib import Path

import click


def _finance_dir():
    return Path(os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))) / "finance"


def _load_holdings_csv(path: Path) -> dict[str, dict]:
    """Load holdings.csv and return {symbol: {units, market_value}} in cost currency."""
    result = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("units") or row["units"].startswith("---"):
                break
            parts = row["units"].split()
            if len(parts) != 2:
                continue
            units_num, symbol = float(parts[0]), parts[1]

            mv_val = 0.0
            mv_currency = ""
            if row.get("market_value"):
                mp = row["market_value"].split()
                if len(mp) == 2:
                    mv_val = float(mp[0])
                    mv_currency = mp[1]

            result[symbol] = {
                "units": units_num,
                "market_value": mv_val,
                "currency": mv_currency,
            }
    return result


def _load_target_holdings(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _get_price_from_beancount(price_map, symbol, currency):
    """Get latest price for a symbol from beancount price map."""
    from beancount.core.prices import get_latest_price

    _date, price = get_latest_price(price_map, (symbol, currency))
    if price is not None:
        return float(price)
    return None


@click.command("invest-plan")
@click.pass_context
def invest_plan(ctx):
    """Generate beancount buy/sell transaction guide from holdings vs target."""
    from beancount.core import prices

    obj = ctx.obj
    entries = obj["entries"]
    price_map = obj.get("price_map")
    if price_map is None:
        price_map = prices.build_price_map(entries)

    finance_dir = _finance_dir()

    holdings_path = finance_dir / "holdings.csv"
    if not holdings_path.exists():
        raise click.ClickException(f"Holdings not found: {holdings_path}. Run 'beancount holdings' first.")

    target_path = finance_dir / "target_holdings.json"
    if not target_path.exists():
        raise click.ClickException(f"Target holdings not found: {target_path}. Run 'beancount target-holdings' first.")

    # Load account names from env
    from dotenv import load_dotenv
    home = Path(os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent")))
    load_dotenv(home / ".env")
    stock_account = os.environ.get("Y_AGENT_STOCK_ACCOUNT", "Assets:Stock")
    cash_account = os.environ.get("Y_AGENT_CASH_ACCOUNT", "Assets:Cash")
    transfer_account = os.environ.get("Y_AGENT_TRANSFER_ACCOUNT", "Assets:Bank:Checking")

    # Get current cash balance in the cash account
    from beancount.core import realization
    from .helpers import sum_tree, convert_balance

    filtered_all = [e for e in entries if not hasattr(e, "date") or e.date <= datetime.date.today()]
    real_all = realization.realize(filtered_all)
    cash_bal = sum_tree(realization, real_all, cash_account)
    cash_usd = convert_balance(cash_bal, price_map, obj.get("convert") or "USD") if cash_bal else {(obj.get("convert") or "USD"): 0}

    current = _load_holdings_csv(holdings_path)
    target_data = _load_target_holdings(target_path)
    currency = target_data["currency"]
    today = datetime.date.today().isoformat()
    current_cash = cash_usd.get(currency, 0)

    # First pass: compute net cash needed
    net_cash_needed = 0.0
    for h in target_data["holdings"]:
        symbol = h["symbol"]
        target_val = h["target"]
        cur = current.get(symbol, {"units": 0, "market_value": 0, "currency": currency})
        delta_val = target_val - cur["market_value"]
        price = _get_price_from_beancount(price_map, symbol, currency)
        if price is None or price == 0:
            continue
        delta_units = round(delta_val / price)
        net_cash_needed += delta_units * price  # positive = need cash, negative = get cash

    deposit_needed = net_cash_needed - current_cash

    lines = [
        f"; Investment plan generated {today}",
        f"; Target total: {target_data['target_total']:.2f} {currency}",
        f"; Cash balance: {current_cash:.2f} {currency}",
        f"; Net cash needed: {net_cash_needed:.2f} {currency}",
        "",
    ]

    if abs(deposit_needed) >= 1:
        abs_deposit = abs(deposit_needed)
        if deposit_needed > 0:
            lines.append(f'{today} * "Deposit"')
            lines.append(f"  {cash_account}  {abs_deposit:.2f} {currency}")
            lines.append(f"  {transfer_account}  -{abs_deposit:.2f} {currency}")
        else:
            lines.append(f'{today} * "Withdraw"')
            lines.append(f"  {transfer_account}  {abs_deposit:.2f} {currency}")
            lines.append(f"  {cash_account}  -{abs_deposit:.2f} {currency}")
        lines.append("")

    for h in target_data["holdings"]:
        symbol = h["symbol"]
        target_val = h["target"]
        cur = current.get(symbol, {"units": 0, "market_value": 0, "currency": currency})

        current_mv = cur["market_value"]
        delta_val = target_val - current_mv
        price = _get_price_from_beancount(price_map, symbol, currency)

        if price is None or price == 0:
            lines.append(f"; {symbol}: no price available, skipping")
            lines.append("")
            continue

        delta_units = round(delta_val / price)

        if delta_units == 0:
            lines.append(f"; {symbol}: on target (delta {delta_val:+.2f} {currency})")
            lines.append("")
            continue

        action = "Buy" if delta_units > 0 else "Sell"
        abs_units = abs(delta_units)
        abs_val = abs_units * price

        lines.append(f"; {symbol}: {action} {abs_units} shares (~{abs_val:.2f} {currency})")
        lines.append(f"; current: {int(cur['units'])} shares @ {price:.2f} = {current_mv:.2f} {currency}")
        lines.append(f"; target: {target_val:.2f} {currency} (weight {h['weight']:.1%})")
        lines.append(f'{today} * "{action} {symbol}"')

        if delta_units > 0:
            lines.append(f"  {stock_account}  {abs_units} {symbol} {{{price:.2f} {currency}}}")
            lines.append(f"  {cash_account}  -{abs_val:.2f} {currency}")
        else:
            lines.append(f"  {stock_account}  -{abs_units} {symbol} {{{price:.2f} {currency}}}")
            lines.append(f"  {cash_account}  {abs_val:.2f} {currency}")

        lines.append("")

    content = "\n".join(lines)

    # Write to coming directory
    output_dir = finance_dir / "beancount" / "coming" / "invest" / "stock"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{today}.bean"
    output_file.write_text(content)

    click.echo(content)
    click.echo(f"\nSaved to {output_file}")
