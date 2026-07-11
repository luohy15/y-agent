import unittest
from unittest.mock import patch

from agent.config import (
    resolve_bot_config,
    tier_of,
    _universe,
    _candidates,
    _pick_by_weight,
    _select,
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


class UniverseEligibilityTest(unittest.TestCase):
    def test_excludes_disabled_ref_and_model(self):
        configs = [
            BotConfig(name="disabled", enabled=False),
            BotConfig(name="ref", ref_bot_name="codex"),
            BotConfig(name="model-bot", type="model"),
            BotConfig(name="agent-bot", type="agent"),
        ]
        with patch("agent.config.bot_service.list_configs", return_value=configs):
            universe = _universe(1)

        names = [c.name for c in universe]
        self.assertEqual(names, ["agent-bot"])

    def test_perplexity_stays_in_universe(self):
        """Perplexity is excluded from tier candidacy only, not the universe
        itself, so backend=perplexity / name=px pins still resolve."""
        px = BotConfig(name="px", backend="perplexity")
        with patch("agent.config.bot_service.list_configs", return_value=[px]):
            universe = _universe(1)

        self.assertEqual([c.name for c in universe], ["px"])

    def test_cross_user_fallback_only_when_user_has_zero_configs(self):
        default_cfg = BotConfig(name="default-user-bot")

        def _list_configs(uid):
            return [] if uid == 1 else [default_cfg]

        with (
            patch("agent.config.bot_service.list_configs", side_effect=_list_configs),
            patch("agent.config.get_default_user_id", return_value=2),
        ):
            universe = _universe(1)

        self.assertEqual([c.name for c in universe], ["default-user-bot"])

    def test_no_cross_user_fallback_when_user_has_disabled_configs(self):
        """'None of their own' means zero configs total, not zero enabled
        ones: a user with only a disabled config does not fall through."""
        disabled = BotConfig(name="disabled", enabled=False)
        default_cfg = BotConfig(name="default-user-bot")

        def _list_configs(uid):
            return [disabled] if uid == 1 else [default_cfg]

        with (
            patch("agent.config.bot_service.list_configs", side_effect=_list_configs),
            patch("agent.config.get_default_user_id", return_value=2),
        ):
            universe = _universe(1)

        self.assertEqual(universe, [])


class CandidatesFilterTest(unittest.TestCase):
    def test_name_filter(self):
        a = BotConfig(name="a")
        b = BotConfig(name="b")
        self.assertEqual([c.name for c in _candidates([a, b], bot_name="a")], ["a"])

    def test_backend_filter(self):
        a = BotConfig(name="a", backend="codex")
        b = BotConfig(name="b", backend="claude_code")
        self.assertEqual([c.name for c in _candidates([a, b], backend="codex")], ["a"])

    def test_tier_filter_unset_tier_matches_tier3(self):
        a = BotConfig(name="a")  # unset tier -> tier3
        b = BotConfig(name="b", tier="tier1")
        self.assertEqual([c.name for c in _candidates([a, b], tier="tier3")], ["a"])

    def test_tier_filter_excludes_perplexity(self):
        px = BotConfig(name="px", backend="perplexity", tier="tier1")
        normal = BotConfig(name="normal", tier="tier1")
        result = _candidates([px, normal], tier="tier1")
        self.assertEqual([c.name for c in result], ["normal"])

    def test_filters_intersect(self):
        a = BotConfig(name="a", backend="codex", tier="tier1")
        b = BotConfig(name="a", backend="claude_code", tier="tier1")
        result = _candidates([a, b], bot_name="a", backend="codex")
        self.assertEqual([c.name for c in result], ["a"])
        self.assertEqual(result[0].backend, "codex")


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

    def test_zero_weight_never_wins_multi_candidate_draw(self):
        active = BotConfig(name="active", route_weight=1)
        paused = BotConfig(name="paused", route_weight=0)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [active]
            result = _pick_by_weight([active, paused])

        self.assertEqual(result.name, "active")
        args, _ = mock_choices.call_args
        choices = args[0]
        self.assertNotIn("paused", [c.name for c in choices])

    def test_unset_weight_never_wins_multi_candidate_draw(self):
        active = BotConfig(name="active", route_weight=1)
        unknown = BotConfig(name="unknown", route_weight=None)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [active]
            result = _pick_by_weight([active, unknown])

        self.assertEqual(result.name, "active")
        args, _ = mock_choices.call_args
        choices = args[0]
        self.assertNotIn("unknown", [c.name for c in choices])

    def test_negative_weight_excluded(self):
        active = BotConfig(name="active", route_weight=1)
        neg = BotConfig(name="neg", route_weight=-1)

        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [active]
            result = _pick_by_weight([active, neg])

        self.assertEqual(result.name, "active")

    def test_zero_total_pool_returns_none(self):
        """A zero-total-weight pool counts as empty."""
        paused_a = BotConfig(name="paused-a", route_weight=0)
        paused_b = BotConfig(name="paused-b", route_weight=0)
        self.assertIsNone(_pick_by_weight([paused_a, paused_b]))

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


class SelectTest(unittest.TestCase):
    def test_sole_candidate_used_regardless_of_weight(self):
        """A sole candidate is used directly; weight is not consulted."""
        zero_weight = BotConfig(name="only", route_weight=0)
        with patch("agent.config.random.choices") as mock_choices:
            result = _select([zero_weight])
        self.assertEqual(result.name, "only")
        mock_choices.assert_not_called()

    def test_empty_returns_none(self):
        self.assertIsNone(_select([]))

    def test_multi_candidate_draws_by_weight(self):
        a = BotConfig(name="a", route_weight=1)
        b = BotConfig(name="b", route_weight=1)
        with patch("agent.config.random.choices") as mock_choices:
            mock_choices.return_value = [b]
            result = _select([a, b])
        self.assertEqual(result.name, "b")
        mock_choices.assert_called_once()

    def test_multi_candidate_zero_total_weight_returns_none(self):
        a = BotConfig(name="a", route_weight=0)
        b = BotConfig(name="b", route_weight=0)
        self.assertIsNone(_select([a, b]))


class ResolveBotConfigTest(unittest.TestCase):
    def test_no_filters_resolves_tier2(self):
        t2_bot = BotConfig(name="t2-bot", tier="tier2", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[t2_bot]),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1)
        self.assertEqual(config.name, "t2-bot")

    def test_single_candidate_used_directly_weight_not_consulted(self):
        bot_a = BotConfig(name="bot-a", tier="tier1", route_weight=0)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[bot_a]),
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, tier="tier1")
        self.assertEqual(config.name, "bot-a")
        mock_choices.assert_not_called()

    def test_multiple_tier_candidates_use_persisted_weighted_round_robin(self):
        bot_a = BotConfig(name="bot-a", tier="tier1", route_weight=1)
        bot_b = BotConfig(name="bot-b", tier="tier1", route_weight=1)
        bot_c = BotConfig(name="bot-c", tier="tier1", route_weight=3)
        configs = [bot_a, bot_b, bot_c]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.bot_service.select_weighted_round_robin", return_value="bot-c") as select,
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "bot-c")
        select.assert_called_once_with(1, "tier1", [("bot-a", 1), ("bot-b", 1), ("bot-c", 3)])
        mock_choices.assert_not_called()

    def test_tier_selection_uses_persisted_sequence_across_new_chats(self):
        sol = BotConfig(name="sol", tier="tier1", route_weight=1)
        opus = BotConfig(name="opus", tier="tier1", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[sol, opus]),
            patch("agent.config.bot_service.select_weighted_round_robin", side_effect=["sol", "opus"]),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            first = resolve_bot_config(1, tier="tier1")
            second = resolve_bot_config(1, tier="tier1")

        self.assertEqual([first.name, second.name], ["sol", "opus"])

    def test_tier_and_backend_filter_uses_persisted_weighted_round_robin(self):
        bot_a = BotConfig(name="bot-a", backend="codex", tier="tier1", route_weight=1)
        bot_b = BotConfig(name="bot-b", backend="codex", tier="tier1", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[bot_a, bot_b]),
            patch("agent.config.bot_service.select_weighted_round_robin", return_value="bot-b") as select,
            patch("agent.config.random.choices") as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, backend="codex", tier="tier1")

        self.assertEqual(config.name, "bot-b")
        select.assert_called_once_with(1, "tier1", [("bot-a", 1), ("bot-b", 1)])
        mock_choices.assert_not_called()

    def test_backend_filter_keeps_weighted_random_selection(self):
        bot_a = BotConfig(name="bot-a", backend="codex", tier="tier1", route_weight=1)
        bot_b = BotConfig(name="bot-b", backend="codex", tier="tier1", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[bot_a, bot_b]),
            patch("agent.config.random.choices", return_value=[bot_b]) as mock_choices,
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, backend="codex")

        self.assertEqual(config.name, "bot-b")
        mock_choices.assert_called_once()

    def test_name_and_backend_intersect(self):
        matching = BotConfig(name="a", backend="codex")
        mismatched = BotConfig(name="b", backend="claude_code")
        with (
            patch("agent.config.bot_service.list_configs", return_value=[matching, mismatched]),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="a", backend="codex")
        self.assertEqual(config.name, "a")

    def test_name_and_backend_empty_intersection_falls_back_to_tier2(self):
        """PRD behavior change: --bot X --backend Y with no config satisfying
        both intersects to empty and degrades to tier2, no synthetic fallback."""
        only_config = BotConfig(name="a", backend="claude_code")
        t2_bot = BotConfig(name="t2-bot", tier="tier2", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[only_config, t2_bot]),
            patch("agent.config.bot_service.get_config", return_value=None),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="a", backend="codex")
        self.assertEqual(config.name, "t2-bot")

    def test_unknown_bot_name_falls_back_to_tier2(self):
        t2_bot = BotConfig(name="t2-bot", tier="tier2", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[t2_bot]),
            patch("agent.config.bot_service.get_config", return_value=None),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="nonexistent")
        self.assertEqual(config.name, "t2-bot")

    def test_disabled_bot_name_pin_falls_back_to_tier2(self):
        disabled = BotConfig(name="disabled-bot", enabled=False)
        t2_bot = BotConfig(name="t2-bot", tier="tier2", route_weight=1)
        with (
            patch("agent.config.bot_service.list_configs", return_value=[disabled, t2_bot]),
            patch("agent.config.bot_service.get_config", return_value=disabled),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="disabled-bot")
        self.assertEqual(config.name, "t2-bot")

    def test_empty_tier2_falls_back_to_default_bot(self):
        default = BotConfig(name="default", backend="codex", model="gpt-5.4")
        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.bot_service.get_config", return_value=default),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, tier="tier1")
        self.assertEqual(config.name, "default")

    def test_empty_intersection_with_no_tier2_pool_raises_on_no_default(self):
        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.bot_service.get_config", return_value=None),
            patch("agent.config.get_default_user_id", return_value=1),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            with self.assertRaises(ValueError):
                resolve_bot_config(1, bot_name="nonexistent")


