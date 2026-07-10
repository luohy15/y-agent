"""Unit tests for the `y chat` dispatch (send) path trace-flag wiring in
cli/commands/chat/click.py.

Asserts the JSON payload posted to /api/chat/notify for the cross-session
contract: trace_id / from_topic / from_chat_id inclusion, the Y_CHAT_ID env
fallback for from_chat_id, --new -> force_new, and topic/skill/chat-id
targeting. Mirrors the CliRunner + payload-assert style of test_chat_send_image.
"""

import unittest
from unittest.mock import patch

from click.testing import CliRunner

from yagent.commands.chat.click import chat_group


def _invoke(args, env=None):
    # Clear Y_CHAT_ID by default (click drops env keys whose value is None) so a
    # caller's ambient Y_CHAT_ID doesn't leak into the no-fallback assertions.
    full_env = {"Y_CHAT_ID": None}
    if env:
        full_env.update(env)
    with patch("yagent.commands.chat.click.api_request") as api_request:
        api_request.return_value.json.return_value = {"chat_id": "abc123"}
        result = CliRunner().invoke(chat_group, ["-m", "hello", *args], env=full_env)
    return result, api_request


class ChatSendTraceFlagsCliTest(unittest.TestCase):
    def test_defaults_force_new_false_and_from_topic_manager(self):
        result, api_request = _invoke([])
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["message"], "hello")
        self.assertEqual(payload["force_new"], False)
        self.assertEqual(payload["from_topic"], "manager")
        # Absent optional targeting flags are omitted, not sent as None.
        for key in ("topic", "skill", "chat_id", "trace_id", "work_dir", "from_chat_id", "bot_name", "bot_tier", "reasoning_effort"):
            self.assertNotIn(key, payload)

    def test_trace_flags_included(self):
        result, api_request = _invoke([
            "--trace-id", "2484",
            "--from-topic", "dev",
            "--from-chat-id", "caller9",
            "--work-dir", "/tmp/wt",
        ])
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["trace_id"], "2484")
        self.assertEqual(payload["from_topic"], "dev")
        self.assertEqual(payload["from_chat_id"], "caller9")
        self.assertEqual(payload["work_dir"], "/tmp/wt")

    def test_y_chat_id_env_fallback_for_from_chat_id(self):
        result, api_request = _invoke([], env={"Y_CHAT_ID": "envchat"})
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["from_chat_id"], "envchat")

    def test_explicit_from_chat_id_overrides_env(self):
        result, api_request = _invoke(["--from-chat-id", "explicit"], env={"Y_CHAT_ID": "envchat"})
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["from_chat_id"], "explicit")

    def test_new_flag_sets_force_new(self):
        result, api_request = _invoke(["--new", "--topic", "dev"])
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["force_new"], True)

    def test_topic_and_skill_targeting(self):
        result, api_request = _invoke(["--topic", "dev", "--skill", "review"])
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["topic"], "dev")
        self.assertEqual(payload["skill"], "review")

    def test_chat_id_targeting(self):
        result, api_request = _invoke(["--chat-id", "c1"])
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "c1")

    def test_bot_and_tier_targeting(self):
        result, api_request = _invoke(["--bot", "codex", "--tier", "tier2"])
        self.assertEqual(result.exit_code, 0)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["bot_name"], "codex")
        self.assertEqual(payload["bot_tier"], "tier2")

    def test_reasoning_effort_is_sent_with_alias(self):
        result, api_request = _invoke(["--effort", "XHIGH"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(api_request.call_args.kwargs["json"]["reasoning_effort"], "xhigh")

    def test_posts_to_notify_endpoint_and_prints_chat_id(self):
        result, api_request = _invoke([])
        self.assertEqual(result.exit_code, 0)
        method, path = api_request.call_args.args[:2]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/chat/notify")
        self.assertIn("abc123", result.output)


if __name__ == "__main__":
    unittest.main()
