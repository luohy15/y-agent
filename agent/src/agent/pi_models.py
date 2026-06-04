"""pi models.json management — provider builder helpers and sync hooks.

These functions live in the agent package so they can be imported by both
the worker (launch-time merge) and cli/api (CRUD-time full rebuild).
"""

import io
import json
import re

from loguru import logger

from storage.entity.dto import BotConfig, _throughput_enabled
from storage.service import bot_config as bot_service

from agent.claude_code import _parse_ssh_target, _shell_quote, _ssh_exec


# Stock OpenRouter endpoint that BotConfig falls back to when base_url is unset.
# A pi bot left at this default keeps the v1 behavior (provider inferred from the
# `<provider>/<model>` prefix); only an explicitly-configured custom gateway
# triggers models.json custom-provider registration.
DEFAULT_BOT_BASE_URL = BotConfig.__dataclass_fields__["base_url"].default


def _pi_provider_name(bot_name: str) -> str:
    """Synthetic, namespaced pi provider name derived from a bot name.

    Prefixed with `y-` so it never collides with pi's built-in providers
    (anthropic / openrouter / google / ...).
    """
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", bot_name or "bot").strip("-") or "bot"
    return f"y-{safe}"


def _apply_throughput_suffix(model_id: str, bot_config) -> str:
    """Append OpenRouter's `:nitro` throughput shorthand to a pi model id when the
    bot is throughput-routed. pi sends Anthropic-messages bodies, so the body-level
    `provider` field can't be injected; `:nitro` is the only lever and rides along
    in the model slug. Idempotent: never doubles an existing suffix."""
    if model_id and _throughput_enabled(bot_config) and not model_id.endswith(":nitro"):
        return f"{model_id}:nitro"
    return model_id


def build_pi_models_provider(bot_config) -> tuple[str, dict]:
    """Materialize a pi custom-provider entry from bot_config.base_url.

    pi has no generic per-provider base-url env override, so an OpenAI/Anthropic
    gateway (like the OpenRouter cloudflare gateway used by deepseek/inline) must
    be registered as a custom provider in ~/.pi/agent/models.json. This keeps the
    bot config (base_url + api_key + model) the single source of truth: the worker
    generates the provider entry and addresses it via `--model <provider>/<model>`.

    Returns (provider_name, provider_dict).
    """
    provider_name = _pi_provider_name(bot_config.name)
    model_name = bot_config.model.strip('"').strip() if bot_config.model else ""
    model_id = _apply_throughput_suffix(model_name, bot_config)
    provider = {
        "baseUrl": bot_config.base_url,
        "api": "anthropic-messages",
        "apiKey": bot_config.api_key or "",
        "models": [
            {
                "id": model_id,
                "name": model_name,
                "reasoning": True,
                "input": ["text", "image"],
                "contextWindow": 200000,
                "maxTokens": 16384,
            }
        ],
    }
    return provider_name, provider


def resolve_pi_model_and_provider(bot_config, model):
    """Apply base_url custom-provider routing to a pi model string.

    When a non-default (custom gateway) base_url is configured, the model is
    namespaced to a synthetic provider (`y-<bot>/<model>`) backed by a models.json
    entry the worker writes remotely; auth then lives in that entry. A bot left at
    the stock OpenRouter default keeps the v1 behavior (provider inferred from the
    model prefix, auth via --api-key). Returns (model, models_provider) where
    models_provider is None when no custom-provider routing applies.
    """
    base_url = bot_config.base_url
    if base_url and base_url != DEFAULT_BOT_BASE_URL and model:
        provider_name, provider_dict = build_pi_models_provider(bot_config)
        # Keep the --model reference in sync with the models.json `id` so pi selects
        # (and forwards) the `:nitro` slug when throughput routing is on.
        model = _apply_throughput_suffix(model, bot_config)
        return f"{provider_name}/{model}", {provider_name: provider_dict}
    return model, None


