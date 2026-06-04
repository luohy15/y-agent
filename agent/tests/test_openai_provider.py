import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.openai_chat import _provider_payload, openai_chat_completion
from storage.entity.dto import BotConfig

GATEWAY_URL = "https://gateway.ai.cloudflare.com/v1/acct/luohy15/openrouter"


class ProviderPayloadTest(unittest.TestCase):
    def test_explicit_config_passthrough(self):
        bot = BotConfig(name="tldr", base_url=GATEWAY_URL, api_key="sk-or-x",
                        openrouter_config={"provider": {"sort": "price"}})
        self.assertEqual(_provider_payload(bot), {"sort": "price"})

    def test_openrouter_routed_defaults_to_throughput(self):
        bot = BotConfig(name="tldr", base_url=GATEWAY_URL, api_key="sk-or-x")
        self.assertEqual(_provider_payload(bot), {"sort": "throughput"})

    def test_non_openrouter_has_no_provider(self):
        bot = BotConfig(name="local", base_url="https://api.example.com/v1", api_key="key")
        self.assertIsNone(_provider_payload(bot))


class ChatCompletionPayloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_config_openrouter_bot_payload_has_throughput_provider(self):
        bot = BotConfig(name="tldr", base_url=GATEWAY_URL, api_key="sk-or-x",
                        model="anthropic/claude-sonnet-4.6")

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(
            return_value={"choices": [{"message": {"content": "hi"}}], "usage": {}}
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)

        with patch("agent.openai_chat.httpx.AsyncClient", return_value=client):
            await openai_chat_completion([{"role": "user", "content": "hello"}], bot)

        sent_payload = client.post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["provider"], {"sort": "throughput"})


if __name__ == "__main__":
    unittest.main()
