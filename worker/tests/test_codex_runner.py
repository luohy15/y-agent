import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import (
    _build_codex_params,
    build_codex_env,
    build_codex_provider_args,
)

RELAY_URL = "https://cc1.yovy.app/openai"

PROVIDER_ARGS = [
    "-c", 'model_provider="y-codex"',
    "-c", 'model_providers.y-codex.name="y-codex"',
    "-c", f'model_providers.y-codex.base_url="{RELAY_URL}"',
    "-c", 'model_providers.y-codex.wire_api="responses"',
    "-c", 'model_providers.y-codex.env_key="OPENAI_API_KEY"',
]


def _message(role: str, content: str, msg_id: str) -> Message:
    return Message(
        id=msg_id,
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )


def _chat(external_id=None, work_dir="/repo", skill=None) -> Chat:
    return Chat(
        id="chat-1",
        create_time=get_utc_iso8601_timestamp(),
        update_time=get_utc_iso8601_timestamp(),
        messages=[_message("user", "hello", "m1")],
        external_id=external_id,
        work_dir=work_dir,
        skill=skill,
    )


class CodexProviderArgsTest(unittest.TestCase):
    def test_empty_base_url_returns_no_args(self):
        # Default codex bot (empty base_url) falls back to host config.toml.
        self.assertEqual(
            build_codex_provider_args(BotConfig(name="codex", backend="codex", api_key="cr_x")),
            [],
        )

    def test_base_url_returns_exact_provider_flags(self):
        self.assertEqual(
            build_codex_provider_args(
                BotConfig(name="codex2", backend="codex", base_url=RELAY_URL, api_key="cr_x")
            ),
            PROVIDER_ARGS,
        )

    def test_base_url_without_api_key_skips_injection(self):
        # base_url set but no credential -> skip (warn) and fall back to host config.
        self.assertEqual(
            build_codex_provider_args(
                BotConfig(name="codex3", backend="codex", base_url=RELAY_URL, api_key="")
            ),
            [],
        )


class CodexEnvTest(unittest.TestCase):
    def test_env_exports_openai_api_key_for_custom_provider(self):
        # env_key="OPENAI_API_KEY" reuses the key build_codex_env exports.
        env = build_codex_env(
            BotConfig(name="codex2", backend="codex", base_url=RELAY_URL, api_key="cr_x"),
            chat_id="chat-1",
            trace_id="2590",
            topic="dev",
            last_message_id="m1",
        )
        self.assertEqual(env["OPENAI_API_KEY"], "cr_x")
        self.assertEqual(env["Y_CHAT_ID"], "chat-1")
        self.assertEqual(env["Y_TRACE_ID"], "2590")


class CodexBuildParamsTest(unittest.TestCase):
    def test_fresh_cmd_includes_provider_flags_when_base_url_set(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_codex_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="codex2", backend="codex", base_url=RELAY_URL,
                          api_key="cr_x", model="gpt-5.5"),
            )
        self.assertEqual(
            params["cmd"],
            ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
             *PROVIDER_ARGS, "-C", "/repo", "-m", "gpt-5.5"],
        )
        self.assertFalse(params["resume"])

    def test_fresh_cmd_omits_provider_flags_when_base_url_empty(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_codex_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="codex", backend="codex", api_key="cr_x", model="gpt-5.5"),
            )
        self.assertEqual(
            params["cmd"],
            ["codex", "exec", "--json", "--dangerously-bypass-approvals-and-sandbox",
             "-C", "/repo", "-m", "gpt-5.5"],
        )
        self.assertNotIn('model_provider="y-codex"', params["cmd"])

    def test_resume_cmd_includes_provider_flags_when_base_url_set(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_codex_params(
                _chat(external_id="thread-1", work_dir="/repo"),
                "chat-1",
                1,
                BotConfig(name="codex2", backend="codex", base_url=RELAY_URL,
                          api_key="cr_x", model="gpt-5.5"),
            )
        self.assertEqual(
            params["cmd"],
            ["codex", "exec", "resume", "thread-1", "--json",
             "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-5.5", *PROVIDER_ARGS],
        )
        self.assertTrue(params["resume"])

    def test_resume_cmd_omits_provider_flags_when_base_url_empty(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_codex_params(
                _chat(external_id="thread-1", work_dir="/repo"),
                "chat-1",
                1,
                BotConfig(name="codex", backend="codex", api_key="cr_x", model="gpt-5.5"),
            )
        self.assertEqual(
            params["cmd"],
            ["codex", "exec", "resume", "thread-1", "--json",
             "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-5.5"],
        )
        self.assertNotIn('model_provider="y-codex"', params["cmd"])


if __name__ == "__main__":
    unittest.main()
