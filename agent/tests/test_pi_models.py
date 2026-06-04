import json
import unittest
from unittest.mock import Mock, patch

from storage.entity.dto import BotConfig
from agent.pi_models import (
    _pi_provider_name,
    build_pi_models_provider,
    resolve_pi_model_and_provider,
    _write_pi_models_json,
    sync_pi_models,
    DEFAULT_BOT_BASE_URL,
)

GATEWAY_URL = "https://gateway.ai.cloudflare.com/v1/acct/luohy15/openrouter"


class _ExecStream:
    def __init__(self, data=b"", exit_status=0):
        self._data = data
        self.channel = type("_Ch", (), {"recv_exit_status": staticmethod(lambda: exit_status)})()

    def read(self):
        return self._data


class _SftpFile:
    def __init__(self, sink, path):
        self._sink = sink
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, content):
        self._sink[self._path] = content


class _FakeSftp:
    def __init__(self, sink):
        self._sink = sink

    def open(self, path, _mode):
        return _SftpFile(self._sink, path)

    def close(self):
        pass


class _ModelsJsonClient:
    """Fake SSH client for _write_pi_models_json: serves HOME + existing file."""

    def __init__(self, home="/home/roy", existing=""):
        self.home = home
        self.existing = existing
        self.writes = {}
        self.commands = []

    def exec_command(self, cmd):
        self.commands.append(cmd)
        exit_status = 0
        if "$HOME" in cmd:
            data = self.home.encode()
        elif cmd.startswith("cat "):
            if self.existing is None:
                data = b""
                if "|| true" not in cmd:
                    exit_status = 1
            else:
                data = self.existing.encode()
        else:  # mkdir -p / chmod
            data = b""
        return None, _ExecStream(data, exit_status), _ExecStream(b"")

    def open_sftp(self):
        return _FakeSftp(self.writes)

    def close(self):
        pass

    def set_missing_host_key_policy(self, _policy):
        pass

    def connect(self, _host, **kwargs):
        pass


class PiProviderNameTest(unittest.TestCase):
    def test_safe_name_from_simple(self):
        self.assertEqual(_pi_provider_name("kimi"), "y-kimi")

    def test_special_chars_replaced(self):
        self.assertEqual(_pi_provider_name("a+b=c"), "y-a-b-c")


class BuildPiModelsProviderTest(unittest.TestCase):
    def test_build_from_bot_config(self):
        name, provider = build_pi_models_provider(
            BotConfig(
                name="pi",
                backend="pi_cli",
                base_url=GATEWAY_URL,
                api_key="sk-or-x",
                model='"anthropic/claude-sonnet-4.6"',
            )
        )
        self.assertEqual(name, "y-pi")
        self.assertEqual(provider["baseUrl"], GATEWAY_URL)
        self.assertEqual(provider["apiKey"], "sk-or-x")
        # OpenRouter-routed bot with no explicit openrouter_config defaults to
        # throughput, so the model id carries the `:nitro` shorthand.
        self.assertEqual(provider["models"][0]["id"], "anthropic/claude-sonnet-4.6:nitro")
        self.assertEqual(provider["models"][0]["name"], "anthropic/claude-sonnet-4.6")


class EmptyApiKeyGuardTest(unittest.TestCase):
    PROVIDER_GOOD = {"y-good": {"baseUrl": "https://good",
                                "api": "anthropic-messages", "apiKey": "sk-good"}}
    PROVIDER_EMPTY = {"y-empty": {"baseUrl": "https://empty",
                                   "api": "anthropic-messages", "apiKey": ""}}
    PROVIDER_MISSING = {"y-missing": {"baseUrl": "https://missing",
                                      "api": "anthropic-messages"}}

    def test_writes_only_good_provider(self):
        client = _ModelsJsonClient(existing=None)
        _write_pi_models_json(client, {
            **self.PROVIDER_GOOD,
            **self.PROVIDER_EMPTY,
            **self.PROVIDER_MISSING,
        })

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        self.assertIn("y-good", providers)
        self.assertNotIn("y-empty", providers)
        self.assertNotIn("y-missing", providers)

    def test_empty_key_is_skipped_with_warning(self):
        client = _ModelsJsonClient(existing=None)
        with patch("agent.pi_models.logger") as mock_logger:
            _write_pi_models_json(client, {
                **self.PROVIDER_GOOD,
                **self.PROVIDER_EMPTY,
            })

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        self.assertIn("y-good", providers)
        self.assertNotIn("y-empty", providers)
        # Warning logged for the skipped provider
        warning_calls = [c for c in mock_logger.warning.call_args_list
                         if "y-empty" in str(c)]
        self.assertEqual(len(warning_calls), 1)


