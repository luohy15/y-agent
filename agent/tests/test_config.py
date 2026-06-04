import unittest
from unittest.mock import patch

from agent.config import (
    resolve_bot_config,
    tier_of,
    _bots_for_tier,
    _pick_by_weight,
    _pick_uniform,
    SKILL_TO_TIER,
    TIER_FALLBACK_PRICES,
)
from storage.entity.dto import BotConfig


class TierOfTest(unittest.TestCase):
    def test_explicit_tier0(self):
        bot = BotConfig(name="t0", tier="tier0")
        self.assertEqual(tier_of(bot), "tier0")

    def test_explicit_tier1(self):
        bot = BotConfig(name="t1", tier="tier1")
        self.assertEqual(tier_of(bot), "tier1")

    def test_explicit_tier2(self):
        bot = BotConfig(name="t2", tier="tier2")
        self.assertEqual(tier_of(bot), "tier2")

    def test_none_defaults_tier1(self):
        bot = BotConfig(name="none")
        self.assertEqual(tier_of(bot), "tier1")

    def test_empty_string_defaults_tier1(self):
        bot = BotConfig(name="empty", tier="")
        self.assertEqual(tier_of(bot), "tier1")


class SkillToTierDictTest(unittest.TestCase):
    def test_tier2_allowlist(self):
        for skill in ("journal", "link", "note", "image", "format-zh"):
            self.assertEqual(SKILL_TO_TIER.get(skill), "tier2")

    def test_unlisted_returns_none_from_dict(self):
        self.assertIsNone(SKILL_TO_TIER.get("plan"))
        self.assertIsNone(SKILL_TO_TIER.get("impl"))
        self.assertIsNone(SKILL_TO_TIER.get("nonexistent-skill"))

    def test_get_with_or_returns_tier1(self):
        self.assertEqual(SKILL_TO_TIER.get("plan") or "tier1", "tier1")
        self.assertEqual(SKILL_TO_TIER.get("journal") or "tier1", "tier2")

    def test_tier0_set_is_empty(self):
        self.assertNotIn("exam", SKILL_TO_TIER)
        self.assertNotIn("manager", SKILL_TO_TIER)


class PickByWeightTest(unittest.TestCase):
    def test_inverse_square_weights(self):
        cheap = BotConfig(name="cheap", base_url="https://openrouter.ai/api/v1", model="cheap-model")
        mid = BotConfig(name="mid", base_url="https://openrouter.ai/api/v1", model="mid-model")
        bots = [(cheap, 1.0), (mid, 2.0)]

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [cheap]
            result = _pick_by_weight(bots, 1.0)

        self.assertEqual(result.name, "cheap")
        mock_choices.assert_called_once()
        _, kwargs = mock_choices.call_args
        weights = kwargs["weights"]
        self.assertAlmostEqual(weights[0], 1.0 / (1.0 ** 2))
        self.assertAlmostEqual(weights[1], 1.0 / (2.0 ** 2))

    def test_priceless_uses_fallback(self):
        priceless = BotConfig(name="priceless", base_url="https://relay.example.com", model="relay")
        bots = [(priceless, None)]

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [priceless]
            result = _pick_by_weight(bots, fallback_price=5.0)

        self.assertEqual(result.name, "priceless")
        _, kwargs = mock_choices.call_args
        self.assertAlmostEqual(kwargs["weights"][0], 1.0 / (5.0 ** 2))

    def test_zero_price_uses_fallback(self):
        bot = BotConfig(name="zero", base_url="https://openrouter.ai/api/v1", model="zero-model")
        bots = [(bot, 0.0)]

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [bot]
            _pick_by_weight(bots, fallback_price=3.0)

        _, kwargs = mock_choices.call_args
        self.assertAlmostEqual(kwargs["weights"][0], 1.0 / (3.0 ** 2))

    def test_empty_list_returns_none(self):
        self.assertIsNone(_pick_by_weight([], 1.0))


class PickUniformTest(unittest.TestCase):
    def test_uniform_selection(self):
        a = BotConfig(name="a")
        b = BotConfig(name="b")
        bots = [(a, 3.0), (b, 1.0)]

        with patch("agent.config.random.choice") as mock_choice:
            mock_choice.return_value = a
            result = _pick_uniform(bots)

        self.assertEqual(result.name, "a")
        mock_choice.assert_called_once()
        args = mock_choice.call_args[0][0]
        self.assertEqual(len(args), 2)

    def test_empty_list_returns_none(self):
        self.assertIsNone(_pick_uniform([]))


