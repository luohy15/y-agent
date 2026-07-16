import unittest
import uuid
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import (
    _build_grok_params,
    build_grok_env,
    build_grok_resume_cmd,
)


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


class GrokRunnerTest(unittest.TestCase):
    def test_resume_cmd_uses_session_and_model(self):
        self.assertEqual(
            build_grok_resume_cmd("session-1", "grok-4.5"),
            ["grok", "--resume", "session-1", "--output-format", "streaming-json", "--always-approve", "-m", "grok-4.5"],
        )

    def test_env_maps_api_key_and_trace(self):
        env = build_grok_env(
            BotConfig(name="grok", backend="grok_build", api_key="secret"),
            chat_id="chat-1",
            trace_id="2734",
            topic="dev",
            last_message_id="m1",
        )

        self.assertEqual(env["XAI_API_KEY"], "secret")
        self.assertEqual(env["Y_CHAT_ID"], "chat-1")
        self.assertEqual(env["Y_TRACE_ID"], "2734")
        self.assertEqual(env["Y_TOPIC"], "dev")
        self.assertEqual(env["Y_MESSAGE_ID"], "m1")

    def test_build_params_uses_relay_alias_for_custom_base_url(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_grok_params(
                _chat(),
                "chat-1",
                1,
                BotConfig(
                    name="grok",
                    backend="grok_build",
                    model="grok-4.5",
                    base_url="https://cc1.yovy.app/openai",
                    api_key="secret",
                ),
            )

        self.assertEqual(params["cmd"][:4], ["grok", "--output-format", "streaming-json", "--always-approve"])
        self.assertEqual(params["cmd"][4], "-s")
        uuid.UUID(params["cmd"][5])  # a fresh run assigns a valid session UUID up front
        self.assertEqual(params["cmd"][6:], ["-m", "y-grok"])
        self.assertEqual(params["session_id"], params["cmd"][5])
        self.assertNotIn("GROK_BASE_URL", params["env"])

    def test_build_params_fresh_run(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_grok_params(
                _chat(skill="impl"),
                "chat-1",
                1,
                BotConfig(name="grok", backend="grok_build", model='"grok-4.5"', api_key="secret"),
                trace_id="2734",
                topic="dev",
            )

        self.assertEqual(params["cmd"][:4], ["grok", "--output-format", "streaming-json", "--always-approve"])
        self.assertEqual(params["cmd"][4], "-s")
        uuid.UUID(params["cmd"][5])  # a fresh run assigns a valid session UUID up front (todo 2813)
        self.assertEqual(params["cmd"][6:], ["-m", "grok-4.5"])
        self.assertIn("load the 'impl' skill", params["prompt"])
        self.assertTrue(params["prompt"].endswith("hello"))
        self.assertFalse(params["resume"])
        self.assertEqual(params["session_id"], params["cmd"][5])

    def test_build_params_carries_image_paths(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        chat = _chat()
        chat.messages = [_image_message("user", "what is this?", "m1", ["/Users/roy/luohy15/assets/images/a.jpg"])]
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_grok_params(
                chat,
                "chat-1",
                1,
                BotConfig(name="grok", backend="grok_build"),
            )

        self.assertEqual(params["images"], ["/Users/roy/luohy15/assets/images/a.jpg"])
        self.assertEqual(params["prompt"], "what is this?")

    def test_build_params_resume_only_when_work_dir_matches(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_grok_params(
                _chat(external_id="session-1", work_dir="/repo"),
                "chat-1",
                1,
                BotConfig(name="grok", backend="grok_build", model="grok-4.5"),
            )

        self.assertEqual(
            params["cmd"],
            ["grok", "--resume", "session-1", "--output-format", "streaming-json", "--always-approve", "-m", "grok-4.5"],
        )
        self.assertTrue(params["resume"])
        self.assertEqual(params["session_id"], "session-1")


if __name__ == "__main__":
    unittest.main()