class PerplexityLiveShapeRegressionTest(unittest.TestCase):
    """Regression guard for review-2738: the live px config is
    `type=agent` (not `type=model`), so it must stay reachable via both a
    name pin and a backend pin. The fixture mirrors the live roster shape
    exactly (`y bot list`: px = backend=perplexity, model=sonar, tier3,
    type=agent) so a future retype can't silently regress candidacy again."""

    def _roster(self):
        return [
            BotConfig(name="sonnet", backend="claude_code", tier="tier2", route_weight=1),
            BotConfig(name="terra", backend="codex", tier="tier2", route_weight=1),
            BotConfig(name="px", backend="perplexity", model="sonar", tier="tier3", type="agent"),
        ]

    def test_bot_name_px_resolves_to_px(self):
        with (
            patch("agent.config.bot_service.list_configs", return_value=self._roster()),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, bot_name="px")
        self.assertEqual(config.name, "px")
        self.assertEqual(config.backend, "perplexity")

    def test_backend_perplexity_resolves_to_px(self):
        with (
            patch("agent.config.bot_service.list_configs", return_value=self._roster()),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, backend="perplexity")
        self.assertEqual(config.name, "px")

    def test_px_excluded_from_tier3_pool(self):
        """Perplexity is pin-only: it must not enter the tier3 weighted
        pool even though it now shares tier3 with other agent-type bots."""
        other_tier3 = BotConfig(name="deepseek", backend="pi_cli", tier="tier3", route_weight=1)
        roster = self._roster() + [other_tier3]
        with (
            patch("agent.config.bot_service.list_configs", return_value=roster),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, tier="tier3")
        self.assertEqual(config.name, "deepseek")


