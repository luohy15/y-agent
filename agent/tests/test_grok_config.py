import tomllib
import unittest

from storage.entity.dto import BotConfig

from agent.grok_config import build_grok_model_entry, merge_grok_config_toml


class GrokConfigTest(unittest.TestCase):
    def test_builds_responses_model_from_bot_config(self):
        alias, entry = build_grok_model_entry(
            BotConfig(
                name="grok",
                backend="grok_build",
                model='"grok-4.5"',
                base_url="https://cc1.yovy.app/openai",
            )
        )

        self.assertEqual(alias, "y-grok")
        self.assertEqual(entry["model"], "grok-4.5")
        self.assertEqual(entry["base_url"], "https://cc1.yovy.app/openai")
        self.assertEqual(entry["api_backend"], "responses")
        self.assertEqual(entry["env_key"], "XAI_API_KEY")

    def test_merges_relay_model_without_losing_existing_tables(self):
        existing = """[cli]\ninstaller = \"internal\"\n\n[[marketplace.sources]]\nname = \"xAI Official\"\ngit = \"https://example.com/plugins.git\"\n"""
        content = merge_grok_config_toml(
            existing,
            "y-grok",
            {
                "model": "grok-4.5",
                "base_url": "https://cc1.yovy.app/openai",
                "api_backend": "responses",
                "env_key": "XAI_API_KEY",
            },
        )

        data = tomllib.loads(content)
        self.assertEqual(data["cli"]["installer"], "internal")
        self.assertEqual(data["marketplace"]["sources"][0]["name"], "xAI Official")
        self.assertEqual(data["model"]["y-grok"]["base_url"], "https://cc1.yovy.app/openai")
        self.assertEqual(data["model"]["y-grok"]["env_key"], "XAI_API_KEY")


if __name__ == "__main__":
    unittest.main()
