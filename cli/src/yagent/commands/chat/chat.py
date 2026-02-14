import asyncio
import click
from typing import Optional

from yagent.display_manager import DisplayManager
from yagent.input_manager import InputManager
from agent.config import make_provider
from yagent.chat.runner import run_chat
from storage.service import bot_config as bot_service
from loguru import logger

@click.command()
@click.option('--chat-id', '-c', help='Continue from an existing chat')
@click.option('--latest', '-l', is_flag=True, help='Continue from the latest chat')
@click.option('--model', '-m', help='OpenRouter model to use')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed usage instructions')
@click.option('--bot', '-b', help='Use specific bot name')
@click.option('--prompt', '-p', help='Run a one-off query and exit')
def chat(chat_id: Optional[str], latest: bool, model: Optional[str], verbose: bool = False, bot: Optional[str] = None, prompt: Optional[str] = None):
    """Start a new chat conversation or continue an existing one.

    Use --latest/-l to continue from your most recent chat.
    Use --chat-id/-c to continue from a specific chat ID.
    If neither option is provided, starts a new chat.
    Use --bot/-b to use a specific bot name.
    """
    if verbose:
        logger.info("Starting chat command")

    bot_config = bot_service.get_config(bot or "default")
    bot_config.model = model or bot_config.model

    # Handle --latest flag
    if latest:
        from storage.service import chat as chat_service
        chats = asyncio.run(chat_service.list_chats(limit=1))
        if not chats:
            click.echo("Error: No existing chats found")
            raise click.Abort()
        chat_id = chats[0].chat_id

    display_manager = DisplayManager(bot_config)
    input_manager = InputManager(display_manager.console)
    provider = make_provider(bot_config)

    if verbose:
        logger.info(f"Using OpenRouter API Base URL: {bot_config.base_url}")
        if bot:
            logger.info(f"Using bot: {bot}")
        if chat_id:
            logger.info(f"Continuing from chat {chat_id}")
        else:
            logger.info("Starting new chat")

    asyncio.run(run_chat(
        display_manager=display_manager,
        input_manager=input_manager,
        provider=provider,
        chat_id=chat_id,
        verbose=verbose,
        prompt=prompt,
    ))
