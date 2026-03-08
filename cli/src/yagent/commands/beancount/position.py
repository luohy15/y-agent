import datetime

import click

from .helpers import sum_tree, convert_balance, filter_by_date, extract_tree, save_and_echo

LIVING_RESERVE_MONTHS = 6


@click.command("position")
@click.pass_context
def position(ctx):
    """Calculate maximum investable amount from beancount data."""
    from beancount.core import realization, prices

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]
    price_map, convert = obj["price_map"], obj["convert"]

    # Always need price_map for USD conversion
    target = convert or "USD"
    if price_map is None:
        price_map = prices.build_price_map(entries)

    today = datetime.date.today()

    # --- Net worth (all time, up to today) ---
    filtered_all = [e for e in entries if not hasattr(e, "date") or e.date <= today]
    real_all = realization.realize(filtered_all)
    assets_bal = sum_tree(realization, real_all, options["name_assets"])
    liabilities_bal = sum_tree(realization, real_all, options["name_liabilities"])
    assets_usd = convert_balance(assets_bal, price_map, target)
    liabilities_usd = convert_balance(liabilities_bal, price_map, target)
    net_worth = assets_usd[target] + liabilities_usd.get(target, 0)

    # --- Stock holdings ---
    stock_tree = extract_tree(realization, real_all, "Assets:Stock")
    from .helpers import convert_tree
    stock_tree_usd = convert_tree(stock_tree, price_map, target)
    stock_holdings = _tree_total_flat(stock_tree_usd)

    # --- Trailing 12 months ---
    twelve_months_ago = today.replace(year=today.year - 1)
    filtered_12m = filter_by_date(entries, twelve_months_ago, today)
    real_12m = realization.realize(filtered_12m)

    # Labor income (past 12 months) — Income is negative in beancount, negate it
    salary_bal = sum_tree(realization, real_12m, "Income:Employment")
    salary_usd = convert_balance(salary_bal, price_map, target) if salary_bal else {target: 0}
    labor_income = -salary_usd.get(target, 0)

    # Monthly expense (past 12 months avg)
    expenses_bal = sum_tree(realization, real_12m, options["name_expenses"])
    expenses_usd = convert_balance(expenses_bal, price_map, target) if expenses_bal else {target: 0}
    total_expenses = expenses_usd.get(target, 0)
    monthly_expense = total_expenses / 12

    # --- Calculations ---
    living_reserve = monthly_expense * LIVING_RESERVE_MONTHS
    liability_allowance = labor_income / 12 * 10 # 10 months of labor income as liability allowance
    max_investable = net_worth + liability_allowance - living_reserve
    position_ratio = stock_holdings / max_investable if max_investable else 0

    result = {
        "net_worth": round(net_worth, 2),
        "stock_holdings": round(stock_holdings, 2),
        "labor_income_12m": round(labor_income, 2),
        "monthly_expense": round(monthly_expense, 2),
        "living_reserve": round(living_reserve, 2),
        "liability_allowance": round(liability_allowance, 2),
        "max_investable": round(max_investable, 2),
        "position_ratio": round(position_ratio, 4),
        "currency": target,
    }
    save_and_echo("position", result)


def _tree_total_flat(node):
    """Sum all balances in a converted tree."""
    total = sum(node["balance"].values())
    for child in node["children"]:
        total += _tree_total_flat(child)
    return total