class ReplaceOwnedTest(unittest.TestCase):
    def test_replace_owned_drops_existing_y_prefix_and_keeps_others(self):
        existing = json.dumps({
            "providers": {
                "y-old": {"baseUrl": "https://old", "api": "anthropic-messages",
                          "apiKey": "old"},
                "y-keep": {"baseUrl": "https://old-keep", "api": "anthropic-messages",
                             "apiKey": "keep"},
                "anthropic": {"baseUrl": "https://anthropic", "api": "anthropic-messages",
                              "apiKey": "sk-ant"},
            }
        })
        new_providers = {
            "y-keep": {"baseUrl": "https://new-keep", "api": "anthropic-messages",
                       "apiKey": "keep-new"},
            "y-new": {"baseUrl": "https://new", "api": "anthropic-messages",
                      "apiKey": "new"},
        }
        client = _ModelsJsonClient(existing=existing)
        _write_pi_models_json(client, new_providers, replace_owned=True)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        self.assertNotIn("y-old", providers)
        self.assertEqual(providers["y-keep"]["baseUrl"], "https://new-keep")
        self.assertIn("y-new", providers)
        self.assertEqual(providers["anthropic"]["baseUrl"], "https://anthropic")

    def test_without_replace_keeps_existing_y_entries(self):
        existing = json.dumps({
            "providers": {
                "y-old": {"baseUrl": "https://old", "api": "anthropic-messages",
                          "apiKey": "old"},
            }
        })
        new_providers = {"y-new": {"baseUrl": "https://new", "api": "anthropic-messages",
                                     "apiKey": "new"}}
        client = _ModelsJsonClient(existing=existing)
        _write_pi_models_json(client, new_providers, replace_owned=False)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        self.assertIn("y-old", providers)
        self.assertIn("y-new", providers)

    def test_replace_owned_with_empty_set_cleans_all_y(self):
        existing = json.dumps({
            "providers": {
                "y-old": {"baseUrl": "https://old", "api": "anthropic-messages",
                          "apiKey": "old"},
                "anthropic": {"baseUrl": "https://anthropic", "api": "anthropic-messages",
                              "apiKey": "sk-ant"},
            }
        })
        client = _ModelsJsonClient(existing=existing)
        _write_pi_models_json(client, {}, replace_owned=True)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        self.assertNotIn("y-old", providers)
        self.assertIn("anthropic", providers)


