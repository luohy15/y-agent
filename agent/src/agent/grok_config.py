"""Remote Grok Build custom-model configuration for relay-routed bots."""

import json
import re
import tomllib

from agent.claude_code import _shell_quote, _ssh_exec


def build_grok_model_entry(bot_config) -> tuple[str, dict]:
    """Build the Grok custom-model entry used for a relay-routed bot."""
    model = bot_config.model.strip('"').strip() if bot_config.model else "grok-build"
    return "y-grok", {
        "model": model,
        "base_url": bot_config.base_url,
        "name": "Grok Build (relay)",
        "api_backend": "responses",
        "env_key": "XAI_API_KEY",
    }


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _toml_value(value) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{_toml_key(key)} = {_toml_value(item)}" for key, item in value.items())
        return "{ " + pairs + " }"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def _toml_path(path: list[str]) -> str:
    return ".".join(_toml_key(key) for key in path)


def _render_toml_table(path: list[str], table: dict, lines: list[str], header: str = None) -> None:
    if header:
        if lines:
            lines.append("")
        lines.append(header)

    scalar_items = []
    child_tables = []
    array_tables = []
    for key, value in table.items():
        if isinstance(value, dict):
            child_tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            array_tables.append((key, value))
        else:
            scalar_items.append((key, value))

    lines.extend(f"{_toml_key(key)} = {_toml_value(value)}" for key, value in scalar_items)
    for key, value in child_tables:
        child_path = path + [key]
        _render_toml_table(child_path, value, lines, f"[{_toml_path(child_path)}]")
    for key, values in array_tables:
        child_path = path + [key]
        for value in values:
            _render_toml_table(child_path, value, lines, f"[[{_toml_path(child_path)}]]")


def merge_grok_config_toml(existing: str, alias: str, entry: dict) -> str:
    """Merge a managed custom model into an existing valid Grok TOML config."""
    data = tomllib.loads(existing) if existing.strip() else {}
    models = data.setdefault("model", {})
    if not isinstance(models, dict):
        raise ValueError("Grok config [model] must be a table")
    models[alias] = entry

    lines: list[str] = []
    _render_toml_table([], data, lines)
    return "\n".join(lines) + "\n"


def write_grok_config_toml(client, alias: str, entry: dict) -> None:
    """Merge the relay model into the remote ``~/.grok/config.toml``."""
    config_path = "~/.grok/config.toml"
    _ssh_exec(client, "mkdir -p ~/.grok")
    existing = _ssh_exec(client, f"cat {_shell_quote(config_path)} 2>/dev/null || true")
    content = merge_grok_config_toml(existing, alias, entry)

    sftp = client.open_sftp()
    try:
        remote_path = f"{sftp.normalize('.')}/.grok/config.toml"
        with sftp.open(remote_path, "w") as config_file:
            config_file.write(content)
    finally:
        sftp.close()
    _ssh_exec(client, f"chmod 600 {_shell_quote(config_path)}")
