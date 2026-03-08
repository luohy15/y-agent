"""Fetch and update market data (forex rates and stock prices) from Alpha Vantage."""

import csv
import os
import re
import time
from io import StringIO
from pathlib import Path

import click
import httpx

from .alphavantage import get_api_key, query


START_DATE = "2019-01-01"
# Alpha Vantage premium tier: 150 calls/minute
API_CALL_DELAY = 60 / 150


def _finance_dir():
    return Path(os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))) / "finance"


def parse_symbols_from_index(finance_dir: Path):
    """Parse symbols from index.bean files.

    Returns:
        (forex_dict, stocks_dict) where each dict maps symbol to (bean_file_path, comment)
    """
    forex = {}
    stocks = {}

    forex_index = finance_dir / "beancount/price/forex/index.bean"
    if forex_index.exists():
        for line in forex_index.read_text().splitlines():
            match = re.match(r'include "(\w+)\.bean"', line)
            if match:
                symbol = match.group(1).upper()
                forex[symbol] = (
                    finance_dir / f"beancount/price/forex/{symbol.lower()}.bean",
                    f"{symbol}/USD monthly rates",
                )

    stock_index = finance_dir / "beancount/price/stock/index.bean"
    if stock_index.exists():
        in_price_section = False
        for line in stock_index.read_text().splitlines():
            if "; Price data" in line:
                in_price_section = True
                continue
            if in_price_section:
                match = re.match(r'include "(\w+)\.bean"', line)
                if match:
                    symbol = match.group(1).upper()
                    stocks[symbol] = (
                        finance_dir / f"beancount/price/stock/{symbol.lower()}.bean",
                        f"{symbol} weekly closing prices",
                    )

    return forex, stocks


def fetch_forex_historical(client: httpx.Client, api_key: str, symbol: str) -> str:
    return query(client, api_key, {"function": "FX_MONTHLY", "from_symbol": symbol, "to_symbol": "USD"}, csv=True)


def fetch_stock_historical(client: httpx.Client, api_key: str, symbol: str) -> str:
    return query(client, api_key, {"function": "TIME_SERIES_WEEKLY_ADJUSTED", "symbol": symbol}, csv=True)


def fetch_forex_latest(client: httpx.Client, api_key: str, symbol: str):
    data = query(client, api_key, {"function": "CURRENCY_EXCHANGE_RATE", "from_currency": symbol, "to_currency": "USD"})
    rate_data = data.get("Realtime Currency Exchange Rate", {})
    return rate_data.get("6. Last Refreshed", ""), rate_data.get("5. Exchange Rate", "")


def fetch_stock_latest(client: httpx.Client, api_key: str, symbol: str):
    data = query(client, api_key, {"function": "GLOBAL_QUOTE", "symbol": symbol})
    quote = data.get("Global Quote", {})
    return quote.get("07. latest trading day", ""), quote.get("05. price", "")


def append_latest_to_rows(rows: list, timestamp: str, close_price: str, is_forex: bool):
    """Append latest quote to rows if date not already present."""
    if not timestamp or not close_price or close_price.lower() in ("none", "null", ""):
        return

    if is_forex and " " in timestamp:
        timestamp = timestamp.split(" ")[0]

    existing_dates = {row["timestamp"] for row in rows}
    if timestamp not in existing_dates:
        if is_forex:
            rows.append({"timestamp": timestamp, "close": close_price})
        else:
            rows.append({"timestamp": timestamp, "close": close_price})


def csv_to_bean(csv_text: str, symbol: str, comment: str, latest_row: dict | None = None) -> str:
    """Convert CSV text to beancount price format."""
    lines = [f"; {comment}"]

    reader = csv.DictReader(StringIO(csv_text))
    rows = list(reader)

    if latest_row:
        existing_dates = {row["timestamp"] for row in rows}
        if latest_row["timestamp"] not in existing_dates:
            rows.append(latest_row)

    rows.sort(key=lambda x: x["timestamp"], reverse=True)

    for row in rows:
        date = row["timestamp"]
        if date < START_DATE:
            continue
        close = row["close"]
        if not close or close.lower() in ("none", "null", ""):
            continue
        if " " in date:
            date = date.split(" ")[0]
        lines.append(f"{date} price {symbol}  {close} USD")

    return "\n".join(lines) + "\n"


def update_symbol(client: httpx.Client, api_key: str, symbol: str, is_forex: bool, bean_path: Path, comment: str):
    """Fetch data and update bean file for a symbol."""
    click.echo(f"  {symbol}...", nl=False)

    # Fetch historical data
    if is_forex:
        csv_text = fetch_forex_historical(client, api_key, symbol)
    else:
        csv_text = fetch_stock_historical(client, api_key, symbol)
    time.sleep(API_CALL_DELAY)

    # Fetch latest quote
    latest_row = None
    if is_forex:
        timestamp, rate = fetch_forex_latest(client, api_key, symbol)
        if timestamp and rate:
            ts = timestamp.split(" ")[0] if " " in timestamp else timestamp
            latest_row = {"timestamp": ts, "close": rate}
            click.echo(f" {rate} ({timestamp})", nl=False)
    else:
        trading_day, price = fetch_stock_latest(client, api_key, symbol)
        if trading_day and price:
            latest_row = {"timestamp": trading_day, "close": price}
            click.echo(f" {price} ({trading_day})", nl=False)
    time.sleep(API_CALL_DELAY)

    # Convert and write
    content = csv_to_bean(csv_text, symbol, comment, latest_row)
    bean_path.write_text(content)
    click.echo(" done")


@click.command("update-market-data")
def update_market_data():
    """Fetch and update forex rates and stock prices from Alpha Vantage."""
    api_key = get_api_key()
    finance_dir = _finance_dir()
    forex, stocks = parse_symbols_from_index(finance_dir)

    click.echo(f"Forex: {', '.join(forex.keys()) or 'none'}")
    click.echo(f"Stocks: {', '.join(stocks.keys()) or 'none'}")

    with httpx.Client() as client:
        if forex:
            click.echo("\nForex:")
            for symbol, (bean_path, comment) in forex.items():
                try:
                    update_symbol(client, api_key, symbol, True, bean_path, comment)
                except Exception as e:
                    click.echo(f" error: {e}")

        if stocks:
            click.echo("\nStocks:")
            for symbol, (bean_path, comment) in stocks.items():
                try:
                    update_symbol(client, api_key, symbol, False, bean_path, comment)
                except Exception as e:
                    click.echo(f" error: {e}")

    click.echo("\nDone.")
