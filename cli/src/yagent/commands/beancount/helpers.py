import datetime


def period_boundaries(start_date, end_date, granularity):
    periods = []
    if granularity == "monthly":
        cur = start_date.replace(day=1)
        while cur < end_date:
            next_p = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            periods.append((cur, min(next_p, end_date), cur.strftime("%Y-%m")))
            cur = next_p
    else:  # yearly
        cur = start_date.replace(month=1, day=1)
        while cur < end_date:
            next_p = cur.replace(year=cur.year + 1)
            periods.append((cur, min(next_p, end_date), str(cur.year)))
            cur = next_p
    return periods


def filter_by_date(entries, start_date, end_date):
    filtered = []
    for e in entries:
        if not hasattr(e, "date"):
            filtered.append(e)
            continue
        if start_date and e.date < start_date:
            continue
        if end_date and e.date >= end_date:
            continue
        filtered.append(e)
    return filtered


def walk_tree(real_account):
    node = {
        "account": real_account.account,
        "balance": {},
        "children": [],
    }
    for pos in real_account.balance:
        cur = pos.units.currency
        amt = float(pos.units.number)
        node["balance"][cur] = node["balance"].get(cur, 0) + amt
    for child in sorted(real_account.values(), key=lambda r: r.account):
        child_node = walk_tree(child)
        if child_node["children"] or child_node["balance"]:
            node["children"].append(child_node)
    return node


def extract_tree(realization, root, prefix):
    acc = realization.get(root, prefix)
    if acc is None:
        return {"account": prefix, "balance": {}, "children": []}
    return walk_tree(acc)


def sum_tree(realization, root, prefix):
    acc = realization.get(root, prefix)
    if acc is None:
        return {}
    totals = {}
    def walk(node):
        for pos in node.balance:
            cur = pos.units.currency
            amt = float(pos.units.number)
            totals[cur] = totals.get(cur, 0) + amt
        for child in node.values():
            walk(child)
    walk(acc)
    return totals


def convert_balance(balance, price_map, target_currency, date=None):
    """Convert a {currency: amount} dict to a single {target_currency: amount} dict."""
    from beancount.core.prices import get_price

    total = 0.0
    for cur, amt in balance.items():
        if cur == target_currency:
            total += amt
        else:
            result = get_price(price_map, (cur, target_currency), date)
            if result is None:
                raise click.UsageError(f"No price found for {cur} -> {target_currency}")
            _, price = result
            total += amt * float(price)
    return {target_currency: round(total, 2)}


def _tree_total(node):
    """Sum all balances in a tree (node + descendants)."""
    total = sum(node["balance"].values())
    for child in node["children"]:
        total += _tree_total(child)
    return total


def convert_tree(node, price_map, target_currency, date=None):
    """Recursively convert all balances in an account tree to target currency."""
    children = [convert_tree(child, price_map, target_currency, date) for child in node["children"]]
    children.sort(key=lambda c: abs(_tree_total(c)), reverse=True)
    converted = {
        "account": node["account"],
        "balance": convert_balance(node["balance"], price_map, target_currency, date) if node["balance"] else {},
        "children": children,
    }
    return converted


# re-export click for convert_balance error
import click  # noqa: E402