class RefBotResolveTest(unittest.TestCase):
    """Tests for ref/pointer bot dereference."""

    def test_ref_dereference_default_bot(self):
        """No-filter dispatch never sees the ref pointer (excluded from the
        universe / tier2 pool); it only reaches the deref'd default via the
        empty-tier2 fallback path."""
        default = BotConfig(name="default", ref_bot_name="codex")
        codex = BotConfig(name="codex", backend="codex", model="gpt-5.4")

        def _get_config(uid, name="default"):
            if name == "default":
                return default
            if name == "codex":
                return codex
            return None

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
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

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.get_default_user_id", return_value=1),
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
        ):
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

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.get_default_user_id", return_value=1),
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1, bot_name="a")
            self.assertIn("Circular ref", str(ctx.exception))

    def test_ref_self_loop_detected(self):
        default = BotConfig(name="default", ref_bot_name="default")

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.get_default_user_id", return_value=1),
            patch("agent.config.bot_service.get_config", return_value=default),
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1)
            self.assertIn("Circular ref", str(ctx.exception))

    def test_ref_max_depth_exceeded(self):
        bots = {f"bot{i}": BotConfig(name=f"bot{i}", ref_bot_name=f"bot{i+1}") for i in range(6)}
        bots["bot5"] = BotConfig(name="bot5", ref_bot_name="bot6")  # will exceed _MAX_REF_DEPTH=5

        def _get_config(uid, name="default"):
            return bots.get(name)

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.get_default_user_id", return_value=1),
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1, bot_name="bot0")
            self.assertIn("Max ref depth", str(ctx.exception))

    def test_ref_bot_excluded_from_tier_pool(self):
        default = BotConfig(name="default", ref_bot_name="codex", tier="tier1")
        codex = BotConfig(name="codex", backend="codex", route_weight=1, tier="tier1")
        configs = [default, codex]

        with (
            patch("agent.config.bot_service.list_configs", return_value=configs),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            config = resolve_bot_config(1, tier="tier1")

        self.assertEqual(config.name, "codex")

    def test_ref_bot_pinned_by_name_derefs(self):
        """Decision (plan-2738): explicit name pins keep pointer-deref
        semantics even though ref bots are excluded from candidacy."""
        default = BotConfig(name="default", ref_bot_name="codex")
        codex = BotConfig(name="codex", backend="codex", model="gpt-5.4", route_weight=1, tier="tier1")

        def _get_config(uid, name="default"):
            if name == "default":
                return default
            if name == "codex":
                return codex
            return None

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.get_default_user_id", return_value=1),
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
        ):
            config = resolve_bot_config(1, bot_name="default")

        self.assertEqual(config.name, "codex")
        self.assertEqual(config.backend, "codex")

    def test_ref_bot_pinned_by_name_with_extra_filter_no_deref_exception(self):
        """The name-pin deref exception only applies to a pure name pin (no
        backend/tier alongside it); combined with another filter it follows
        the plain intersection rule (ref excluded -> empty -> tier2)."""
        default = BotConfig(name="default", ref_bot_name="codex")
        t2_bot = BotConfig(name="t2-bot", tier="tier2", route_weight=1)

        with (
            patch("agent.config.bot_service.list_configs", return_value=[t2_bot]),
            patch("agent.config.get_default_user_id", return_value=1),
            patch("agent.config.bot_service.get_config", return_value=default),
            self.assertLogs("agent.config", level="WARNING"),
        ):
            config = resolve_bot_config(1, bot_name="default", backend="codex")

        self.assertEqual(config.name, "t2-bot")

    def test_ref_target_not_found_raises(self):
        default = BotConfig(name="default", ref_bot_name="nonexistent")

        def _get_config(uid, name="default"):
            if name == "default":
                return default
            return None

        with (
            patch("agent.config.bot_service.list_configs", return_value=[]),
            patch("agent.config.bot_service.get_config", side_effect=_get_config),
            patch("agent.config.get_default_user_id", return_value=1),
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_bot_config(1)
            self.assertIn("not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
