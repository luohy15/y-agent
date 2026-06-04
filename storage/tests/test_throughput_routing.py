import unittest

from storage.entity.dto import BotConfig, effective_openrouter_config, _throughput_enabled

GATEWAY_URL = "https://gateway.ai.cloudflare.com/v1/acct/luohy15/openrouter"


class ThroughputEnabledTest(unittest.TestCase):
    def test_explicit_throughput(self):
        bot = BotConfig(name="tldr", base_url=GATEWAY_URL, api_key="sk-or-x",
                        openrouter_config={"provider": {"sort": "throughput"}})
        self.assertTrue(_throughput_enabled(bot))

    def test_explicit_other_sort(self):
        bot = BotConfig(name="tldr", base_url=GATEWAY_URL, api_key="sk-or-x",
                        openrouter_config={"provider": {"sort": "price"}})
        self.assertFalse(_throughput_enabled(bot))

    def test_no_config_openrouter_routed_defaults_throughput(self):
        # Cloudflare gateway base_url + sk-or- key => OpenRouter-routed => default.
        bot = BotConfig(name="tldr", base_url=GATEWAY_URL, api_key="sk-or-x")
        self.assertTrue(_throughput_enabled(bot))
        self.assertEqual(effective_openrouter_config(bot), {"provider": {"sort": "throughput"}})

    def test_no_config_non_openrouter_is_off(self):
        bot = BotConfig(name="local", base_url="https://api.example.com/v1", api_key="key")
        self.assertFalse(_throughput_enabled(bot))
        self.assertIsNone(effective_openrouter_config(bot))


if __name__ == "__main__":
    unittest.main()
