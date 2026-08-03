"""Unit tests for `y ui` (todo 2412, S4).

API and the node build are mocked; SDK package data and scaffolding are real.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from yagent.commands.ui.click import ui_group
from yagent.commands.ui._paths import SLUG_RE, meta_path, source_path, ui_dir, validate_slug
from yagent.commands.ui._sdk import (
    _DIGEST_MARKER,
    ensure_sdk,
    load_contract,
    package_sdk_digest,
    package_sdk_root,
)


def _resp(payload, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = payload
    m.raise_for_status = MagicMock()
    return m


class UiGroupHelpTest(unittest.TestCase):
    def test_group_help_lists_commands(self):
        result = CliRunner().invoke(ui_group, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for name in (
            "create",
            "list",
            "versions",
            "publish",
            "rollback",
            "activate",
            "enable",
            "disable",
            "delete",
        ):
            self.assertIn(name, result.output)


class SdkPackageDataTest(unittest.TestCase):
    def test_contract_and_shims_ship_with_cli(self):
        root = package_sdk_root()
        self.assertTrue((root / "contract.json").is_file())
        self.assertTrue((root / "build.mjs").is_file())
        self.assertTrue((root / "theme.css").is_file())
        self.assertTrue((root / "shims" / "react.cjs").is_file())
        self.assertTrue((root / "shims" / "y-host.cjs").is_file())
        self.assertTrue((root / "templates" / "starter.tsx").is_file())
        contract = load_contract()
        self.assertEqual(contract["version"], 4)
        self.assertIn("react", contract["externals"])
        self.assertIn("@y/host", contract["externals"])
        self.assertIn("lightweight-charts", contract["externals"])
        self.assertIn("swr/infinite", contract["externals"])
        # F1/F2 markers must stay in the build recipe.
        build = (root / "build.mjs").read_text(encoding="utf-8")
        self.assertIn("theme(reference)", build)
        self.assertIn("source(none)", build)
        self.assertIn("@scope", build)
        self.assertIn("hoistAtProperty", build)

    def test_y_host_dts_mirrors_runtime_host_sdk_exports(self):
        """d.ts must match web/src/host/sdk.ts hostSdk keys (S5 runtime names win).

        Declaring a name that is not on the registry makes artifacts typecheck
        then throw at runtime when the CJS shim does registry.modules['@y/host'].
        """
        dts = (package_sdk_root() / "y-host.d.ts").read_text(encoding="utf-8")
        # Extract the @y/host module block only.
        start = dts.index('declare module "@y/host"')
        block = dts[start:]
        required = [
            "HOST_CONTRACT_VERSION",
            "API",
            "authFetch",
            "jsonFetcher",
            "ListLoading",
            "ListError",
            "ListEmpty",
            "useThemeColors",
            "readThemeColors",
            "ThemeColors",
            "TRACE_BADGE",
            "CHAT_BADGE",
            "topicBadgeClass",
            "statusBadgeClass",
            "priorityColorClass",
            "actionBadgeClass",
            "getTopicColor",
            "getTopicChartColors",
            "navigateTo",
            "useArtifactIntent",
            "openArtifactDetail",
            "runHostCommand",
            "optimisticListMutate",
        ]
        for name in required:
            self.assertIn(name, block, f"missing runtime export {name!r} in y-host.d.ts")
        # Names that used to be invented here and are NOT on hostSdk.
        # Match as export identifiers (word boundary) so useTheme ≠ useThemeColors
        # and navigate ≠ navigateTo.
        import re

        for name in ("useTheme", "Badge", "navigate"):
            pattern = rf"\b{re.escape(name)}\b"
            self.assertIsNone(
                re.search(pattern, block),
                f"stale non-runtime export {name!r} still in y-host.d.ts",
            )


class SlugValidationTest(unittest.TestCase):
    """CLI slug rule must match api/controller/ui_artifact.py SLUG_RE exactly."""

    API_SLUG_RE = r"^[a-z0-9][a-z0-9-]{0,62}$"

    def test_regex_matches_api(self):
        self.assertEqual(SLUG_RE.pattern, self.API_SLUG_RE)

    def test_accepts_digit_start_and_hyphen(self):
        self.assertEqual(validate_slug("9lives"), "9lives")
        self.assertEqual(validate_slug("demo-panel"), "demo-panel")
        self.assertEqual(validate_slug("a" + "b" * 62), "a" + "b" * 62)  # 63 chars

    def test_rejects_underscore_uppercase_and_too_long(self):
        for bad in ("demo_panel", "BadSlug", "has space", "", "a" * 64, "-leading"):
            with self.assertRaises(ValueError):
                validate_slug(bad)


class SdkRefreshTest(unittest.TestCase):
    def test_ensure_sdk_refreshes_when_packaged_content_changes(self):
        """A fix to build.mjs (no contract bump) must re-materialize ~/ui/.sdk."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.ui._sdk._ensure_npm_install"):
                dest = ensure_sdk()
                build_path = dest / "build.mjs"
                self.assertTrue(build_path.is_file())
                marker = dest / _DIGEST_MARKER
                self.assertTrue(marker.is_file())
                first_digest = marker.read_text(encoding="utf-8").strip()
                self.assertEqual(first_digest, package_sdk_digest())

                # Stale local edit must be overwritten when package digest mismatches.
                build_path.write_text(
                    build_path.read_text(encoding="utf-8") + "\n// STALE_LOCAL\n",
                    encoding="utf-8",
                )
                # Force a package-side content change via a temp package root.
                with tempfile.TemporaryDirectory() as pkg_tmp:
                    import shutil

                    pkg = Path(pkg_tmp)
                    shutil.copytree(package_sdk_root(), pkg, dirs_exist_ok=True)
                    (pkg / "build.mjs").write_text(
                        (pkg / "build.mjs").read_text(encoding="utf-8")
                        + "\n// PACKAGE_FIX\n",
                        encoding="utf-8",
                    )
                    expected = package_sdk_digest(pkg)
                    with patch(
                        "yagent.commands.ui._sdk.package_sdk_root",
                        return_value=pkg,
                    ):
                        ensure_sdk()

                    refreshed = (dest / "build.mjs").read_text(encoding="utf-8")
                    self.assertIn("PACKAGE_FIX", refreshed)
                    self.assertNotIn("STALE_LOCAL", refreshed)
                    self.assertEqual(
                        (dest / _DIGEST_MARKER).read_text(encoding="utf-8").strip(),
                        expected,
                    )

    def test_ensure_sdk_skips_copy_when_digest_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.ui._sdk._ensure_npm_install"):
                dest = ensure_sdk()
                build_path = dest / "build.mjs"
                # Mutate dest file but keep marker in sync → without package
                # change we would skip; force marker to match package so skip
                # path is exercised after a no-op package digest match.
                original = build_path.read_text(encoding="utf-8")
                build_path.write_text(original + "\n// local_only\n", encoding="utf-8")
                # Re-stamp marker to current package digest (simulates prior sync).
                (dest / _DIGEST_MARKER).write_text(
                    package_sdk_digest() + "\n", encoding="utf-8"
                )
                ensure_sdk()
                # Skip path: local mutation preserved when package digest matches.
                self.assertIn("local_only", build_path.read_text(encoding="utf-8"))


