import datetime
import json
import os

import click

from .helpers import convert_balance, filter_by_date, sum_tree


def _load_fire_config():
    home = os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))
    path = os.path.join(home, "finance", "fire_target.json")
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
        return cfg, "file"
    monthly_expense = 5000.0
    withdrawal_rate = 0.04
    return {
        "target_usd": round(monthly_expense * 12 / withdrawal_rate, 2),
        "monthly_expense_usd": monthly_expense,
        "withdrawal_rate": withdrawal_rate,
        "currency": "USD",
    }, "default"


@click.command("fire-progress")
@click.pass_context
def fire_progress(ctx):
    """Print FIRE progress as JSON."""
    from beancount.core import prices, realization

    obj = ctx.obj
    entries, options = obj["entries"], obj["options"]
    convert = obj["convert"] or "USD"
    price_map = obj["price_map"] or prices.build_price_map(entries)

    cfg, source = _load_fire_config()
    monthly_expense_usd = float(cfg.get("monthly_expense_usd", 0) or 0)
    withdrawal_rate = float(cfg.get("withdrawal_rate", 0.04) or 0.04)
    target_usd = float(
        cfg.get("target_usd")
        or (monthly_expense_usd * 12 / withdrawal_rate if withdrawal_rate else 0)
    )

    today = datetime.date.today()
    today_end = today + datetime.timedelta(days=1)

    # Net worth as of today
    nw_filtered = [e for e in entries if not hasattr(e, "date") or e.date < today_end]
    nw_real = realization.realize(nw_filtered)
    assets = sum_tree(realization, nw_real, options["name_assets"])
    liabilities = sum_tree(realization, nw_real, options["name_liabilities"])
    assets_conv = convert_balance(assets, price_map, convert, today) if assets else {convert: 0.0}
    liabilities_conv = convert_balance(liabilities, price_map, convert, today) if liabilities else {convert: 0.0}
    net_worth_usd = round(assets_conv.get(convert, 0) + liabilities_conv.get(convert, 0), 2)

    # YTD income/expense
    year_start = datetime.date(today.year, 1, 1)
    ytd_filtered = filter_by_date(entries, year_start, today_end)
    ytd_real = realization.realize(ytd_filtered)
    income = sum_tree(realization, ytd_real, options["name_income"])
    expenses = sum_tree(realization, ytd_real, options["name_expenses"])
    income_conv = convert_balance(income, price_map, convert, today) if income else {convert: 0.0}
    expense_conv = convert_balance(expenses, price_map, convert, today) if expenses else {convert: 0.0}
    ytd_income_usd = round(abs(income_conv.get(convert, 0)), 2)
    ytd_expense_usd = round(expense_conv.get(convert, 0), 2)

    ytd_savings_rate = (
        round((ytd_income_usd - ytd_expense_usd) / ytd_income_usd, 4)
        if ytd_income_usd > 0
        else None
    )

    gap_usd = round(target_usd - net_worth_usd, 2)
    progress_pct = round(net_worth_usd / target_usd * 100, 2) if target_usd > 0 else None

    days_elapsed = max((today - year_start).days + 1, 1)
    months_elapsed = days_elapsed / 30.44
    monthly_savings = (
        (ytd_income_usd - ytd_expense_usd) / months_elapsed if months_elapsed > 0 else 0
    )

    if gap_usd <= 0:
        projected_months = 0
        projected_date = today.isoformat()
    elif monthly_savings > 0:
        m = gap_usd / monthly_savings
        projected_months = round(m, 1)
        projected_date = (today + datetime.timedelta(days=m * 30.44)).isoformat()
    else:
        projected_months = None
        projected_date = None

    result = {
        "net_worth_usd": net_worth_usd,
        "target_usd": round(target_usd, 2),
        "gap_usd": gap_usd,
        "progress_pct": progress_pct,
        "ytd_income_usd": ytd_income_usd,
        "ytd_expense_usd": ytd_expense_usd,
        "ytd_savings_rate": ytd_savings_rate,
        "monthly_expense_usd": monthly_expense_usd,
        "withdrawal_rate": withdrawal_rate,
        "projected_months_to_target": projected_months,
        "projected_date": projected_date,
        "config_source": source,
    }
    click.echo(json.dumps(result))
