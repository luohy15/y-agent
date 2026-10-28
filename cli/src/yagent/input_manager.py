import pyperclip
from typing import List, Tuple
from prompt_toolkit import prompt
from rich.console import Console
from storage.entity.dto import Message

class InputManager:
    def __init__(self, console: Console):
        self.console = console

    def get_input(self) -> Tuple[str, bool, int]:
        """Get user input with support for multi-line input using EOF flags.

        Multi-line input starts with <<EOF and ends with EOF. For example:
        <<EOF
        line 1
        line 2
        EOF

        Returns:
            Tuple[str, bool, int]: A tuple containing:
                - The user input, either single line or multiple lines joined with newlines
                - A boolean indicating if the input was multi-line (True) or single-line (False)
                - The number of lines in the input
        """
        text = prompt('Enter: ', in_thread=True)
        text = text.rstrip()

        # Check for multi-line input start flag
        if text == "<<EOF":
            lines = []
            while True:
                line = prompt(in_thread=True)
                if line == "EOF":
                    break
                lines.extend(line.split("\n"))
            return ("\n".join(lines), True, len(lines))

        lines = text.split("\n")
        return (text, False, len(lines))

    def handle_copy_command(self, command: str, messages: List[Message]) -> bool:
        """Handle the copy command for messages by index.

        Args:
            command: The copy command (e.g., 'copy 1')
            messages: List of all chat messages

        Returns:
            bool: True if command was handled, False otherwise
        """
        try:
            msg_idx = int(command.split()[1])
            if 0 <= msg_idx < len(messages):
                content = messages[msg_idx].content
                if isinstance(content, list):
                    content = next((part['text'] for part in content if part['type'] == 'text'), '')
                pyperclip.copy(content.strip())
                self.console.print(f"[green]Copied message [{msg_idx}] to clipboard[/green]")
            else:
                # Show available message indices
                msg_indices = [f"[{i}] {msg.role}" for i, msg in enumerate(messages)]
                self.console.print("[yellow]Invalid message index. Available messages:[/yellow]")
                for idx in msg_indices:
                    self.console.print(idx)
            return True
        except (IndexError, ValueError):
            self.console.print("[yellow]Invalid copy command. Use 'copy <number>' to copy a message[/yellow]")
            return True

    def is_exit_command(self, text: str) -> bool:
        """Check if the input is an exit command.

        Args:
            text: The input text to check

        Returns:
            bool: True if the input is an exit command, False otherwise
        """
        return text.lower() in ['exit', 'quit']
