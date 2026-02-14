from typing import List, Optional
from storage.entity.dto import Message, BotConfig
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.theme import Theme

# Custom theme for role-based colors
custom_theme = Theme({
    "user": "green",
    "assistant": "cyan",
    'system': "yellow",
    "tool": "blue",
})

class DisplayManager:
    def __init__(self, bot_config: Optional[BotConfig] = None):
        self.console = Console(theme=custom_theme)

    def _format_tool_call(self, tool: str, args: dict, status: str = "approved") -> str:
        """Format a tool call for display. status: pending, denied, approved."""
        style = {"pending": "tool", "denied": "dim", "approved": "assistant"}[status]
        if tool == "bash":
            prefix = "$" if status == "approved" else "#"
            cmd = args.get("command", "")
            cmd = cmd[:200] + '...' if len(cmd) > 200 else cmd
            return f"[{style}]{prefix} {cmd}[/{style}]"
        elif tool == "file_read":
            return f'[{style}]read[/{style}]("{args.get("path", "")}")'
        elif tool == "file_write":
            return f'[{style}]write[/{style}]("{args.get("path", "")}")'
        elif tool == "file_edit":
            return f'[{style}]edit[/{style}]("{args.get("path", "")}")'
        else:
            import json
            args_str = json.dumps(args, separators=(',', ':'))
            args_str = args_str[:200] + '...' if len(args_str) > 200 else args_str
            return f"[{style}]{tool}[/{style}]({args_str})"

    def display_message_panel(self, message: Message, index: Optional[int] = None):
        """Display a message in a panel with role-colored borders."""
        index_str = f"[{index}] " if index is not None else ""

        # Assistant message with tool_calls: show content + pending tool status
        if message.role == "assistant" and message.tool_calls:
            if message.content:
                content = message.content
                if isinstance(content, list):
                    content = next((part.text for part in content if part.type == 'text'), '')
                if content.strip():
                    self.console.print(Markdown(content))
                    self.console.print()
            # Show pending tool calls
            import json
            for tc in message.tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
                display = self._format_tool_call(tool_name, args, status="pending")
                self.console.print(f"{display}")
            return

        # Tool result: show tool name + args + result together
        if message.role == "tool":
            args = message.arguments or {}
            tool = message.tool or "unknown"
            result = message.content if isinstance(message.content, str) else str(message.content)
            status = "denied" if result.startswith("ERROR: User denied") else "approved"
            display = self._format_tool_call(tool, args, status=status)
            result = result.replace('\n', ' ')[:80]
            self.console.print(f"{display}")
            self.console.print(f"[tool]→ {result}[/tool]\n")
            return

        # Extract content text from structured content if needed
        content = message.content
        if isinstance(content, list):
            content = next((part.text for part in content if part.type == 'text'), '')

        # replace <thinking> and </thinking> with thinking emoji
        for tag in ['<thinking>', '</thinking>']:
            content = content.replace(tag, '🤔')

        # Construct display content with reasoning first
        display_content = ""
        if message.reasoning_content:
            display_content = f"```markdown\n{message.reasoning_content}\n```\n"
        display_content += content

        # Add Perplexity reference links if available
        if message.role == "assistant" and message.links and message.provider and "perplexity" in message.provider.lower():
            links_info = "\n\n**References:**\n"
            for i, link in enumerate(message.links, 1):
                if isinstance(link, dict):
                    title = link.get('title', link.get('url', f'Reference {i}'))
                    url = link.get('url', link.get('link', ''))
                    links_info += f"{i}. [{title}]({url})\n"
                else:
                    links_info += f"{i}. [{link}]({link})\n"
            display_content += links_info

        if message.role == "user":
            self.console.print(Panel(
                Markdown(display_content),
                title=f"{index_str}" if index_str else None,
                border_style="user"
            ))
            self.console.print()
        else:
            self.console.print(Markdown(display_content))
            self.console.print()

    def print_error(self, error: str, show_traceback: bool = False):
        """Display an error message with optional traceback in a panel"""
        error_content = f"[red]{error}[/red]"
        if show_traceback and hasattr(error, '__traceback__'):
            import traceback
            error_content += f"\n\n[red]Detailed error:\n{''.join(traceback.format_tb(error.__traceback__))}[/red]"

        self.console.print(Panel(
            Markdown(error_content),
            title="[red]Error[/red]",
            border_style="red"
        ))
