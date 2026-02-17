import os
import click
from yagent.config import config
from storage.database.base import init_tables
from storage.entity.dto import BotConfig
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id

def print_config_info():
    """Print configuration information and available settings."""
    home = os.getenv("Y_AGENT_HOME", "~/.y-agent")
    click.echo(f"\n{click.style('Y_AGENT_HOME:', fg='green')}\n{click.style(home, fg='cyan')}")
    click.echo(f"{click.style('Database:', fg='green')}\n{click.style(config['database_url'], fg='cyan')}")

    click.echo(f"\n{click.style('Optional settings that can be configured using `y-agent bot add`:', fg='green')}")
    click.echo(f"- {click.style('model:', fg='yellow')} The model to use for chat")
    click.echo(f"- {click.style('base_url:', fg='yellow')} OpenRouter API base URL")
    click.echo(f"- {click.style('description:', fg='yellow')} Bot configuration description")
    click.echo(f"- {click.style('openrouter_config:', fg='yellow')} OpenRouter configuration settings")
    click.echo(f"- {click.style('max_tokens:', fg='yellow')} Maximum number of tokens in response")
    click.echo(f"- {click.style('custom_api_path:', fg='yellow')} Custom path for chat completion API request")

    click.echo(f"\n{click.style('Proxy settings via env vars:', fg='magenta')}")
    click.echo(f"- {click.style('Y_AGENT_PROXY_HOST / Y_AGENT_PROXY_PORT:', fg='yellow')} Network proxy settings")

@click.command()
def init():
    """Initialize y-agent configuration with required settings.

    Creates tables and prompts for required settings.
    """

    # Ensure database tables exist
    init_tables()

    # Get existing default config or create new one
    user_id = get_cli_user_id()
    default_config = bot_service.get_config(user_id)

    # If already initialized with API key, skip to echo
    if default_config and default_config.api_key:
        print_config_info()
        return

    # Prompt for OpenRouter API key if not initialized
    api_key = click.prompt(
        "Please enter your OpenRouter API key",
        type=str,
        default=default_config.api_key,
        show_default=False
    )

    # Prompt for model name
    model = click.prompt(
        "Enter the model to use (e.g. anthropic/claude-sonnet-4-5)",
        type=str
    )

    # Create new config with updated API key and model
    new_config = BotConfig(
        name="default",
        api_key=api_key,
        base_url=default_config.base_url,
        model=model
    )

    # Update the default config
    bot_service.add_config(user_id, new_config)

    print_config_info()
