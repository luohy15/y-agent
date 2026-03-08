"""Alpha Vantage API client utilities."""

import os
from pathlib import Path

import click
import httpx
from dotenv import load_dotenv


BASE_URL = "https://www.alphavantage.co/query"


def get_api_key() -> str:
    home = Path(os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent")))
    load_dotenv(home / ".env")
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        raise click.ClickException("ALPHAVANTAGE_API_KEY not found in $Y_AGENT_HOME/.env")
    return key


def query(client: httpx.Client, api_key: str, params: dict, csv: bool = False) -> dict | str:
    """Make an Alpha Vantage API request.

    Args:
        client: httpx client
        api_key: Alpha Vantage API key
        params: query parameters (function, symbol, etc.) — apikey is added automatically
        csv: if True, add datatype=csv and return raw text instead of JSON
    """
    params = {**params, "apikey": api_key}
    if csv:
        params["datatype"] = "csv"
    resp = client.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text if csv else resp.json()