class BotsForTierTest(unittest.TestCase):
    def test_filters_by_tier(self):
        configs = [
            BotConfig(name="t0", tier="tier0"),
            BotConfig(name="t1", tier="tier1"),
            BotConfig(name="t2", tier="tier2"),
            BotConfig(name="none"),  # defaults tier1
        ]
        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.bot_prices_per_1m", return_value=(None, None)),
        ):
            t0_bots = _bots_for_tier(1, "tier0", {})
            t1_bots = _bots_for_tier(1, "tier1", {})
            t2_bots = _bots_for_tier(1, "tier2", {})

        self.assertEqual(len(t0_bots), 1)
        self.assertEqual(t0_bots[0][0].name, "t0")

        self.assertEqual(len(t1_bots), 2)
        names = [b[0].name for b in t1_bots]
        self.assertIn("t1", names)
        self.assertIn("none", names)

        self.assertEqual(len(t2_bots), 1)
        self.assertEqual(t2_bots[0][0].name, "t2")

    def test_excludes_perplexity(self):
        configs = [
            BotConfig(name="px", backend="perplexity", tier="tier1"),
            BotConfig(name="normal", tier="tier1"),
        ]
        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.bot_prices_per_1m", return_value=(None, None)),
        ):
            t1_bots = _bots_for_tier(1, "tier1", {})

        self.assertEqual(len(t1_bots), 1)
        self.assertEqual(t1_bots[0][0].name, "normal")

    def test_price_queried_once_per_bot(self):
        configs = [
            BotConfig(name="a", tier="tier1", base_url="https://openrouter.ai/api/v1", model="a-model"),
        ]
        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.bot_prices_per_1m") as mock_prices,
        ):
            mock_prices.return_value = (2.0, 4.0)
            _bots_for_tier(1, "tier1", {})

        # tier_of now reads cfg.tier, not price -> bot_prices_per_1m called once (for weighting)
        self.assertEqual(mock_prices.call_count, 1)