class UiCreateTest(unittest.TestCase):
    def test_create_scaffolds_source_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.ui._sdk._ensure_npm_install"), \
                 patch("yagent.commands.ui.create.resolve_artifact", return_value=None), \
                 patch(
                     "yagent.commands.ui.create.create_artifact",
                     return_value={"artifact_id": "art_1", "slug": "demo"},
                 ) as create_fn:
                result = CliRunner().invoke(ui_group, ["create", "demo"])

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(source_path("demo").is_file())
                meta = json.loads(meta_path("demo").read_text(encoding="utf-8"))
                self.assertEqual(meta["label"], "Demo")
                self.assertEqual(meta["icon"], "box")
                create_fn.assert_called_once_with("demo")
                # SDK materialized
                self.assertTrue((ui_dir() / ".sdk" / "build.mjs").is_file())
                self.assertTrue((ui_dir() / ".sdk" / "shims" / "react.cjs").is_file())
                self.assertTrue((ui_dir() / ".sdk" / _DIGEST_MARKER).is_file())

    def test_create_rejects_invalid_slug(self):
        result = CliRunner().invoke(ui_group, ["create", "Bad Slug"])
        self.assertNotEqual(result.exit_code, 0)
        result2 = CliRunner().invoke(ui_group, ["create", "demo_panel"])
        self.assertNotEqual(result2.exit_code, 0)

    def test_create_accepts_digit_start_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.ui._sdk._ensure_npm_install"), \
                 patch("yagent.commands.ui.create.resolve_artifact", return_value=None), \
                 patch(
                     "yagent.commands.ui.create.create_artifact",
                     return_value={"artifact_id": "art_9", "slug": "9lives"},
                 ):
                result = CliRunner().invoke(ui_group, ["create", "9lives"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(source_path("9lives").is_file())

    def test_create_no_register_skips_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.ui._sdk._ensure_npm_install"), \
                 patch("yagent.commands.ui.create.resolve_artifact") as resolve_fn, \
                 patch("yagent.commands.ui.create.create_artifact") as create_fn:
                result = CliRunner().invoke(
                    ui_group, ["create", "local-only", "--no-register"]
                )
                self.assertEqual(result.exit_code, 0, result.output)
                resolve_fn.assert_not_called()
                create_fn.assert_not_called()
                self.assertTrue(source_path("local-only").is_file())


class UiListTest(unittest.TestCase):
    def test_list_prints_active_version(self):
        payload = [
            {
                "slug": "finance",
                "artifact_id": "art_a",
                "enabled": True,
                "active_version_id": "ver_1",
                "active_version": {
                    "version_no": 2,
                    "label": "Finance",
                    "version_id": "ver_1",
                },
            }
        ]
        with patch("yagent.commands.ui.list.list_artifacts", return_value=payload):
            result = CliRunner().invoke(ui_group, ["list"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("finance", result.output)
        self.assertIn("v2", result.output)


class UiVersionsDescriptionTest(unittest.TestCase):
    def test_versions_shows_description_when_present_and_omits_none(self):
        payload_versions = [
            {
                "version_id": "ver_2",
                "version_no": 2,
                "sha256": "b" * 64,
                "label": "Demo",
                "built_at": "2026-07-31T00:00:00Z",
                "description": "[2991] fix overflow",
            },
            {
                "version_id": "ver_1",
                "version_no": 1,
                "sha256": "a" * 64,
                "label": "Demo",
                "built_at": "2026-07-30T00:00:00Z",
                "description": None,
            },
        ]
        with patch(
            "yagent.commands.ui.versions.resolve_artifact",
            return_value={"artifact_id": "art_1", "slug": "demo", "active_version_id": "ver_2"},
        ), patch(
            "yagent.commands.ui.versions.list_versions",
            return_value=payload_versions,
        ):
            result = CliRunner().invoke(ui_group, ["versions", "demo"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("[2991] fix overflow", result.output)
        v1_line = next(line for line in result.output.splitlines() if "v1" in line)
        self.assertNotIn("None", v1_line)


class UiPublishTest(unittest.TestCase):
    def test_publish_posts_multipart_and_prints_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle = Path(tmp) / "bundle.js"
            bundle.write_bytes(b"export default 1;\nexport const css = \"\";\n")
            manifest = {
                "slug": "demo",
                "sha256": "abc123" + "0" * 58,
                "source_digest": "src" + "0" * 61,
                "min_host_version": 1,
                "bytes": bundle.stat().st_size,
                "bundle": str(bundle),
            }
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.ui.publish.build_artifact",
                     return_value=manifest,
                 ), \
                 patch(
                     "yagent.commands.ui.publish.resolve_or_create",
                     return_value={"artifact_id": "art_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.ui.publish.publish_bundle",
                     return_value={
                         "version_no": 3,
                         "sha256": manifest["sha256"],
                         "version_id": "ver_3",
                     },
                 ) as pub:
                # Write meta so label/icon resolve
                (home / "ui").mkdir(parents=True)
                (home / "ui" / "demo.json").write_text(
                    json.dumps({"label": "Demo", "icon": "box"}), encoding="utf-8"
                )
                result = CliRunner().invoke(ui_group, ["publish", "demo"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("v3", result.output)
            self.assertIn("active", result.output)
            kwargs = pub.call_args.kwargs
            self.assertEqual(kwargs["artifact_id"], "art_1")
            self.assertEqual(kwargs["sha256"], manifest["sha256"])
            self.assertEqual(kwargs["label"], "Demo")
            self.assertTrue(kwargs["activate"])
            self.assertEqual(kwargs["bundle_bytes"], bundle.read_bytes())

    def test_publish_no_activate_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle = Path(tmp) / "bundle.js"
            bundle.write_bytes(b"x")
            manifest = {
                "slug": "demo",
                "sha256": "a" * 64,
                "source_digest": "b" * 64,
                "min_host_version": 1,
                "bytes": 1,
                "bundle": str(bundle),
            }
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.ui.publish.build_artifact",
                     return_value=manifest,
                 ), \
                 patch(
                     "yagent.commands.ui.publish.resolve_or_create",
                     return_value={"artifact_id": "art_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.ui.publish.publish_bundle",
                     return_value={"version_no": 1, "sha256": "a" * 64},
                 ) as pub:
                result = CliRunner().invoke(
                    ui_group, ["publish", "demo", "--no-activate"]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("staged", result.output)
            self.assertFalse(pub.call_args.kwargs["activate"])

    def test_publish_desc_flag_composes_and_threads_through_publish_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle = Path(tmp) / "bundle.js"
            bundle.write_bytes(b"x")
            manifest = {
                "slug": "demo",
                "sha256": "a" * 64,
                "source_digest": "b" * 64,
                "min_host_version": 1,
                "bytes": 1,
                "bundle": str(bundle),
            }
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home), "Y_TRACE_ID": "2991"}), \
                 patch(
                     "yagent.commands.ui.publish.build_artifact",
                     return_value=manifest,
                 ), \
                 patch(
                     "yagent.commands.ui.publish.resolve_or_create",
                     return_value={"artifact_id": "art_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.ui.publish.publish_bundle",
                     return_value={"version_no": 1, "sha256": "a" * 64},
                 ) as pub:
                result = CliRunner().invoke(
                    ui_group, ["publish", "demo", "-d", "fix overflow"]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(pub.call_args.kwargs["description"], "[2991] fix overflow")

    def test_publish_build_failure_exits_nonzero_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.ui.publish.build_artifact",
                     side_effect=RuntimeError("ERROR: Unexpected \")\""),
                 ), \
                 patch("yagent.commands.ui.publish.resolve_or_create") as resolve_fn, \
                 patch("yagent.commands.ui.publish.publish_bundle") as pub_fn:
                result = CliRunner().invoke(ui_group, ["publish", "demo"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Unexpected", result.output + (result.stderr or ""))
            resolve_fn.assert_not_called()
            pub_fn.assert_not_called()


class UiPointerCommandsTest(unittest.TestCase):
    def test_rollback_resolves_slug(self):
        with patch(
            "yagent.commands.ui.rollback.resolve_artifact",
            return_value={"artifact_id": "art_1", "slug": "demo"},
        ), patch(
            "yagent.commands.ui.rollback.rollback",
            return_value={"active_version_id": "ver_prev"},
        ) as rb:
            result = CliRunner().invoke(ui_group, ["rollback", "demo"])
        self.assertEqual(result.exit_code, 0, result.output)
        rb.assert_called_once_with("art_1")

    def test_activate_by_number(self):
        with patch(
            "yagent.commands.ui.activate.resolve_artifact",
            return_value={"artifact_id": "art_1", "slug": "demo"},
        ), patch(
            "yagent.commands.ui.activate.activate",
            return_value={"active_version_id": "ver_1"},
        ) as act:
            result = CliRunner().invoke(ui_group, ["activate", "demo", "1"])
        self.assertEqual(result.exit_code, 0, result.output)
        act.assert_called_once_with("art_1", 1)

    def test_disable_and_enable(self):
        with patch(
            "yagent.commands.ui.enable.resolve_artifact",
            return_value={"artifact_id": "art_1", "slug": "demo"},
        ), patch(
            "yagent.commands.ui.enable.set_enabled",
            side_effect=[
                {"enabled": False},
                {"enabled": True},
            ],
        ) as se:
            r1 = CliRunner().invoke(ui_group, ["disable", "demo"])
            r2 = CliRunner().invoke(ui_group, ["enable", "demo"])
        self.assertEqual(r1.exit_code, 0, r1.output)
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertEqual(se.call_args_list[0].args, ("art_1", False))
        self.assertEqual(se.call_args_list[1].args, ("art_1", True))


class UiDeleteTest(unittest.TestCase):
    def test_delete_with_yes_skips_prompt_and_prints_local_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.ui.delete.resolve_artifact",
                     return_value={"artifact_id": "art_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.ui.delete.delete_artifact",
                     return_value={"artifact_id": "art_1", "slug": "demo", "deleted_versions": 2},
                 ) as del_fn:
                result = CliRunner().invoke(ui_group, ["delete", "demo", "--yes"])
                expected_source = source_path("demo")
                expected_meta = meta_path("demo")
        self.assertEqual(result.exit_code, 0, result.output)
        del_fn.assert_called_once_with("art_1")
        self.assertIn("Deleted demo", result.output)
        self.assertIn(str(expected_source), result.output)
        self.assertIn(str(expected_meta), result.output)

    def test_delete_without_yes_prompts_and_aborts_on_no(self):
        with patch(
            "yagent.commands.ui.delete.resolve_artifact",
            return_value={"artifact_id": "art_1", "slug": "demo"},
        ), patch("yagent.commands.ui.delete.delete_artifact") as del_fn:
            result = CliRunner().invoke(ui_group, ["delete", "demo"], input="n\n")
        self.assertNotEqual(result.exit_code, 0)
        del_fn.assert_not_called()

    def test_delete_unknown_artifact_fails(self):
        with patch("yagent.commands.ui.delete.resolve_artifact", return_value=None):
            result = CliRunner().invoke(ui_group, ["delete", "demo", "--yes"])
        self.assertNotEqual(result.exit_code, 0)


class PublishApiShapeTest(unittest.TestCase):
    def test_publish_bundle_sends_multipart_fields(self):
        from yagent.commands.ui import _api

        with patch("yagent.commands.ui._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                artifact_id="art_1",
                bundle_bytes=b"export default 1;",
                sha256="x" * 64,
                label="Demo",
                icon="box",
                min_host_version=1,
                source_digest="y" * 64,
                activate=True,
            )
        args, kwargs = api.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "/api/ui/publish")
        self.assertIn("files", kwargs)
        self.assertEqual(kwargs["files"]["file"][0], "bundle.js")
        self.assertEqual(kwargs["data"]["artifact_id"], "art_1")
        self.assertEqual(kwargs["data"]["sha256"], "x" * 64)
        self.assertEqual(kwargs["data"]["activate"], "true")
        self.assertEqual(kwargs["data"]["label"], "Demo")
        self.assertNotIn("description", kwargs["data"])

    def test_publish_bundle_includes_description_only_when_given(self):
        from yagent.commands.ui import _api

        with patch("yagent.commands.ui._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                artifact_id="art_1",
                bundle_bytes=b"export default 1;",
                sha256="x" * 64,
                label="Demo",
                icon="box",
                min_host_version=1,
                source_digest="y" * 64,
                activate=True,
                description="[2991] fix overflow",
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["description"], "[2991] fix overflow")


class ComposeDescriptionTest(unittest.TestCase):
    def test_compose_description_d2_table(self):
        from yagent.commands.ui.publish import _compose_description

        self.assertEqual(
            _compose_description("fix chart overflow", "2991"), "[2991] fix chart overflow"
        )
        self.assertEqual(_compose_description(None, "2991"), "[2991]")
        self.assertEqual(_compose_description("fix chart overflow", None), "fix chart overflow")
        self.assertIsNone(_compose_description(None, None))


if __name__ == "__main__":
    unittest.main()
