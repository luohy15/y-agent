import asyncio
import click
from typing import Optional

from yagent.display_manager import DisplayManager
from yagent.input_manager import InputManager
from agent.config import make_provider
from yagent.chat.runner import run_chat
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from loguru import logger


@click.group('chat', invoke_without_command=True)
@click.option('--chat-id', '-c', help='Continue from an existing chat')
@click.option('--latest', '-l', is_flag=True, help='Continue from the latest chat')
@click.option('--model', '-m', help='OpenRouter model to use')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed usage instructions')
@click.option('--bot', '-b', help='Use specific bot name')
@click.option('--prompt', '-p', help='Run a one-off query and exit')
@click.pass_context
def chat_group(ctx, chat_id: Optional[str], latest: bool, model: Optional[str], verbose: bool = False, bot: Optional[str] = None, prompt: Optional[str] = None):
    """Chat with AI models."""
    if ctx.invoked_subcommand is not None:
        return

    if verbose:
        logger.info("Starting chat command")

    bot_config = bot_service.get_config(get_cli_user_id(), bot or "default")
    bot_config.model = model or bot_config.model

    # Handle --latest flag
    if latest:
        from storage.service import chat as chat_service
        chats = asyncio.run(chat_service.list_chats(get_cli_user_id(), limit=1))
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


from .list import list_chats
from .share import share
from .import_chat import import_chats
from .import_claude import import_claude

chat_group.add_command(list_chats)
chat_group.add_command(share)
chat_group.add_command(import_chats)
chat_group.add_command(import_claude)
