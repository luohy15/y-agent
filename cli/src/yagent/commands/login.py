"""Login command — authenticate via Google OAuth through the web app."""

import os
import socket
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import click

from yagent.api_client import save_auth, DEFAULT_API_URL


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handle the OAuth callback from the web app."""

    token = None
    email = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        token = params.get("auth_token", [None])[0]
        email = params.get("auth_email", [None])[0]

        if token and email:
            _CallbackHandler.token = token
            _CallbackHandler.email = email
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Login successful! You can close this tab.</h2></body></html>")
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Login failed. Please try again.</h2></body></html>")

    def log_message(self, format, *args):
        pass  # suppress request logs


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@click.command("login")
@click.option("--token", help="Directly provide auth token (for non-interactive use).")
@click.option("--email", help="Email associated with the token.")
@click.option("--no-browser", is_flag=True, help="Manual login for headless servers — shows URL and prompts for token.")
def login(token, email, no_browser):
    """Authenticate with Google via the web app."""
    api_url = os.environ.get("Y_AGENT_API_URL", DEFAULT_API_URL)

    if token:
        if not email:
            email = click.prompt("Enter your email")
        save_auth(token.strip(), email.strip(), api_url)
        click.echo(f"Logged in as {email.strip()}")
        return

    if no_browser:
        login_url = f"{api_url}?auth_redirect=manual"
        click.echo(f"Visit this URL to login:\n\n  {login_url}\n")
        token = click.prompt("Paste your token here")
        email = click.prompt("Enter your email")
        save_auth(token.strip(), email.strip(), api_url)
        click.echo(f"Logged in as {email.strip()}")
        return

    port = _find_free_port()
    callback_url = f"http://localhost:{port}/callback"

    # Reset state
    _CallbackHandler.token = None
    _CallbackHandler.email = None

    server = HTTPServer(("localhost", port), _CallbackHandler)

    login_url = f"{api_url}?auth_redirect={callback_url}"
    click.echo(f"Opening browser for login...")
    click.echo(f"If the browser doesn't open, visit: {login_url}")
    webbrowser.open(login_url)

    # Wait for callback
    while _CallbackHandler.token is None:
        server.handle_request()

    server.server_close()

    save_auth(_CallbackHandler.token, _CallbackHandler.email, api_url)
    click.echo(f"Logged in as {_CallbackHandler.email}")
