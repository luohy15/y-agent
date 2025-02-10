import os
import sys
import asyncio
from typing import Optional

from .repository import ChatRepository
from cli.display_manager import DisplayManager
from cli.input_manager import InputManager
from mcp_setting.mcp_manager import MCPManager
from .openrouter_manager import OpenRouterManager
from .chat_manager import ChatManager
from config import bot_config_manager
from bot.models import BotConfig

class ChatApp:
    def __init__(self, bot_config: Optional[BotConfig] = None, chat_id: Optional[str] = None, verbose: bool = False):
        """Initialize the chat application.

        Args:
            bot_config: Bot configuration to use
            chat_id: Optional ID of existing chat to load
            verbose: Whether to show verbose output
        """
        # Initialize repository
        repository = ChatRepository()

        # Use default bot config if not provided
        if not bot_config:
            bot_config = bot_config_manager.get_config()

        # Initialize managers
        display_manager = DisplayManager()
        input_manager = InputManager(display_manager.console)
        mcp_manager = MCPManager(display_manager.console)
        openrouter_manager = OpenRouterManager(bot_config)
        self.chat_manager = ChatManager(
            repository=repository,
            display_manager=display_manager,
            input_manager=input_manager,
            mcp_manager=mcp_manager,
            openrouter_manager=openrouter_manager,
            bot_config=bot_config,
            chat_id=chat_id,
            verbose=verbose
        )

    async def chat(self):
        """Start the chat session"""
        await self.chat_manager.run()

async def main():
    try:
        # Set binary mode for stdin/stdout on Windows
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

        app = ChatApp(bot_config=bot_config_manager.get_config(), verbose=True)
        await app.chat()
    except KeyboardInterrupt:
        # Exit silently on Ctrl+C
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
