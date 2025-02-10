from typing import List, Dict, Optional
from contextlib import AsyncExitStack
from types import SimpleNamespace

from chat.models import Chat, Message
from .repository import ChatRepository
from .service import ChatService
from cli.display_manager import DisplayManager
from cli.input_manager import InputManager
from mcp_setting.mcp_manager import MCPManager
from mcp_setting.system import get_system_prompt
from .openrouter_manager import OpenRouterManager
from bot import BotConfig

class ChatManager:
    def __init__(
        self,
        repository: ChatRepository,
        display_manager: DisplayManager,
        input_manager: InputManager,
        mcp_manager: MCPManager,
        openrouter_manager: OpenRouterManager,
        bot_config: BotConfig,
        chat_id: Optional[str] = None,
        verbose: bool = False
    ):
        """Initialize chat manager with required components.

        Args:
            repository: Repository for chat persistence
            display_manager: Manager for display and UI
            input_manager: Manager for user input
            mcp_manager: Manager for MCP operations
            openrouter_manager: Manager for OpenRouter interactions
            bot_config: Bot configuration
            chat_id: Optional ID of existing chat to load
            verbose: Whether to show verbose output
        """
        self.service = ChatService(repository)
        self.bot_config = bot_config
        self.model = bot_config.model
        self.display_manager = display_manager
        self.input_manager = input_manager
        self.mcp_manager = mcp_manager
        self.openrouter_manager = openrouter_manager
        self.verbose = verbose

        # Set up cross-manager references
        self.openrouter_manager.set_display_manager(display_manager)

        # Initialize chat state
        self.current_chat: Optional[Chat] = None
        self.messages: List[Message] = []
        self.system_prompt: Optional[str] = None

        if chat_id:
            self._load_chat(chat_id)

    def _load_chat(self, chat_id: str):
        """Load an existing chat by ID"""
        existing_chat = self.service.get_chat(chat_id)
        if not existing_chat:
            self.display_manager.print_error(f"Chat {chat_id} not found")
            raise ValueError(f"Chat {chat_id} not found")

        self.messages = existing_chat.messages
        self.current_chat = existing_chat

        if self.verbose:
            self.display_manager.console.print(f"Loaded {len(self.messages)} messages from chat {chat_id}")

    def get_user_confirmation(self, content: str) -> bool:
        """Get user confirmation before executing tool use"""
        self.display_manager.console.print("\n[yellow]Tool use detected in response:[/yellow]")
        self.display_manager.console.print(content)
        while True:
            response = input("\nWould you like to proceed with tool execution? (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            self.display_manager.console.print("[yellow]Please answer 'y' or 'n'[/yellow]")

    async def process_user_message(self, user_message: Message):
        self.messages.append(user_message)
        self.display_manager.display_message_panel(user_message, index=len(self.messages) - 1)
        self.persist_chat()

        assistant_message = await self.openrouter_manager.call_chat_completions(self.messages, self.system_prompt)
        await self.process_assistant_message(assistant_message)
        self.persist_chat()

    async def process_assistant_message(self, assistant_message: Message):
        """Process assistant response and handle tool use recursively"""
        # Extract content and metadata based on response type
        content = assistant_message.content

        if not self.openrouter_manager.contains_tool_use(content):
            self.messages.append(assistant_message)
            self.display_manager.display_message_panel(assistant_message, index=len(self.messages) - 1)
            return

        # Handle response with tool use
        plain_content, tool_content = self.openrouter_manager.split_content(content)

        # Update last assistant message with plain content
        assistant_message.content = plain_content
        self.messages.append(assistant_message)
        self.display_manager.display_message_panel(assistant_message, index=len(self.messages) - 1)

        # Get user confirmation for tool execution
        if not self.get_user_confirmation(tool_content):
            no_exec_msg = "Tool execution cancelled by user."
            self.display_manager.console.print(f"\n[yellow]{no_exec_msg}[/yellow]")
            user_message = self.openrouter_manager.create_message("user", no_exec_msg)
            self.messages.append(user_message)
            return

        # Execute tool and get results
        mcp_tool = self.mcp_manager.extract_mcp_tool_use(tool_content)
        if mcp_tool:
            server_name, tool_name, arguments = mcp_tool
            tool_results = await self.mcp_manager.execute_tool(server_name, tool_name, arguments)
        else:
            tool_results = "Tool execution not supported for this response."
            return

        # Add tool results as user message
        user_message = self.openrouter_manager.create_message("user", tool_results)

        # Process user message and assistant response recursively
        await self.process_user_message(user_message)

    def persist_chat(self):
        """Persist current chat state"""
        if not self.current_chat:
            self.current_chat = self.service.create_chat(self.messages)
        else:
            self.current_chat = self.service.update_chat(self.current_chat.id, self.messages)

    async def run(self):
        """Run the chat session"""
        async with AsyncExitStack() as exit_stack:
            try:
                if self.bot_config.mcp_server_settings:
                    # Initialize MCP and system prompt if MCP server settings exist
                    await self.mcp_manager.connect_to_servers(self.bot_config.mcp_server_settings, exit_stack)
                    self.system_prompt = await get_system_prompt(self.mcp_manager)

                if self.verbose:
                    self.display_manager.display_help()

                # Display existing messages if continuing from a previous chat
                if self.messages:
                    self.display_manager.display_chat_history(self.messages)

                while True:
                    # Get user input, multi-line flag, and line count
                    user_input, is_multi_line, line_count = self.input_manager.get_input()

                    if self.input_manager.is_exit_command(user_input):
                        self.display_manager.console.print("\n[yellow]Goodbye![/yellow]")
                        break

                    if not user_input:
                        self.display_manager.console.print("[yellow]Please enter a message.[/yellow]")
                        continue

                    # Handle copy command
                    if user_input.lower().startswith('copy '):
                        if self.input_manager.handle_copy_command(user_input, self.messages):
                            continue

                    # Add user message to history
                    user_message = self.openrouter_manager.create_message("user", user_input)
                    if is_multi_line:
                        # clear <<EOF line and EOF line
                        self.display_manager.clear_lines(2)

                    self.display_manager.clear_lines(line_count)

                    await self.process_user_message(user_message)

            except (KeyboardInterrupt, EOFError):
                self.display_manager.console.print("\n[yellow]Chat interrupted. Exiting...[/yellow]")
            finally:
                # Clear sessions on exit
                self.mcp_manager.clear_sessions()
