"""Build and atomically merge pi provider metadata; credentials stay in launch env."""

import json
from dataclasses import replace

from agent.claude_code import _shell_quote, _ssh_exec
from storage.dto.bot import provider_base_url, _throughput_enabled


def build_pi_provider(bot, entry, model, context_window=None):
    base_url = provider_base_url((entry or {}).get("base_url") or bot.base_url, "pi", bot.api_key)
    if not base_url or not (bot.api_key or "").strip() or not model:
        raise ValueError("pi requires base_url, api_key and model (no host config fallback)")
    effective = replace(bot, base_url=base_url)
    if _throughput_enabled(effective) and not model.endswith(":nitro"):
        model += ":nitro"
    definition = {
        "id": model, "name": model, "reasoning": False, "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }
    if context_window:
        definition["contextWindow"] = context_window
    name = f"y-{bot.name}"
    return name, {
        "baseUrl": base_url, "api": "anthropic-messages", "authHeader": True,
        "apiKey": "$Y_PI_API_KEY", "models": [definition],
    }


def stage_pi_provider(client, provider, agent_dir=None):
    """Serialize concurrent merges on the node and atomically replace models.json.

    No key is sent in this payload. A malformed existing file fails closed;
    unrelated providers/settings are preserved. The CLI uses the same default
    PI_CODING_AGENT_DIR (or ~/.pi/agent) as this remote setup.
    """
    if not provider:
        raise ValueError("pi provider metadata is required")
    payload = json.dumps(provider)
    script = f"provider_payload = {payload!r}\nagent_dir = {agent_dir!r}\n" + '''import fcntl, json, os, tempfile
from pathlib import Path
root = Path(agent_dir or os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
root.mkdir(parents=True, exist_ok=True)
with (root / ".y-models.lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    path = root / "models.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    name, provider = json.loads(provider_payload)
    data.setdefault("providers", {})[name] = provider
    fd, tmp = tempfile.mkstemp(prefix=".y-models-", dir=root)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
print("Y_PI_MODELS_OK")
'''
    result = _ssh_exec(client, "python3 -c " + _shell_quote(script))
    if result.strip() != "Y_PI_MODELS_OK":
        raise RuntimeError("pi models.json staging failed")
