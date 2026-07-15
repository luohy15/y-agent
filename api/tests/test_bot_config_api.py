"""Unit tests for api.controller.bot_config — the `/api/bot/*` endpoints that
back `y bot` CLI-through-API (todo 2811): rename (new), update clear_openrouter
(new), and get/list price + openrouter presence enrichment (new).

storage.service.bot_config and agent.pi_models.sync_pi_models are mocked;
nothing touches a real database.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api.controller import bot_config as bot_config_controller
from storage.entity.dto import BotConfig


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _cfg(name, **overrides):
    base = dict(
        name=name, base_url="https://x", api_key="secret12345678", backend="claude_code",
        model="m", tier="tier2", type="agent", route_weight=1.0, ref_bot_name=None,
        openrouter_config=None, enabled=True,
    )
    base.update(overrides)
    return BotConfig(**base)


class RenameBotConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_rename_success_cascades_and_syncs(self):
        old = _cfg("old")
        with (
            patch.object(
                bot_config_controller.bot_service, "get_config",
                side_effect=lambda uid, name: old if name == "old" else None,
            ),
            patch.object(bot_config_controller.bot_service, "rename_config", return_value=True) as rename_config,
            patch("agent.pi_models.sync_pi_models") as sync_pi_models,
        ):
            result = await bot_config_controller.rename_bot_config(
                _request(), bot_config_controller.BotRenameRequest(old_name="old", new_name="new")
            )
        self.assertEqual(result, {"ok": True, "name": "new"})
        rename_config.assert_called_once_with(123, "old", "new")
        sync_pi_models.assert_called_once_with(123)

    async def test_rename_default_is_guarded(self):
        with self.assertRaises(HTTPException) as ctx:
            await bot_config_controller.rename_bot_config(
                _request(), bot_config_controller.BotRenameRequest(old_name="default", new_name="new")
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_rename_missing_old_name_is_404(self):
        with patch.object(bot_config_controller.bot_service, "get_config", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await bot_config_controller.rename_bot_config(
                    _request(), bot_config_controller.BotRenameRequest(old_name="old", new_name="new")
                )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_rename_name_collision_is_409(self):
        old = _cfg("old")
        new = _cfg("new")
        with patch.object(
            bot_config_controller.bot_service, "get_config",
            side_effect=lambda uid, name: {"old": old, "new": new}.get(name),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await bot_config_controller.rename_bot_config(
                    _request(), bot_config_controller.BotRenameRequest(old_name="old", new_name="new")
                )
        self.assertEqual(ctx.exception.status_code, 409)


class UpdateBotConfigClearOpenrouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_clear_openrouter_nulls_field(self):
        existing = _cfg("x", openrouter_config={"provider": {"sort": "throughput"}})
        with (
            patch.object(bot_config_controller.bot_service, "get_config", return_value=existing),
            patch.object(bot_config_controller.bot_service, "add_config") as add_config,
            patch("agent.pi_models.sync_pi_models"),
        ):
            req = bot_config_controller.UpdateBotConfigRequest(name="x", clear_openrouter=True)
            await bot_config_controller.update_bot_config(_request(), req)
        saved = add_config.call_args[0][1]
        self.assertIsNone(saved.openrouter_config)

    async def test_no_clear_flag_preserves_existing_openrouter_config(self):
        existing = _cfg("x", openrouter_config={"provider": {"sort": "throughput"}})
        with (
            patch.object(bot_config_controller.bot_service, "get_config", return_value=existing),
            patch.object(bot_config_controller.bot_service, "add_config") as add_config,
            patch("agent.pi_models.sync_pi_models"),
        ):
            req = bot_config_controller.UpdateBotConfigRequest(name="x", model="new-model")
            await bot_config_controller.update_bot_config(_request(), req)
        saved = add_config.call_args[0][1]
        self.assertEqual(saved.openrouter_config, {"provider": {"sort": "throughput"}})
        self.assertEqual(saved.model, "new-model")


class GetListEnrichmentTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_includes_price_and_openrouter_presence_fields(self):
        cfg = _cfg("x", openrouter_config={"a": 1})
        with (
            patch.object(bot_config_controller.bot_service, "get_config", return_value=cfg),
            patch.object(bot_config_controller, "fetch_openrouter_catalog", return_value=None),
        ):
            result = await bot_config_controller.get_bot_config(_request(), name="x")
        self.assertIn("price_input", result)
        self.assertIn("price_output", result)
        self.assertTrue(result["has_openrouter"])

    async def test_get_not_found_is_404(self):
        with patch.object(bot_config_controller.bot_service, "get_config", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await bot_config_controller.get_bot_config(_request(), name="missing")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_list_includes_openrouter_presence_field(self):
        cfg = _cfg("x", openrouter_config=None)
        with (
            patch.object(bot_config_controller.bot_service, "list_configs", return_value=[cfg]),
            patch.object(bot_config_controller, "fetch_openrouter_catalog", return_value=None),
        ):
            result = await bot_config_controller.list_bot_configs(_request())
        self.assertFalse(result[0]["has_openrouter"])


if __name__ == "__main__":
    unittest.main()