class ResolveBotConfigTierTest(unittest.TestCase):
    def test_backend_pin_ignores_tier(self):
        configs = [
            BotConfig(name="default", backend="codex", model="gpt-5.4"),
            BotConfig(name="claude_code", backend="claude_code", model="sonnet"),
        ]
        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code", tier="tier2")
        self.assertEqual(config.name, "claude_code")

    def test_bot_name_pin_ignores_tier(self):
        pinned = BotConfig(name="pinned", backend="claude_code")
        with (
            patch("agent.config.bot_service.get_config", return_value=pinned),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.random.choice") as mock_choice,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="pinned", tier="tier2")
        self.assertEqual(config.name, "pinned")
        mock_choices.assert_not_called()
        mock_choice.assert_not_called()

    def test_bot_name_not_found_fallback_to_default(self):
        """Original path preserved: bot_name not found -> default, no cross-user."""
        default_config = BotConfig(name="default", backend="codex")

        def _get_side_effect(uid, name="default"):
            if name == "pinned":
                return None
            return default_config

        with (
            patch("agent.config.bot_service.get_config", side_effect=_get_side_effect),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="pinned")

        self.assertEqual(config.name, "default")

    def test_tier0_uniform_random(self):
        a = BotConfig(name="a", tier="tier0")
        b = BotConfig(name="b", tier="tier0")
        configs = [a, b]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.fetch_openrouter_catalog", return_value={"stub": True}),
            patch("agent.config.bot_pricing.bot_prices_per_1m", return_value=(None, None)),
            patch("agent.config.random.choice") as mock_choice,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choice.return_value = a
            config = resolve_bot_config(1, tier="tier0")

        self.assertEqual(config.name, "a")
        mock_choice.assert_called_once()

    def test_tier1_selects_weighted_random(self):
        bot_a = BotConfig(name="bot-a", tier="tier1", base_url="https://openrouter.ai/api/v1", model="a-model")
        bot_b = BotConfig(name="bot-b", tier="tier1", base_url="https://openrouter.ai/api/v1", model="b-model")
        configs = [bot_a, bot_b]

        def _price_side_effect(cfg, _cat):
            if cfg.model == "a-model":
                return 3.0, 6.0
            if cfg.model == "b-model":
                return 5.0, 10.0
            return None, None

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.fetch_openrouter_catalog", return_value={"stub": True}),
            patch("agent.config.bot_pricing.bot_prices_per_1m", side_effect=_price_side_effect),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [bot_a]
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "bot-a")
        mock_choices.assert_called_once()
        _, kwargs = mock_choices.call_args
        weights = kwargs["weights"]
        self.assertAlmostEqual(weights[0], 1.0 / 9.0)
        self.assertAlmostEqual(weights[1], 1.0 / 25.0)

    def test_tier2_selects_weighted_random(self):
        bot_c = BotConfig(name="bot-c", tier="tier2", base_url="https://openrouter.ai/api/v1", model="c-model")
        configs = [bot_c]

        def _price_side_effect(cfg, _cat):
            if cfg.model == "c-model":
                return 1.0, 2.0
            return None, None

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.fetch_openrouter_catalog", return_value={"stub": True}),
            patch("agent.config.bot_pricing.bot_prices_per_1m", side_effect=_price_side_effect),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [bot_c]
            config = resolve_bot_config(1, tier="tier2")

        self.assertEqual(config.name, "bot-c")
        _, kwargs = mock_choices.call_args
        self.assertAlmostEqual(kwargs["weights"][0], 1.0 / 1.0)

    def test_tier_falls_back_to_default_when_empty(self):
        default = BotConfig(name="default", backend="codex", model="gpt-5.4")
        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.bot_pricing.fetch_openrouter_catalog", return_value={"stub": True}),
            patch("agent.config.bot_service.get_config", return_value=default),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, tier="tier1")
        self.assertEqual(config.name, "default")

    def test_perplexity_excluded_from_tier_pools(self):
        px = BotConfig(name="px", backend="perplexity", tier="tier1")
        normal = BotConfig(name="regular", tier="tier1")
        configs = [px, normal]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing.fetch_openrouter_catalog", return_value={"stub": True}),
            patch("agent.config.bot_pricing.bot_prices_per_1m", return_value=(None, None)),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [normal]
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "regular")
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("px", names)

    def test_without_tier_preserves_default_resolution(self):
        default_config = BotConfig(name="default", backend="codex", model="gpt-5.4")
        with patch("agent.config.bot_service.get_config", return_value=default_config):
            config = resolve_bot_config(1)
        self.assertEqual(config.name, "default")

    def test_fetch_catalog_stubbed_in_tier_path(self):
        """Tier path should not hit the real network; catalog is stubbed/passed."""
        cfg = BotConfig(name="x", tier="tier1", base_url="https://openrouter.ai/api/v1", model="x")
        with (
            patch("agent.config.bot_service.list_configs", return_value=[cfg]),
            patch("agent.config.bot_pricing.fetch_openrouter_catalog", return_value={"stub": True}) as mock_fetch,
            patch("agent.config.bot_pricing.bot_prices_per_1m", return_value=(2.0, 4.0)),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [cfg]
            resolve_bot_config(1, tier="tier1")

        mock_fetch.assert_called_once()


class ResolveBotConfigOriginalTest(unittest.TestCase):
    """Original tests preserved to guard against regressions."""

    def test_without_backend_preserves_default_resolution(self):
        default_config = BotConfig(name="default", backend="codex", model="gpt-5.4")
        with patch("agent.config.bot_service.get_config", return_value=default_config):
            config = resolve_bot_config(1)
        self.assertEqual(config.name, "default")
        self.assertEqual(config.backend, "codex")
        self.assertEqual(config.model, "gpt-5.4")

    def test_backend_identity_ignores_mismatched_default_config(self):
        configs = [
            BotConfig(name="default", backend="codex", model="gpt-5.4"),
            BotConfig(name="claude_code", backend="claude_code", model="sonnet"),
        ]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code")

        self.assertEqual(config.name, "claude_code")
        self.assertEqual(config.backend, "claude_code")
        self.assertEqual(config.model, "sonnet")

    def test_backend_only_fallback_does_not_reuse_mismatched_model(self):
        configs = [
            BotConfig(name="default", backend="codex", model="gpt-5.4"),
        ]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code")

        self.assertEqual(config.name, "default")
        self.assertEqual(config.backend, "claude_code")
        self.assertEqual(config.model, "")


if __name__ == "__main__":
    unittest.main()