def _write_pi_models_json(
    client,
    models_provider: dict[str, dict],
    *,
    replace_owned: bool = False,
    owned_prefix: str = "y-",
) -> None:
    """Merge custom provider entries into ~/.pi/agent/models.json on the remote host.

    pi reads custom providers (gateways, proxies, self-hosted models) from
    $PI_CODING_AGENT_DIR/models.json (default ~/.pi/agent/models.json). The merge
    is keyed by provider name so multiple bots and any hand-written entries
    coexist; only the providers we own are overwritten on each launch.

    When replace_owned is True, all existing provider keys starting with owned_prefix
    are dropped before the merge, fully rebuilding the owned section from DB truth.
    When False (default), existing providers are updated in place, preserving any
    keys not in the merge set (backward-compatible launch-time merge).

    Providers with a falsy or empty-string apiKey are skipped and logged as a
    warning, so a misconfigured bot with an empty key can never poison the whole
    file again.
    """
    home = _ssh_exec(client, 'printf %s "$HOME"').strip()
    agent_dir = f"{home}/.pi/agent"
    models_path = f"{agent_dir}/models.json"
    _ssh_exec(client, f"mkdir -p {_shell_quote(agent_dir)}")

    # `|| true` keeps a missing file from surfacing cat's exit-1 (which _ssh_exec
    # would otherwise raise on, since 2>/dev/null only suppresses stderr text).
    existing = _ssh_exec(client, f"cat {_shell_quote(models_path)} 2>/dev/null || true").strip()
    data = {}
    if existing:
        try:
            data = json.loads(existing)
        except (ValueError, TypeError):
            logger.warning("pi_cli: ignoring unparseable models.json on remote host")
            data = {}
    if not isinstance(data, dict):
        data = {}

    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers

    if replace_owned:
        for key in list(providers.keys()):
            if key.startswith(owned_prefix):
                del providers[key]

    # Hardening: skip any provider with an empty apiKey so one bad bot can't
    # invalidate the whole file (see todo 2376).
    filtered = {}
    for name, provider in models_provider.items():
        api_key = provider.get("apiKey")
        if not api_key:
            logger.warning("Skipping provider '{}' with empty/falsy apiKey", name)
            continue
        filtered[name] = provider

    providers.update(filtered)

    payload = json.dumps(data, indent=2)
    sftp = client.open_sftp()
    try:
        with sftp.open(models_path, "w") as handle:
            handle.write(payload)
    finally:
        sftp.close()

    # The file holds a plaintext api key, so keep it owner-only.
    _ssh_exec(client, f"chmod 600 {_shell_quote(models_path)}")


def sync_pi_models(user_id: int, *, ssh_client=None) -> None:
    """Rebuild the `y-*` provider section in ~/.pi/agent/models.json from current DB state.

    Lists all bots for the user, keeps only pi_cli bots with a custom base_url and
    non-empty apiKey, builds the owned y-* provider set, resolves the default VM, opens
    an SSH session (or reuses the passed-in client), and writes the rebuilt section
    with replace_owned=True.

    Best-effort: SSH or connection errors and missing VM config are logged as warnings
    and swallowed so the CRUD operation that triggered the sync is not failed.
    """
    try:
        bots = bot_service.list_configs(user_id)
        owned_providers: dict[str, dict] = {}

        for bot in bots:
            effective_backend = bot.backend or bot.api_type
            if effective_backend != "pi_cli":
                continue
            if not bot.model:
                continue
            model, models_provider = resolve_pi_model_and_provider(bot, bot.model)
            if models_provider:
                owned_providers.update(models_provider)

        from agent.config import resolve_vm_config
        vm_config = resolve_vm_config(user_id)
        if not vm_config or not vm_config.vm_name:
            logger.warning("sync_pi_models: no default VM config for user_id={}", user_id)
            return
    except Exception as e:
        logger.warning("sync_pi_models: failed to prepare provider set: {}", e)
        return

    owns_client = ssh_client is None
    client = ssh_client
    try:
        if owns_client:
            import paramiko

            user, host, port = _parse_ssh_target(vm_config.vm_name)
            key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=user, pkey=key, timeout=30)

        _write_pi_models_json(client, owned_providers, replace_owned=True)
        logger.info("sync_pi_models: rebuilt y-* providers for user_id={}", user_id)
    except Exception as e:
        logger.warning("sync_pi_models: SSH write failed: {}", e)
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:
                pass
