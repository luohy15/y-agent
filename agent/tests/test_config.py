import unittest
from unittest.mock import patch

from agent.config import (
    resolve_bot_config,
    tier_of,
    derive_tier,
    _bots_for_tier,
    _pick_by_weight,
    _pick_uniform,
)
from storage.entity.dto import BotConfig


class TierOfTest(unittest.TestCase):
    def test_falsy_tier_defaults_tier3(self):
        # Only the default-fallback has logic worth pinning: a falsy `tier`
        # (absent → None, or stored empty string) resolves to tier3. Explicit
        # tier values are a plain field passthrough, not retested here.
        for value in (None, ""):
            with self.subTest(tier=value):
                self.assertEqual(tier_of(BotConfig(name="b", tier=value)), "tier3")


class DeriveTierTest(unittest.TestCase):
    def test_listed_skill_uses_skill_tier(self):
        self.assertEqual(derive_tier("git"), "tier2")

    def test_unlisted_skill_defaults_tier3(self):
        self.assertEqual(derive_tier("some-unmapped-skill"), "tier3")

    def test_no_skill_defaults_tier3(self):
        self.assertEqual(derive_tier(None), "tier3")

    def test_explicit_requested_tier_overrides_skill(self):
        self.assertEqual(derive_tier("git", "tier0"), "tier0")


class PickByWeightTest(unittest.TestCase):
    def test_route_weight_proportional(self):
        """route_weight ratios determine probability: a=1, b=1, c=3 → ~60% goes to c."""
        a = BotConfig(name="a", route_weight=1)
        b = BotConfig(name="b", route_weight=1)
        c = BotConfig(name="c", route_weight=3)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [c]
            result = _pick_by_weight([a, b, c])

        self.assertEqual(result.name, "c")
        mock_choices.assert_called_once()
        _, kwargs = mock_choices.call_args
        weights = kwargs["weights"]
        self.assertAlmostEqual(weights[0], 1.0 / 5.0)
        self.assertAlmostEqual(weights[1], 1.0 / 5.0)
        self.assertAlmostEqual(weights[2], 3.0 / 5.0)

    def test_weight_zero_excluded(self):
        """Bots with route_weight=0 are excluded from auto-routing."""
        active = BotConfig(name="active", route_weight=1)
        paused = BotConfig(name="paused", route_weight=0)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [active]
            result = _pick_by_weight([active, paused])

        self.assertEqual(result.name, "active")
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("paused", names)
        self.assertEqual(len(choices), 1)

    def test_weight_none_excluded(self):
        """Bots with route_weight=None are excluded (treated as unknown/0)."""
        active = BotConfig(name="active", route_weight=1)
        unknown = BotConfig(name="unknown", route_weight=None)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [active]
            result = _pick_by_weight([active, unknown])

        self.assertEqual(result.name, "active")
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("unknown", names)

    def test_weight_negative_excluded(self):
        """Bots with route_weight < 0 are excluded."""
        active = BotConfig(name="active", route_weight=1)
        neg = BotConfig(name="neg", route_weight=-1)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [active]
            result = _pick_by_weight([active, neg])

        self.assertEqual(result.name, "active")
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("neg", names)

    def test_all_excluded_returns_none(self):
        """When all bots have weight <= 0, return None."""
        paused = BotConfig(name="paused", route_weight=0)
        self.assertIsNone(_pick_by_weight([paused]))

    def test_empty_list_returns_none(self):
        self.assertIsNone(_pick_by_weight([]))

    def test_float_weights(self):
        """route_weight accepts floats (e.g. 0.5 for half traffic)."""
        a = BotConfig(name="a", route_weight=0.5)
        b = BotConfig(name="b", route_weight=1.0)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [b]
            result = _pick_by_weight([a, b])

        self.assertEqual(result.name, "b")
        _, kwargs = mock_choices.call_args
        weights = kwargs["weights"]
        self.assertAlmostEqual(weights[0], 0.5 / 1.5)
        self.assertAlmostEqual(weights[1], 1.0 / 1.5)


