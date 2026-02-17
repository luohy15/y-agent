"""Permission system for agent tool execution.

Tools like file_read and file_write are always allowed.
Bash commands require matching against an allow list with glob-style patterns.

Config file: ~/.y-agent/permissions.json
Example:
{
    "permissions": {
        "allow": [
            "Bash(python:*)",
            "Bash(ls:*)",
            "Bash(cat:*)"
        ]
    }
}

Pattern format: "Bash(<program>:<args_pattern>)"
- "*" matches anything
- The program is matched against the first token of the command
- The args_pattern is matched against the rest using fnmatch
"""

import json
import os
import fnmatch
from typing import Dict, List, Optional


class PermissionManager:
    """Manages tool execution permissions."""

    # Tools that are always allowed without permission checks
    ALWAYS_ALLOWED = {"file_read", "file_write", "file_edit"}

    # Read-only bash commands that are always allowed
    READONLY_BASH_COMMANDS = {
        "ls", "find", "cat", "head", "tail",
        "grep", "wc", "date", "pwd", "echo",
    }

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            home = os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))
            config_path = os.path.join(home, "permissions.json")
        self.config_path = config_path
        self.allow_patterns: List[str] = []
        self._load_config()

    def _load_config(self):
        """Load permissions config from file."""
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path) as f:
                data = json.load(f)
            self.allow_patterns = data.get("permissions", {}).get("allow", [])
        except (json.JSONDecodeError, OSError):
            pass

    def is_allowed(self, tool_name: str, arguments: Dict) -> bool:
        """Check if a tool call is allowed.

        Args:
            tool_name: Name of the tool (e.g., "bash", "file_read")
            arguments: Tool arguments dict

        Returns:
            True if allowed, False if denied
        """
        if tool_name in self.ALWAYS_ALLOWED:
            return True

        if tool_name == "bash":
            return self._check_bash_permission(arguments.get("command", ""))

        # Unknown tools are denied by default
        return False

    def _check_bash_permission(self, command: str) -> bool:
        """Check if a bash command matches any allow pattern.

        Pattern format: "Bash(<program>:<args_pattern>)"
        - program: matched against the first token of the command
        - args_pattern: matched against the rest using fnmatch glob
        - "Bash(*)" allows all bash commands
        """
        command = command.strip()
        if not command:
            return False

        # Split command into program and args
        parts = command.split(None, 1)
        program = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        # Read-only commands are always allowed
        if program in self.READONLY_BASH_COMMANDS:
            return True

        for pattern in self.allow_patterns:
            if not pattern.startswith("Bash(") or not pattern.endswith(")"):
                continue

            inner = pattern[5:-1]  # strip "Bash(" and ")"

            # "Bash(*)" allows everything
            if inner == "*":
                return True

            if ":" not in inner:
                # "Bash(python)" - match program only, any args
                if fnmatch.fnmatch(program, inner):
                    return True
                continue

            prog_pattern, args_pattern = inner.split(":", 1)

            if not fnmatch.fnmatch(program, prog_pattern):
                continue

            if args_pattern == "*" or fnmatch.fnmatch(args, args_pattern):
                return True

        return False
