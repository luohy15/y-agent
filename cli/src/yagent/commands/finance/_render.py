"""Friendly table rendering for the DB-backed y finance commands.

Each render_* helper takes the same envelope dict the --json path would emit and
prints a tabulate(tablefmt="simple") table (matching the rest of the y CLI).
"""

import click
from tabulate import tabulate


# --- formatting primitives -------------------------------------------------

def fmt_money(amount, currency: str | None = None) -> str:
    """Format a money amount with thousands separators and 2 decimals.

    None/empty renders as '-'. With a currency, prefixes 'CUR '.
    """
    if amount is None or amount == "":
        return "-"
    s = f"{amount:,.2f}"
    return f"{currency} {s}" if currency else s


def fmt_qty(n) -> str:
    """Format a quantity: thousands separators, up to 4 decimals, trailing zeros trimmed."""
    if n is None or n == "":
        return "-"
    s = f"{n:,.4f}".rstrip("0").rstrip(".")
    return s or "0"


def fmt_pct(frac) -> str:
    """Format a fraction (0.7 -> '70.00%'). None/empty renders as '-'."""
    if frac is None or frac == "":
        return "-"
    return f"{frac * 100:.2f}%"


def fmt_balance(balance: dict | None, sign: int = 1) -> str:
    """Format a {currency: amount} balance dict, joined with ' / '. Empty -> '-'."""
    if not balance:
        return "-"
    parts = [fmt_money(amt * sign, cur) for cur, amt in balance.items()]
    return " / ".join(parts)


def _sum_balances(node: dict) -> dict:
    """Recursively sum a balance-sheet/income tree node's descendant leaf balances."""
    total: dict = {}
    for cur, amt in (node.get("balance") or {}).items():
        total[cur] = total.get(cur, 0) + amt
    for child in node.get("children") or []:
        for cur, amt in _sum_balances(child).items():
            total[cur] = total.get(cur, 0) + amt
    return total


def flatten_account_tree(node: dict, depth: int = 0, sign: int = 1) -> list[tuple[str, str]]:
    """Flatten an account tree into [(indented_account, balance_str)] with subtotals."""
    rows: list[tuple[str, str]] = []
    name = node.get("account", "")
    indent = "  " * depth
    rows.append((indent + name, fmt_balance(_sum_balances(node), sign=sign)))
    for child in node.get("children") or []:
        rows.extend(flatten_account_tree(child, depth + 1, sign=sign))
    return rows


def _combine(*balances: dict, sign: int = 1) -> dict:
    """Sum several {currency: amount} dicts into one."""
    out: dict = {}
    for bal in balances:
        for cur, amt in (bal or {}).items():
            out[cur] = out.get(cur, 0) + amt * sign
    return out


# --- per-command renderers -------------------------------------------------

def render_holdings(envelope: dict) -> None:
    rows = envelope.get("data") or []
    summary = envelope.get("summary") or {}
    base_cur = summary.get("base_currency") or "USD"
    table = []
    for p in rows:
        cur = p.get("cost_currency")
        unreal = p.get("unrealized_profit_pct")
        table.append([
            p.get("symbol"),
            fmt_qty(p.get("quantity")),
            fmt_money(p.get("average_cost"), cur),
            fmt_money(p.get("price"), cur),
            fmt_money(p.get("market_value"), cur),
            fmt_money(p.get("market_value_base"), base_cur),
            fmt_pct(p.get("allocation_pct")),
            fmt_pct(unreal / 100) if unreal is not None else "-",
            "yes" if p.get("is_cash") else "",
        ])
    headers = ["Symbol", "Qty", "Avg Cost", "Price", "Market Value", f"MV ({base_cur})", "Alloc%", "Unreal%", "Cash"]
    click.echo(tabulate(table, headers=headers, tablefmt="simple"))
    click.echo()
    click.echo(
        f"Total: {fmt_money(summary.get('total_base'), base_cur)}    "
        f"Risky: {fmt_money(summary.get('risky_base'), base_cur)}    "
        f"Risky%: {fmt_pct(summary.get('risky_pct'))}"
    )


def render_prices(envelope: dict) -> None:
    rows = envelope.get("data") or []
    table = [[r.get("symbol"), r.get("price_date"), fmt_money(r.get("price")), r.get("currency")] for r in rows]
    click.echo(tabulate(table, headers=["Symbol", "Date", "Price", "Currency"], tablefmt="simple"))


def render_transactions(envelope: dict) -> None:
    rows = envelope.get("data") or []
    table = []
    for g in rows:
        qty = " / ".join(f"{fmt_qty(q.get('amount'))} {q.get('currency')}" for q in (g.get("quantity") or []))
        amt = " / ".join(fmt_money(a.get("amount"), a.get("currency")) for a in (g.get("amount") or []))
        table.append([
            g.get("transaction_date"),
            g.get("symbol"),
            g.get("side"),
            qty or "-",
            amt or "-",
            g.get("payee") or "-",
            g.get("narration") or "-",
        ])
    headers = ["Date", "Symbol", "Side", "Quantity", "Amount", "Payee", "Narration"]
    click.echo(tabulate(table, headers=headers, tablefmt="simple"))


