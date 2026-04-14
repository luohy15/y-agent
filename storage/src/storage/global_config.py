"""Load global config from ~/.y-agent/config.toml."""

import os

_DEFAULT_HOME = os.path.expanduser("~/.y-agent")
_CONFIG_PATH = os.path.join(_DEFAULT_HOME, "config.toml")
_loaded = False


def load_global_config():
    """Load ~/.y-agent/config.toml and set values as env vars.

    Only sets vars not already in the environment (env vars take precedence).
    Safe to call multiple times — only loads once.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True

    if not os.path.exists(_CONFIG_PATH):
        return

    import tomllib
    with open(_CONFIG_PATH, "rb") as f:
        config = tomllib.load(f)

    for key, value in config.items():
        if isinstance(value, str) and key not in os.environ:
            os.environ[key] = value
