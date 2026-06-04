import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import (
    _build_pi_params,
    build_pi_env,
    build_pi_models_provider,
    build_pi_resume_cmd,
    resolve_pi_model_and_provider,
)

GATEWAY_URL = "https://gateway.ai.cloudflare.com/v1/acct/luohy15/openrouter"


def _message(role: str, content: str, msg_id: str) -> Message:
    return Message(
        id=msg_id,
        role=role,
        content=content,
        timestamp=get_utc_iso8601_timestamp(),
        unix_timestamp=get_unix_timestamp(),
    )


def _image_message(role: str, content: str, msg_id: str, images: list) -> Message:
    msg = _message(role, content, msg_id)
    msg.images = images
    return msg


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


class PiRunnerTest(unittest.TestCase):
    def test_resume_cmd_uses_session_model_and_key(self):
        self.assertEqual(
            build_pi_resume_cmd("session-1", "google/gemini-2.5-pro", "secret"),
            ["pi", "-p", "--mode", "json", "--session", "session-1",
             "--model", "google/gemini-2.5-pro", "--api-key", "secret"],
        )

    def test_resume_cmd_without_key(self):
        self.assertEqual(
            build_pi_resume_cmd("session-1", "google/gemini-2.5-pro"),
            ["pi", "-p", "--mode", "json", "--session", "session-1",
             "--model", "google/gemini-2.5-pro"],
        )

    def test_env_maps_trace_not_api_key(self):
        env = build_pi_env(
            BotConfig(name="pi", backend="pi_cli", api_key="secret"),
            chat_id="chat-1",
            trace_id="2312",
            topic="dev",
            last_message_id="m1",
        )

        # pi auth goes via --api-key on the cmd, not env
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertEqual(env["Y_CHAT_ID"], "chat-1")
        self.assertEqual(env["Y_TRACE_ID"], "2312")
        self.assertEqual(env["Y_TOPIC"], "dev")
        self.assertEqual(env["Y_MESSAGE_ID"], "m1")

    def test_build_params_fresh_run(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_pi_params(
                _chat(skill="impl"),
                "chat-1",
                1,
                BotConfig(name="pi", backend="pi_cli", model='"google/gemini-2.5-pro"', api_key="secret"),
                trace_id="2312",
                topic="dev",
            )

        self.assertEqual(
            params["cmd"],
            ["pi", "-p", "--mode", "json", "--model", "google/gemini-2.5-pro", "--api-key", "secret"],
        )
        self.assertIn("load the 'impl' skill", params["prompt"])
        self.assertTrue(params["prompt"].endswith("hello"))
        self.assertFalse(params["resume"])
        self.assertIsNone(params["session_id"])

    def test_build_params_carries_image_paths(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        chat = _chat()
        chat.messages = [_image_message("user", "what is this?", "m1", ["/Users/roy/luohy15/assets/images/a.jpg"])]
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_pi_params(
                chat,
                "chat-1",
                1,
                BotConfig(name="pi", backend="pi_cli"),
            )

        self.assertEqual(params["images"], ["/Users/roy/luohy15/assets/images/a.jpg"])
        self.assertEqual(params["prompt"], "what is this?")

    def test_build_params_resume_only_when_work_dir_matches(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_pi_params(
                _chat(external_id="session-1", work_dir="/repo"),
                "chat-1",
                1,
                BotConfig(name="pi", backend="pi_cli", model="google/gemini-2.5-flash", api_key="secret"),
            )

        self.assertEqual(
            params["cmd"],
            ["pi", "-p", "--mode", "json", "--session", "session-1",
             "--model", "google/gemini-2.5-flash", "--api-key", "secret"],
        )
        self.assertTrue(params["resume"])
        self.assertEqual(params["session_id"], "session-1")


class PiBaseUrlTest(unittest.TestCase):
    def test_models_provider_built_from_bot_config(self):
        name, provider = build_pi_models_provider(
            BotConfig(name="pi", backend="pi_cli", base_url=GATEWAY_URL,
                      api_key="sk-or-x", model='"anthropic/claude-sonnet-4.6"')
        )
        self.assertEqual(name, "y-pi")
        self.assertEqual(provider["baseUrl"], GATEWAY_URL)
        self.assertEqual(provider["api"], "anthropic-messages")
        self.assertEqual(provider["apiKey"], "sk-or-x")
        # OpenRouter-routed bot with no explicit openrouter_config defaults to
        # throughput, so the model id carries the `:nitro` shorthand.
        self.assertTrue(provider["models"][0]["id"].endswith(":nitro"))
        self.assertEqual(provider["models"][0]["id"], "anthropic/claude-sonnet-4.6:nitro")
        self.assertEqual(provider["models"][0]["name"], "anthropic/claude-sonnet-4.6")

    def test_models_provider_nitro_is_idempotent(self):
        _, provider = build_pi_models_provider(
            BotConfig(name="pi", backend="pi_cli", base_url=GATEWAY_URL,
                      api_key="sk-or-x", model="anthropic/claude-sonnet-4.6:nitro")
        )
        # Already-suffixed model id must not gain a second `:nitro`.
        self.assertEqual(provider["models"][0]["id"], "anthropic/claude-sonnet-4.6:nitro")

    def test_models_provider_no_nitro_when_throughput_disabled(self):
        # Explicit non-throughput openrouter_config opts out of the `:nitro` slug.
        _, provider = build_pi_models_provider(
            BotConfig(name="pi", backend="pi_cli", base_url=GATEWAY_URL,
                      api_key="sk-or-x", model="anthropic/claude-sonnet-4.6",
                      openrouter_config={"provider": {"sort": "price"}})
        )
        self.assertEqual(provider["models"][0]["id"], "anthropic/claude-sonnet-4.6")

    def test_resolve_with_base_url_namespaces_model(self):
        model, provider = resolve_pi_model_and_provider(
            BotConfig(name="pi", base_url=GATEWAY_URL, api_key="sk-or-x"),
            "anthropic/claude-sonnet-4.6",
        )
        # Throughput default adds `:nitro`, and the --model reference stays in sync
        # with the models.json id.
        self.assertEqual(model, "y-pi/anthropic/claude-sonnet-4.6:nitro")
        self.assertIn("y-pi", provider)

    def test_resolve_with_default_base_url_is_passthrough(self):
        # BotConfig defaults base_url to the stock OpenRouter endpoint; that must
        # keep the v1 provider-prefix behavior, not register a custom provider.
        model, provider = resolve_pi_model_and_provider(
            BotConfig(name="pi"), "google/gemini-2.5-pro"
        )
        self.assertEqual(model, "google/gemini-2.5-pro")
        self.assertIsNone(provider)

    def test_build_params_with_base_url_drops_api_key_flag(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_pi_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="pi", backend="pi_cli", base_url=GATEWAY_URL,
                          api_key="sk-or-x", model="anthropic/claude-sonnet-4.6"),
            )

        self.assertEqual(
            params["cmd"],
            ["pi", "-p", "--mode", "json", "--model", "y-pi/anthropic/claude-sonnet-4.6:nitro"],
        )
        self.assertNotIn("--api-key", params["cmd"])
        self.assertIn("y-pi", params["models_provider"])

    def test_build_params_resume_with_base_url(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_pi_params(
                _chat(external_id="session-1", work_dir="/repo"),
                "chat-1",
                1,
                BotConfig(name="pi", backend="pi_cli", base_url=GATEWAY_URL,
                          api_key="sk-or-x", model="anthropic/claude-sonnet-4.6"),
            )

        self.assertEqual(
            params["cmd"],
            ["pi", "-p", "--mode", "json", "--session", "session-1",
             "--model", "y-pi/anthropic/claude-sonnet-4.6:nitro"],
        )
        self.assertIn("y-pi", params["models_provider"])

    def test_build_params_without_base_url_unchanged(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_pi_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(name="pi", backend="pi_cli", model="google/gemini-2.5-pro", api_key="secret"),
            )

        self.assertEqual(
            params["cmd"],
            ["pi", "-p", "--mode", "json", "--model", "google/gemini-2.5-pro", "--api-key", "secret"],
        )
        self.assertIsNone(params["models_provider"])


if __name__ == "__main__":
    unittest.main()