class PickUniformTest(unittest.TestCase):
    def test_uniform_selection(self):
        a = BotConfig(name="a")
        b = BotConfig(name="b")
        bots = [a, b]

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
            BotConfig(name="none"),  # defaults tier3
        ]
        with patch("agent.config.bot_service.list_configs", return_value=configs):
            t0_bots = _bots_for_tier(1, "tier0")
            t1_bots = _bots_for_tier(1, "tier1")
            t2_bots = _bots_for_tier(1, "tier2")
            t3_bots = _bots_for_tier(1, "tier3")

        self.assertEqual(len(t0_bots), 1)
        self.assertEqual(t0_bots[0].name, "t0")

        self.assertEqual(len(t1_bots), 1)
        self.assertEqual(t1_bots[0].name, "t1")

        self.assertEqual(len(t2_bots), 1)
        self.assertEqual(t2_bots[0].name, "t2")

        self.assertEqual(len(t3_bots), 1)
        self.assertEqual(t3_bots[0].name, "none")

    def test_excludes_perplexity(self):
        configs = [
            BotConfig(name="px", backend="perplexity", tier="tier1"),
            BotConfig(name="normal", tier="tier1"),
        ]
        with patch("agent.config.bot_service.list_configs", return_value=configs):
            t1_bots = _bots_for_tier(1, "tier1")

        self.assertEqual(len(t1_bots), 1)
        self.assertEqual(t1_bots[0].name, "normal")

    def test_no_price_queried(self):
        """_bots_for_tier no longer queries OpenRouter prices."""
        configs = [
            BotConfig(name="a", tier="tier1", base_url="https://openrouter.ai/api/v1", model="a-model"),
        ]
        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_pricing", create=True) as _,
        ):
            # Should not import or call bot_pricing
            bots = _bots_for_tier(1, "tier1")
        self.assertEqual(len(bots), 1)
        self.assertEqual(bots[0].name, "a")

    def test_excludes_model_type(self):
        """type='model' bots are excluded from tier pools."""
        inline = BotConfig(name="inline", tier="tier1", type="model")
        agent = BotConfig(name="agent", tier="tier1", type="agent")
        configs = [inline, agent]

        with patch("agent.config.bot_service.list_configs", return_value=configs):
            t1_bots = _bots_for_tier(1, "tier1")

        names = [b.name for b in t1_bots]
        self.assertNotIn("inline", names)
        self.assertIn("agent", names)

    def test_excludes_disabled(self):
        disabled = BotConfig(name="disabled", tier="tier1", enabled=False)
        enabled = BotConfig(name="enabled", tier="tier1", enabled=True)
        configs = [disabled, enabled]

        with patch("agent.config.bot_service.list_configs", return_value=configs):
            t1_bots = _bots_for_tier(1, "tier1")

        names = [b.name for b in t1_bots]
        self.assertNotIn("disabled", names)
        self.assertIn("enabled", names)


