import click
import httpx

from yagent.api_client import api_request


def access_request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        return api_request(method, path, **kwargs)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise click.ClickException("Access denied. Sign in as the deployment maintainer.") from None
        raise
