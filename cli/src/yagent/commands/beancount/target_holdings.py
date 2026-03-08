"""Compute target holdings and buy/sell deltas from allocation config."""

import json
import os

import click


@click.command("target-holdings")
@click.pass_context
def target_holdings(ctx):
    """Compute target holdings from allocation weights and current position."""
    import datetime
    from beancount.core import realization, prices

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]
    price_map = obj.get("price_map")
    convert = obj.get("convert") or "USD"

    if price_map is None:
        price_map = prices.build_price_map(entries)

    # Load target_ratio from saved target_position result
    home = os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))
    position_path = os.path.join(home, "finance", "target_position.json")
    if not os.path.exists(position_path):
        raise click.ClickException(f"Target position not found: {position_path}. Run 'beancount target-position' first.")
    with open(position_path) as f:
        position_data = json.load(f)
    target_ratio = position_data["target_ratio"]

    # Load allocation config
    config_path = os.path.join(home, "finance", "target_allocation.json")
    if not os.path.exists(config_path):
        raise click.ClickException(f"Allocation config not found: {config_path}")
    with open(config_path) as f:
        allocation = json.load(f)

    # Validate weights sum to ~1.0
    total_weight = sum(allocation.values())
    if abs(total_weight - 1.0) > 0.01:
        raise click.ClickException(f"Allocation weights sum to {total_weight}, expected ~1.0")

    # Compute max_investable (same logic as current_position)
    from .position import LIVING_RESERVE_MONTHS
    from .helpers import sum_tree, convert_balance, filter_by_date

    today = datetime.date.today()
    filtered_all = [e for e in entries if not hasattr(e, "date") or e.date <= today]
    real_all = realization.realize(filtered_all)

    assets_bal = sum_tree(realization, real_all, options["name_assets"])
    liabilities_bal = sum_tree(realization, real_all, options["name_liabilities"])
    assets_usd = convert_balance(assets_bal, price_map, convert)
    liabilities_usd = convert_balance(liabilities_bal, price_map, convert)
    net_worth = assets_usd[convert] + liabilities_usd.get(convert, 0)

    twelve_months_ago = today.replace(year=today.year - 1)
    filtered_12m = filter_by_date(entries, twelve_months_ago, today)
    real_12m = realization.realize(filtered_12m)

    salary_bal = sum_tree(realization, real_12m, "Income:Employment")
    salary_usd = convert_balance(salary_bal, price_map, convert) if salary_bal else {convert: 0}
    labor_income = -salary_usd.get(convert, 0)

    expenses_bal = sum_tree(realization, real_12m, options["name_expenses"])
    expenses_usd = convert_balance(expenses_bal, price_map, convert) if expenses_bal else {convert: 0}
    monthly_expense = expenses_usd.get(convert, 0) / 12

    living_reserve = monthly_expense * LIVING_RESERVE_MONTHS
    liability_allowance = labor_income / 12 * 10
    max_investable = net_worth + liability_allowance - living_reserve

    target_total = max_investable * target_ratio

    # Compute target per symbol
    result = []
    for symbol, weight in sorted(allocation.items(), key=lambda x: -x[1]):
        target_val = round(target_total * weight, 2)
        result.append({
            "symbol": symbol,
            "weight": weight,
            "target": target_val,
        })

    output = {
        "currency": convert,
        "max_investable": round(max_investable, 2),
        "target_ratio": target_ratio,
        "target_total": round(target_total, 2),
        "holdings": result,
    }
    from .helpers import save_and_echo
    save_and_echo("target_holdings", output)