class ResolveBotConfigTierTest(unittest.TestCase):
    def test_name_pin_beats_backend_pin_same_request(self):
        """G1: bot-name pin wins over a backend pin on the same request, even
        when the named config's backend differs from the pinned backend."""
        default = BotConfig(name="default", backend="codex", model="gpt-5.4")
        claude_code = BotConfig(name="claude_code", backend="claude_code", model="sonnet")

        def _get_config(uid, name="default"):
            return claude_code if name == "claude_code" else None

        with (
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
            patch("agent.config.bot_service.list_configs", return_value=[default, claude_code]),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="claude_code", backend="codex")

        self.assertEqual(config.name, "claude_code")
        self.assertEqual(config.backend, "claude_code")

    def test_backend_pin_ignores_tier(self):
        """Name-first: the bot-name pin wins over both a backend pin and a
        tier request on the same request (PRD chain: name > backend > tier >
        default)."""
        default = BotConfig(name="default", backend="codex", model="gpt-5.4")
        claude_code = BotConfig(name="claude_code", backend="claude_code", model="sonnet")

        def _get_config(uid, name="default"):
            return default if name == "default" else None

        with (
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
            patch("agent.config.bot_service.list_configs", return_value=[default, claude_code]),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code", tier="tier2")
        self.assertEqual(config.name, "default")

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
        """G2 (strict chain): bot_name not found and no backend/tier given ->
        falls all the way through to default, no cross-user."""
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

    def test_missing_name_pin_falls_through_to_tier(self):
        """G2 (strict chain): a bot_name that fails lookup 'did not match' and
        falls through to the next link (tier), instead of short-circuiting to
        default."""
        bot_a = BotConfig(name="bot-a", tier="tier1", route_weight=1)

        with (
            patch("agent.config.bot_service.get_config", return_value=None),
            patch("agent.config.bot_service.list_configs", return_value=[bot_a]),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [bot_a]
            config = resolve_bot_config(1, bot_name="pinned", tier="tier1")

        self.assertEqual(config.name, "bot-a")
        mock_choices.assert_called_once()

    def test_tier_selects_weighted_random(self):
        # Representative proportional-weight routing through resolve_bot_config.
        # The per-tier variants (tier0/tier2) overlapped on this same normalization
        # math; the math itself is exercised directly in PickByWeightTest, and
        # per-tier filtering in BotsForTierTest, so one representative is enough.
        bot_a = BotConfig(name="bot-a", tier="tier1", route_weight=1)
        bot_b = BotConfig(name="bot-b", tier="tier1", route_weight=1)
        bot_c = BotConfig(name="bot-c", tier="tier1", route_weight=3)
        configs = [bot_a, bot_b, bot_c]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [bot_c]
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "bot-c")
        mock_choices.assert_called_once()
        _, kwargs = mock_choices.call_args
        weights = kwargs["weights"]
        self.assertAlmostEqual(weights[0], 0.2)
        self.assertAlmostEqual(weights[1], 0.2)
        self.assertAlmostEqual(weights[2], 0.6)

    def test_tier_falls_back_to_default_when_empty(self):
        default = BotConfig(name="default", backend="codex", model="gpt-5.4")
        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.bot_service.get_config", return_value=default),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, tier="tier1")
        self.assertEqual(config.name, "default")

    def test_perplexity_excluded_from_tier_pools(self):
        px = BotConfig(name="px", backend="perplexity", tier="tier1")
        normal = BotConfig(name="regular", tier="tier1", route_weight=1)
        configs = [px, normal]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
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

    def test_model_bots_excluded_from_tier(self):
        inline = BotConfig(name="inline", tier="tier1", type="model")
        tldr = BotConfig(name="tldr", tier="tier1", type="model")
        agent = BotConfig(name="deepseek", tier="tier1", type="agent", route_weight=1)
        configs = [inline, tldr, agent]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [agent]
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "deepseek")
        mock_choices.assert_called_once()
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("inline", names)
        self.assertNotIn("tldr", names)

    def test_tier_with_weight_zero_excluded(self):
        """Bots with route_weight=0 in a tier should not receive auto traffic."""
        active = BotConfig(name="active", tier="tier1", route_weight=1)
        paused = BotConfig(name="paused", tier="tier1", route_weight=0)
        configs = [active, paused]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [active]
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "active")
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("paused", names)

    def test_without_tier_preserves_default_resolution(self):
        default_config = BotConfig(name="default", backend="codex", model="gpt-5.4")
        with patch("agent.config.bot_service.get_config", return_value=default_config):
            config = resolve_bot_config(1)
        self.assertEqual(config.name, "default")


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
        """Name-first: the name pin ('default') wins even though its backend
        ('codex') differs from the pinned backend ('claude_code')."""
        default = BotConfig(name="default", backend="codex", model="gpt-5.4")
        claude_code = BotConfig(name="claude_code", backend="claude_code", model="sonnet")

        def _get_config(uid, name="default"):
            return default if name == "default" else None

        with (
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
            patch("agent.config.bot_service.list_configs", return_value=[default, claude_code]),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code")

        self.assertEqual(config.name, "default")
        self.assertEqual(config.backend, "codex")
        self.assertEqual(config.model, "gpt-5.4")

    def test_backend_only_fallback_does_not_reuse_mismatched_model(self):
        configs = [
            BotConfig(name="default", backend="codex", model="gpt-5.4"),
        ]

        with (
            patch("agent.config.bot_service.get_config", return_value=None),
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="claude_code")

        self.assertEqual(config.name, "default")
        self.assertEqual(config.backend, "claude_code")
        self.assertEqual(config.model, "")


class RefBotResolveTest(unittest.TestCase):
    """Tests for ref/pointer bot dereference."""

    def test_ref_dereference_single_level(self):
        default = BotConfig(name="default", ref_bot_name="codex")
        codex = BotConfig(name="codex", backend="codex", model="gpt-5.4")

        def _get_config(uid, name="default"):
            if name == "default":
                return default
            if name == "codex":
                return codex
            return None

        with patch("agent.config.bot_service.get_config", side_effect=_get_config):
            config = resolve_bot_config(1)

        self.assertEqual(config.name, "codex")
        self.assertEqual(config.backend, "codex")
        self.assertEqual(config.model, "gpt-5.4")

    def test_ref_dereference_multi_level(self):
        a = BotConfig(name="a", ref_bot_name="b")
        b = BotConfig(name="b", ref_bot_name="c")
        c = BotConfig(name="c", backend="codex", model="gpt-5.4")

        def _get_config(uid, name="default"):
            mapping = {"a": a, "b": b, "c": c}
            return mapping.get(name)

        with patch("agent.config.bot_service.get_config", side_effect=_get_config):
            config = resolve_bot_config(1, bot_name="a")

        self.assertEqual(config.name, "c")
        self.assertEqual(config.backend, "codex")
        self.assertEqual(config.model, "gpt-5.4")

    def test_ref_circular_detected(self):
        a = BotConfig(name="a", ref_bot_name="b")
        b = BotConfig(name="b", ref_bot_name="a")

        def _get_config(uid, name="default"):
            mapping = {"a": a, "b": b}
            return mapping.get(name)

        with patch("agent.config.bot_service.get_config", side_effect=_get_config):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1, bot_name="a")
            self.assertIn("Circular ref", str(ctx.exception))

    def test_ref_self_loop_detected(self):
        default = BotConfig(name="default", ref_bot_name="default")

        with patch("agent.config.bot_service.get_config", return_value=default):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1)
            self.assertIn("Circular ref", str(ctx.exception))

    def test_ref_max_depth_exceeded(self):
        bots = {f"bot{i}": BotConfig(name=f"bot{i}", ref_bot_name=f"bot{i+1}") for i in range(6)}
        bots["bot5"] = BotConfig(name="bot5", ref_bot_name="bot6")  # will exceed _MAX_REF_DEPTH=5

        def _get_config(uid, name="default"):
            return bots.get(name)

        with patch("agent.config.bot_service.get_config", side_effect=_get_config):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1, bot_name="bot0")
            self.assertIn("Max ref depth", str(ctx.exception))

    def test_ref_bot_excluded_from_tier_pool(self):
        default = BotConfig(name="default", ref_bot_name="codex", tier="tier1")
        codex = BotConfig(name="codex", backend="codex", route_weight=1, tier="tier1")
        configs = [default, codex]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            mock_choices.return_value = [codex]
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "codex")
        args, _ = mock_choices.call_args
        choices = args[0]
        names = [c.name for c in choices]
        self.assertNotIn("default", names)
        self.assertIn("codex", names)

    def test_ref_bot_pinned_by_name_derefs(self):
        default = BotConfig(name="default", ref_bot_name="codex")
        codex = BotConfig(name="codex", backend="codex", model="gpt-5.4", route_weight=1, tier="tier1")

        def _get_config(uid, name="default"):
            if name == "default":
                return default
            if name == "codex":
                return codex
            return None

        with patch("agent.config.bot_service.get_config", side_effect=_get_config):
            config = resolve_bot_config(1, bot_name="default")

        self.assertEqual(config.name, "codex")
        self.assertEqual(config.backend, "codex")

    def test_ref_backend_pin_derefs(self):
        # A backend pin (no matching name) derefs the matched ref bot to its target.
        default = BotConfig(name="default", ref_bot_name="codex")
        codex = BotConfig(name="codex", backend="codex", model="gpt-5.4")
        configs = [default, codex]

        with (
            patch("agent.config.bot_service.get_config", return_value=None),
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="unpinned", backend="codex")

        # _find_bot_config_by_backend finds codex directly (not default)
        self.assertEqual(config.name, "codex")
        self.assertEqual(config.backend, "codex")

    def test_ref_target_not_found_raises(self):
        default = BotConfig(name="default", ref_bot_name="nonexistent")

        def _get_config(uid, name="default"):
            if name == "default":
                return default
            return None

        with (
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1)
            self.assertIn("not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()