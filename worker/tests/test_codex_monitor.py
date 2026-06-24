import unittest
from unittest.mock import Mock, patch

from worker.monitor import _restart_codex_with_steer

RELAY_URL = "https://cc1.yovy.app/openai"

PROVIDER_ARGS = [
    "-c", 'model_provider="y-codex"',
    "-c", 'model_providers.y-codex.name="y-codex"',
    "-c", f'model_providers.y-codex.base_url="{RELAY_URL}"',
    "-c", 'model_providers.y-codex.wire_api="responses"',
    "-c", 'model_providers.y-codex.env_key="OPENAI_API_KEY"',
]


class CodexSteerTest(unittest.IsolatedAsyncioTestCase):
    async def _run_steer(self, base_url):
        captured = {}

        async def fake_start(**kwargs):
            captured.update(kwargs)
            return "thread-1"

        bot_config = Mock()
        bot_config.name = "codex2"
        bot_config.model = "gpt-5.5"
        bot_config.api_key = "cr_x"
        bot_config.base_url = base_url

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock(name="vm")),
            patch("agent.config.resolve_bot_config", return_value=bot_config),
            patch("agent.codex.start_detached_codex_ssh", side_effect=fake_start) as start,
            patch("worker.monitor.update_process_offset"),
            patch("worker.monitor.release_lease"),
        ):
            await _restart_codex_with_steer(
                "chat-1",
                {"user_id": 1, "vm_name": "vm", "work_dir": "/repo", "backend_type": "codex"},
                {"status": "steer", "steer_text": "do more", "thread_id": "thread-1"},
            )

        start.assert_awaited_once()
        return captured

    async def test_steer_restart_keeps_provider_flags_when_base_url_set(self):
        captured = await self._run_steer(RELAY_URL)
        self.assertEqual(
            captured["cmd"],
            ["codex", "exec", "resume", "thread-1", "--json",
             "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-5.5", *PROVIDER_ARGS],
        )
        self.assertEqual(captured["prompt"], "do more")

    async def test_steer_restart_omits_provider_flags_when_base_url_empty(self):
        captured = await self._run_steer("")
        self.assertEqual(
            captured["cmd"],
            ["codex", "exec", "resume", "thread-1", "--json",
             "--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-5.5"],
        )
        self.assertNotIn('model_provider="y-codex"', captured["cmd"])


if __name__ == "__main__":
    unittest.main()