class SyncPiModelsTest(unittest.TestCase):
    def test_sync_rebuilds_from_current_pi_cli_bots(self):
        """sync_pi_models lists bots, filters pi_cli, builds providers, and
        writes with replace_owned=True."""
        bot_good = BotConfig(
            name="kimi",
            backend="pi_cli",
            base_url=GATEWAY_URL,
            api_key="sk-good",
            model="anthropic/claude-sonnet-4.6",
        )
        bot_other_backend = BotConfig(
            name="codex-local",
            backend="codex",
            base_url=None,
            api_key="",
            model="",
        )
        bot_empty_key = BotConfig(
            name="bad",
            backend="pi_cli",
            base_url=GATEWAY_URL,
            api_key="",
            model="anthropic/claude-bad",
        )
        bot_default_base = BotConfig(
            name="default-bot",
            backend="pi_cli",
            base_url=DEFAULT_BOT_BASE_URL,
            api_key="sk-default",
            model="google/gemini-2.5-pro",
        )

        fake_vm = Mock(vm_name="ssh:user@host:22", api_token="fake-key")
        fake_vm.work_dir = "/repo"

        client = _ModelsJsonClient(existing=None)

        with patch("agent.pi_models.bot_service.list_configs",
                   return_value=[bot_good, bot_other_backend, bot_empty_key, bot_default_base]):
            with patch("agent.config.resolve_vm_config", return_value=fake_vm):
                with patch("agent.pi_models._parse_ssh_target",
                           return_value=("user", "host", 22)):
                    with patch("paramiko.Ed25519Key.from_private_key"):
                        with patch("paramiko.SSHClient") as mock_ssh:
                            mock_ssh.return_value = client
                            sync_pi_models(1)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        # Only the pi_cli bot with custom base_url + good key got rebuilt
        self.assertIn("y-kimi", providers)
        self.assertEqual(providers["y-kimi"]["apiKey"], "sk-good")
        # Non-pi_cli bots are skipped
        self.assertNotIn("y-codex-local", providers)
        # Empty-key pi_cli bot: resolved to custom provider (custom base_url),
        # but then filtered by _write_pi_models_json empty-apiKey guard
        self.assertNotIn("y-bad", providers)
        # Default-base_url pi_cli bot uses passthrough, no custom provider
        self.assertNotIn("y-default-bot", providers)

    def test_sync_swallows_ssh_error(self):
        """SSH errors are best-effort swallowed."""
        bot_good = BotConfig(
            name="kimi",
            backend="pi_cli",
            base_url=GATEWAY_URL,
            api_key="sk-good",
            model="anthropic/claude-sonnet-4.6",
        )
        fake_vm = Mock(vm_name="ssh:user@host:22", api_token="fake-key")
        fake_vm.work_dir = "/repo"

        with patch("agent.pi_models.bot_service.list_configs", return_value=[bot_good]):
            with patch("agent.config.resolve_vm_config", return_value=fake_vm):
                with patch("agent.pi_models._parse_ssh_target",
                           return_value=("user", "host", 22)):
                    with patch("paramiko.Ed25519Key.from_private_key"):
                        with patch("paramiko.SSHClient") as mock_ssh:
                            mock_ssh_instance = Mock()
                            mock_ssh_instance.connect = Mock(
                                side_effect=Exception("Connection refused"))
                            mock_ssh.return_value = mock_ssh_instance
                            # Should not raise
                            sync_pi_models(1, ssh_client=None)

    def test_sync_reuses_passed_ssh_client(self):
        """When ssh_client is passed, no new SSH connection is made."""
        bot_good = BotConfig(
            name="kimi",
            backend="pi_cli",
            base_url=GATEWAY_URL,
            api_key="sk-good",
            model="anthropic/claude-sonnet-4.6",
        )

        client = _ModelsJsonClient(existing=None)

        with patch("agent.pi_models.bot_service.list_configs", return_value=[bot_good]):
            with patch("agent.config.resolve_vm_config", return_value=Mock(vm_name="ssh:user@host:22", api_token="key")):
                sync_pi_models(1, ssh_client=client)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]
        self.assertIn("y-kimi", providers)

    def test_sync_no_vm_config_is_noop(self):
        """When there is no default VM config, sync returns without error."""
        with patch("agent.pi_models.bot_service.list_configs", return_value=[]):
            with patch("agent.config.resolve_vm_config", return_value=Mock(vm_name="", api_token="")):
                # Should not raise
                sync_pi_models(1)


class Regression2376Test(unittest.TestCase):
    """Regression for todo 2376: empty-apiKey bot must not poison models.json."""

    def test_empty_key_bot_does_not_trigger_schema_error(self):
        """A pi_cli bot with empty api_key (like the glm config that caused 2376)
        must not appear in models.json — otherwise pi --list-models would reject
        the whole file with 'apiKey must not have fewer than 1 characters'."""
        bot_good = BotConfig(
            name="kimi",
            backend="pi_cli",
            base_url=GATEWAY_URL,
            api_key="sk-good",
            model="anthropic/claude-sonnet-4.6",
        )
        bot_poison = BotConfig(
            name="glm",
            backend="pi_cli",
            base_url=GATEWAY_URL,
            api_key="",  # the 2376 poison value
            model="google/gemini-2.5-pro",
        )

        fake_vm = Mock(vm_name="ssh:user@host:22", api_token="fake-key")
        fake_vm.work_dir = "/repo"
        client = _ModelsJsonClient(existing=None)

        with patch("agent.pi_models.bot_service.list_configs",
                   return_value=[bot_good, bot_poison]):
            with patch("agent.config.resolve_vm_config", return_value=fake_vm):
                with patch("agent.pi_models._parse_ssh_target",
                           return_value=("user", "host", 22)):
                    with patch("paramiko.Ed25519Key.from_private_key"):
                        with patch("paramiko.SSHClient") as mock_ssh:
                            mock_ssh.return_value = client
                            sync_pi_models(1)

        written = json.loads(client.writes["/home/roy/.pi/agent/models.json"])
        providers = written["providers"]

        # Poison bot is absent
        self.assertNotIn("y-glm", providers)
        # Good bot is still there
        self.assertIn("y-kimi", providers)
        # No provider in the file has an empty apiKey, so pi schema is valid
        for name, provider in providers.items():
            self.assertTrue(
                bool(provider.get("apiKey")),
                f"provider '{name}' has empty/falsy apiKey: {provider.get('apiKey')!r}",
            )


if __name__ == "__main__":
    unittest.main()