def render_fire_progress(envelope: dict) -> None:
    d = envelope.get("data") or {}
    rows = [
        ("Net worth", fmt_money(d.get("net_worth_usd"), "USD")),
        ("Target", fmt_money(d.get("target_usd"), "USD")),
        ("Gap", fmt_money(d.get("gap_usd"), "USD")),
        ("Progress", f"{d['progress_pct']:.2f}%" if d.get("progress_pct") is not None else "-"),
        ("YTD income", fmt_money(d.get("ytd_income_usd"), "USD")),
        ("YTD expense", fmt_money(d.get("ytd_expense_usd"), "USD")),
        ("YTD savings rate", fmt_pct(d.get("ytd_savings_rate"))),
        ("Monthly expense", fmt_money(d.get("monthly_expense_usd"), "USD")),
        ("Withdrawal rate", fmt_pct(d.get("withdrawal_rate"))),
        ("Months to target", fmt_qty(d.get("projected_months_to_target"))),
        ("Projected date", d.get("projected_date") or "-"),
        ("Config source", d.get("config_source") or "-"),
    ]
    click.echo(tabulate(rows, headers=["Metric", "Value"], tablefmt="simple"))


def render_balance_sheet(envelope: dict, history: bool, breakdown: str | None) -> None:
    data = envelope.get("data")
    if breakdown:
        # Best-effort per-period position table; --json is the precise escape hatch.
        table = []
        for period in (data or []):
            for symbol, bal in (period.get("positions") or {}).items():
                table.append([period.get("period"), symbol, fmt_balance(bal)])
        click.echo(tabulate(table, headers=["Period", "Symbol", "Value"], tablefmt="simple"))
        return
    if history:
        table = []
        for row in (data or []):
            net = _combine(row.get("assets"), row.get("liabilities"))
            table.append([row.get("period"), fmt_balance(row.get("assets")), fmt_balance(row.get("liabilities")), fmt_balance(net)])
        click.echo(tabulate(table, headers=["Period", "Assets", "Liabilities", "Net"], tablefmt="simple"))
        return

    assets = data.get("assets") or {}
    liabilities = data.get("liabilities") or {}
    table = flatten_account_tree(assets)
    table.append(("Total Assets", fmt_balance(_sum_balances(assets))))
    table.append(("", ""))
    table.extend(flatten_account_tree(liabilities))
    table.append(("Total Liabilities", fmt_balance(_sum_balances(liabilities))))
    table.append(("", ""))
    net = _combine(_sum_balances(assets), _sum_balances(liabilities))
    table.append(("Net Worth", fmt_balance(net)))
    click.echo(tabulate(table, headers=["Account", "Balance"], tablefmt="simple"))


def render_investment_returns(envelope: dict, history: bool) -> None:
    data = envelope.get("data")
    if history:
        table = []
        for row in (data or []):
            table.append([
                row.get("period"),
                fmt_money(row.get("realized")),
                fmt_money(row.get("unrealized")),
                fmt_money(row.get("total_return_cumulative")),
            ])
        click.echo(tabulate(table, headers=["Period", "Realized", "Unrealized", "Total (cumulative)"], tablefmt="simple"))
        return

    d = data or {}
    cur = d.get("convert") or "USD"
    summary = [
        ("Realized", fmt_money(d.get("realized"), cur)),
        ("  Dividends", fmt_money(d.get("dividends"), cur)),
        ("  Interest", fmt_money(d.get("interest"), cur)),
        ("Unrealized", fmt_money(d.get("unrealized"), cur)),
        ("Unrealized %", fmt_pct(d.get("unrealized_pct"))),
        ("Total return", fmt_money(d.get("total_return"), cur)),
    ]
    click.echo(tabulate(summary, headers=["Metric", "Value"], tablefmt="simple"))
    positions = d.get("positions") or []
    if positions:
        click.echo()
        table = [[
            p.get("symbol"),
            fmt_money(p.get("market_value_base"), cur),
            fmt_money(p.get("book_value_base"), cur),
            fmt_money(p.get("unrealized"), cur),
            fmt_pct(p.get("unrealized_pct")),
        ] for p in positions]
        headers = ["Symbol", f"MV ({cur})", f"Book ({cur})", "Unrealized", "Unreal%"]
        click.echo(tabulate(table, headers=headers, tablefmt="simple"))


def render_income_statement(envelope: dict, history: bool, breakdown: str) -> None:
    # Display convention: income shown positive (raw credit is negative), expenses positive.
    data = envelope.get("data")
    if breakdown == "categories":
        table = []
        for period in (data or []):
            for account, bal in (period.get("income_categories") or {}).items():
                table.append([period.get("period"), "Income", account, fmt_balance(bal, sign=-1)])
            for account, bal in (period.get("expense_categories") or {}).items():
                table.append([period.get("period"), "Expense", account, fmt_balance(bal)])
        click.echo(tabulate(table, headers=["Period", "Type", "Category", "Amount"], tablefmt="simple"))
        return
    if history:
        table = []
        for row in (data or []):
            net = _combine(row.get("income"), sign=-1)
            for cur, amt in _combine(row.get("expenses")).items():
                net[cur] = net.get(cur, 0) - amt
            table.append([row.get("period"), fmt_balance(row.get("income"), sign=-1), fmt_balance(row.get("expenses")), fmt_balance(net)])
        click.echo(tabulate(table, headers=["Period", "Income", "Expenses", "Net"], tablefmt="simple"))
        return

    income = data.get("income") or {}
    expenses = data.get("expenses") or {}
    table = flatten_account_tree(income, sign=-1)
    income_total = _combine(_sum_balances(income), sign=-1)
    table.append(("Total Income", fmt_balance(_sum_balances(income), sign=-1)))
    table.append(("", ""))
    table.extend(flatten_account_tree(expenses))
    expense_total = _sum_balances(expenses)
    table.append(("Total Expenses", fmt_balance(expense_total)))
    table.append(("", ""))
    net = dict(income_total)
    for cur, amt in expense_total.items():
        net[cur] = net.get(cur, 0) - amt
    table.append(("Net Income", fmt_balance(net)))
    click.echo(tabulate(table, headers=["Account", "Amount"], tablefmt="simple"))
