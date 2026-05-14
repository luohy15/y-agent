import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp
from worker.runner import (
    _build_gemini_params,
    build_gemini_env,
    build_gemini_resume_cmd,
)


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


class GeminiRunnerTest(unittest.TestCase):
    def test_resume_cmd_uses_session_and_model(self):
        self.assertEqual(
            build_gemini_resume_cmd("session-1", "gemini-2.5-pro"),
            ["gemini", "--resume", "session-1", "--output-format", "stream-json", "--yolo", "--skip-trust", "-m", "gemini-2.5-pro"],
        )

    def test_env_maps_api_key_and_trace(self):
        env = build_gemini_env(
            BotConfig(name="gemini", backend="gemini_cli", api_key="secret"),
            chat_id="chat-1",
            trace_id="2084",
            topic="dev",
            last_message_id="m1",
        )

        self.assertEqual(env["GEMINI_API_KEY"], "secret")
        self.assertEqual(env["Y_CHAT_ID"], "chat-1")
        self.assertEqual(env["Y_TRACE_ID"], "2084")
        self.assertEqual(env["Y_TOPIC"], "dev")
        self.assertEqual(env["Y_MESSAGE_ID"], "m1")

    def test_build_params_fresh_run(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_gemini_params(
                _chat(skill="impl"),
                "chat-1",
                1,
                BotConfig(name="gemini", backend="gemini_cli", model='"gemini-2.5-pro"', api_key="secret"),
                trace_id="2084",
                topic="dev",
            )

        self.assertEqual(params["cmd"], ["gemini", "--output-format", "stream-json", "--yolo", "--skip-trust", "-m", "gemini-2.5-pro"])
        self.assertIn("load the 'impl' skill", params["prompt"])
        self.assertTrue(params["prompt"].endswith("hello"))
        self.assertFalse(params["resume"])
        self.assertIsNone(params["session_id"])

    def test_build_params_resume_only_when_work_dir_matches(self):
        vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir="/repo")
        with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
            params = _build_gemini_params(
                _chat(external_id="session-1", work_dir="/repo"),
                "chat-1",
                1,
                BotConfig(name="gemini", backend="gemini_cli", model="gemini-2.5-flash"),
            )

        self.assertEqual(
            params["cmd"],
            ["gemini", "--resume", "session-1", "--output-format", "stream-json", "--yolo", "--skip-trust", "-m", "gemini-2.5-flash"],
        )
        self.assertTrue(params["resume"])
        self.assertEqual(params["session_id"], "session-1")


if __name__ == "__main__":
    unittest.main()
