"""Unit tests for `y module` (todo 2412 origin, renamed under todo 3020 phase 1).

API and the node build are mocked; SDK package data and scaffolding are real.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from yagent.commands.module.click import module_group
from yagent.commands.module._paths import (
    SLUG_RE,
    meta_path,
    modules_dir,
    source_dir,
    source_path,
    validate_slug,
)
from yagent.commands.module._sdk import (
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


class ModuleGroupHelpTest(unittest.TestCase):
    def test_group_help_lists_commands(self):
        result = CliRunner().invoke(module_group, ["--help"])
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
    """CLI slug rule must match api/controller/module.py SLUG_RE exactly."""

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


class ModuleSourceLayoutTest(unittest.TestCase):
    def test_modules_dir_has_no_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict(
                "os.environ",
                {"Y_AGENT_HOME": str(home), "Y_AGENT_MODULES_DIR": "/tmp/elsewhere"},
            ):
                self.assertEqual(modules_dir(), home / "modules")


class SdkRefreshTest(unittest.TestCase):
    def test_ensure_sdk_refreshes_when_packaged_content_changes(self):
        """A fix to build.mjs (no contract bump) must re-materialize ~/ui/.sdk."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"):
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
                        "yagent.commands.module._sdk.package_sdk_root",
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
                 patch("yagent.commands.module._sdk._ensure_npm_install"):
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


class ModuleCreateTest(unittest.TestCase):
    def test_create_scaffolds_source_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ) as create_fn:
                result = CliRunner().invoke(module_group, ["create", "demo"])

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(source_path("demo").is_file())
                meta = json.loads(meta_path("demo").read_text(encoding="utf-8"))
                self.assertEqual(meta["label"], "Demo")
                self.assertEqual(meta["icon"], "box")
                create_fn.assert_called_once_with("demo")
                self.assertEqual(source_path("demo"), home / "modules" / "demo" / "ui" / "index.tsx")
                self.assertEqual(meta_path("demo"), home / "modules" / "demo" / "module.json")
                self.assertTrue(source_dir("demo").is_dir())
                # SDK materialized
                self.assertTrue((modules_dir() / ".sdk" / "build.mjs").is_file())
                self.assertTrue((modules_dir() / ".sdk" / "shims" / "react.cjs").is_file())
                self.assertTrue((modules_dir() / ".sdk" / _DIGEST_MARKER).is_file())

    def test_create_rejects_invalid_slug(self):
        result = CliRunner().invoke(module_group, ["create", "Bad Slug"])
        self.assertNotEqual(result.exit_code, 0)
        result2 = CliRunner().invoke(module_group, ["create", "demo_panel"])
        self.assertNotEqual(result2.exit_code, 0)

    def test_create_accepts_digit_start_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_9", "slug": "9lives"},
                 ):
                result = CliRunner().invoke(module_group, ["create", "9lives"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(source_path("9lives").is_file())

    def test_create_no_register_skips_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module") as resolve_fn, \
                 patch("yagent.commands.module.create.create_module") as create_fn:
                result = CliRunner().invoke(
                    module_group, ["create", "local-only", "--no-register"]
                )
                self.assertEqual(result.exit_code, 0, result.output)
                resolve_fn.assert_not_called()
                create_fn.assert_not_called()
                self.assertTrue(source_path("local-only").is_file())


class ModuleListTest(unittest.TestCase):
    def test_list_prints_active_version(self):
        payload = [
            {
                "slug": "finance",
                "module_id": "mod_a",
                "enabled": True,
                "active_version_id": "ver_1",
                "active_version": {
                    "version_no": 2,
                    "label": "Finance",
                    "version_id": "ver_1",
                },
            }
        ]
        with patch("yagent.commands.module.list.list_modules", return_value=payload):
            result = CliRunner().invoke(module_group, ["list"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("finance", result.output)
        self.assertIn("v2", result.output)


class ModuleVersionsDescriptionTest(unittest.TestCase):
    def test_versions_shows_description_when_present_and_omits_none(self):
        payload_versions = [
            {
                "version_id": "ver_2",
                "version_no": 2,
                "ui_sha256": "b" * 64,
                "label": "Demo",
                "built_at": "2026-07-31T00:00:00Z",
                "description": "[2991] fix overflow",
            },
            {
                "version_id": "ver_1",
                "version_no": 1,
                "ui_sha256": "a" * 64,
                "label": "Demo",
                "built_at": "2026-07-30T00:00:00Z",
                "description": None,
            },
        ]
        with patch(
            "yagent.commands.module.versions.resolve_module",
            return_value={"module_id": "mod_1", "slug": "demo", "active_version_id": "ver_2"},
        ), patch(
            "yagent.commands.module.versions.list_versions",
            return_value=payload_versions,
        ):
            result = CliRunner().invoke(module_group, ["versions", "demo"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("[2991] fix overflow", result.output)
        v1_line = next(line for line in result.output.splitlines() if "v1" in line)
        self.assertNotIn("None", v1_line)


def _scaffold_ui(slug: str, home: Path) -> None:
    """Create the minimum source tree so publish sees a UI half."""
    ui = home / "modules" / slug / "ui"
    ui.mkdir(parents=True, exist_ok=True)
    (ui / "index.tsx").write_text("export const panel = () => null;\n", encoding="utf-8")
    meta_path(slug).write_text(
        json.dumps({"label": slug.title(), "icon": "box"}), encoding="utf-8"
    )


class ModulePublishTest(unittest.TestCase):
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
                     "yagent.commands.module.publish.build_artifact",
                     return_value=manifest,
                 ), \
                 patch(
                     "yagent.commands.module.publish.build_api_bundle",
                     return_value=None,
                 ), \
                 patch(
                     "yagent.commands.module.publish.resolve_or_create",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.publish.publish_bundle",
                     return_value={
                         "version_no": 3,
                         "ui_sha256": manifest["sha256"],
                         "version_id": "ver_3",
                     },
                 ) as pub:
                _scaffold_ui("demo", home)
                result = CliRunner().invoke(module_group, ["publish", "demo"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("v3", result.output)
            self.assertIn("active", result.output)
            kwargs = pub.call_args.kwargs
            self.assertEqual(kwargs["module_id"], "mod_1")
            self.assertEqual(kwargs["sha256"], manifest["sha256"])
            self.assertEqual(kwargs["label"], "Demo")
            self.assertTrue(kwargs["activate"])
            self.assertEqual(kwargs["bundle_bytes"], bundle.read_bytes())
            self.assertIsNone(kwargs["api_bundle_bytes"])

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
                     "yagent.commands.module.publish.build_artifact",
                     return_value=manifest,
                 ), \
                 patch(
                     "yagent.commands.module.publish.build_api_bundle",
                     return_value=None,
                 ), \
                 patch(
                     "yagent.commands.module.publish.resolve_or_create",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.publish.publish_bundle",
                     return_value={"version_no": 1, "ui_sha256": "a" * 64},
                 ) as pub:
                _scaffold_ui("demo", home)
                result = CliRunner().invoke(
                    module_group, ["publish", "demo", "--no-activate"]
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
                     "yagent.commands.module.publish.build_artifact",
                     return_value=manifest,
                 ), \
                 patch(
                     "yagent.commands.module.publish.build_api_bundle",
                     return_value=None,
                 ), \
                 patch(
                     "yagent.commands.module.publish.resolve_or_create",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.publish.publish_bundle",
                     return_value={"version_no": 1, "ui_sha256": "a" * 64},
                 ) as pub:
                _scaffold_ui("demo", home)
                result = CliRunner().invoke(
                    module_group, ["publish", "demo", "-d", "fix overflow"]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(pub.call_args.kwargs["description"], "[2991] fix overflow")

    def test_publish_build_failure_exits_nonzero_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.module.publish.build_artifact",
                     side_effect=RuntimeError("ERROR: Unexpected \")\""),
                 ), \
                 patch("yagent.commands.module.publish.build_api_bundle") as api_fn, \
                 patch("yagent.commands.module.publish.resolve_or_create") as resolve_fn, \
                 patch("yagent.commands.module.publish.publish_bundle") as pub_fn:
                _scaffold_ui("demo", home)
                result = CliRunner().invoke(module_group, ["publish", "demo"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Unexpected", result.output + (result.stderr or ""))
            resolve_fn.assert_not_called()
            pub_fn.assert_not_called()
            api_fn.assert_not_called()

    def test_publish_sends_both_halves_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ui_bundle = Path(tmp) / "bundle.js"
            ui_bundle.write_bytes(b"export default 1;")
            api_bundle = Path(tmp) / "bundle.api.zip"
            api_bundle.write_bytes(b"PK\x03\x04fakezip")
            ui_manifest = {
                "slug": "demo",
                "sha256": "u" * 64,
                "source_digest": "s" * 64,
                "min_host_version": 4,
                "bytes": ui_bundle.stat().st_size,
                "bundle": str(ui_bundle),
            }
            api_manifest = {
                "slug": "demo",
                "sha256": "a" * 64,
                "bytes": api_bundle.stat().st_size,
                "bundle": str(api_bundle),
                "entries": ["__init__.py", "api.py"],
            }
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.module.publish.build_artifact",
                     return_value=ui_manifest,
                 ), \
                 patch(
                     "yagent.commands.module.publish.build_api_bundle",
                     return_value=api_manifest,
                 ), \
                 patch(
                     "yagent.commands.module.publish.resolve_or_create",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.publish.publish_bundle",
                     return_value={
                         "version_no": 5,
                         "ui_sha256": "u" * 64,
                         "api_sha256": "a" * 64,
                     },
                 ) as pub:
                _scaffold_ui("demo", home)
                (home / "modules" / "demo" / "api.py").write_text(
                    "from fastapi import APIRouter\nrouter = APIRouter()\n",
                    encoding="utf-8",
                )
                meta_path("demo").write_text(
                    json.dumps({
                        "label": "Demo",
                        "icon": "box",
                        "min_backend_version": 1,
                    }),
                    encoding="utf-8",
                )
                result = CliRunner().invoke(module_group, ["publish", "demo"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("v5", result.output)
            kwargs = pub.call_args.kwargs
            self.assertEqual(kwargs["sha256"], "u" * 64)
            self.assertEqual(kwargs["api_sha256"], "a" * 64)
            self.assertEqual(kwargs["bundle_bytes"], ui_bundle.read_bytes())
            self.assertEqual(kwargs["api_bundle_bytes"], api_bundle.read_bytes())
            self.assertEqual(kwargs["min_backend_version"], 1)


class ModulePointerCommandsTest(unittest.TestCase):
    def test_rollback_resolves_slug(self):
        with patch(
            "yagent.commands.module.rollback.resolve_module",
            return_value={"module_id": "mod_1", "slug": "demo"},
        ), patch(
            "yagent.commands.module.rollback.rollback",
            return_value={"active_version_id": "ver_prev"},
        ) as rb:
            result = CliRunner().invoke(module_group, ["rollback", "demo"])
        self.assertEqual(result.exit_code, 0, result.output)
        rb.assert_called_once_with("mod_1")

    def test_activate_by_number(self):
        with patch(
            "yagent.commands.module.activate.resolve_module",
            return_value={"module_id": "mod_1", "slug": "demo"},
        ), patch(
            "yagent.commands.module.activate.activate",
            return_value={"active_version_id": "ver_1"},
        ) as act:
            result = CliRunner().invoke(module_group, ["activate", "demo", "1"])
        self.assertEqual(result.exit_code, 0, result.output)
        act.assert_called_once_with("mod_1", 1)

    def test_disable_and_enable(self):
        with patch(
            "yagent.commands.module.enable.resolve_module",
            return_value={"module_id": "mod_1", "slug": "demo"},
        ), patch(
            "yagent.commands.module.enable.set_enabled",
            side_effect=[
                {"enabled": False},
                {"enabled": True},
            ],
        ) as se:
            r1 = CliRunner().invoke(module_group, ["disable", "demo"])
            r2 = CliRunner().invoke(module_group, ["enable", "demo"])
        self.assertEqual(r1.exit_code, 0, r1.output)
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertEqual(se.call_args_list[0].args, ("mod_1", False))
        self.assertEqual(se.call_args_list[1].args, ("mod_1", True))


class ModuleDeleteTest(unittest.TestCase):
    def test_delete_with_yes_skips_prompt_and_prints_local_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch(
                     "yagent.commands.module.delete.resolve_module",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.delete.delete_module",
                     return_value={"module_id": "mod_1", "slug": "demo", "deleted_versions": 2},
                 ) as del_fn:
                result = CliRunner().invoke(module_group, ["delete", "demo", "--yes"])
                expected_source = source_dir("demo")
        self.assertEqual(result.exit_code, 0, result.output)
        del_fn.assert_called_once_with("mod_1")
        self.assertIn("Deleted demo", result.output)
        self.assertIn(str(expected_source), result.output)

    def test_delete_without_yes_prompts_and_aborts_on_no(self):
        with patch(
            "yagent.commands.module.delete.resolve_module",
            return_value={"module_id": "mod_1", "slug": "demo"},
        ), patch("yagent.commands.module.delete.delete_module") as del_fn:
            result = CliRunner().invoke(module_group, ["delete", "demo"], input="n\n")
        self.assertNotEqual(result.exit_code, 0)
        del_fn.assert_not_called()

    def test_delete_unknown_module_fails(self):
        with patch("yagent.commands.module.delete.resolve_module", return_value=None):
            result = CliRunner().invoke(module_group, ["delete", "demo", "--yes"])
        self.assertNotEqual(result.exit_code, 0)


class PublishApiShapeTest(unittest.TestCase):
    def test_publish_bundle_sends_multipart_fields(self):
        from yagent.commands.module import _api

        with patch("yagent.commands.module._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                module_id="mod_1",
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
        self.assertEqual(args[1], "/api/module/publish")
        self.assertIn("files", kwargs)
        self.assertEqual(kwargs["files"]["file"][0], "bundle.js")
        self.assertEqual(kwargs["data"]["module_id"], "mod_1")
        self.assertEqual(kwargs["data"]["sha256"], "x" * 64)
        self.assertEqual(kwargs["data"]["activate"], "true")
        self.assertEqual(kwargs["data"]["label"], "Demo")
        self.assertEqual(kwargs["data"]["min_host_version"], "1")
        self.assertNotIn("min_backend_version", kwargs["data"])
        self.assertNotIn("description", kwargs["data"])

    def test_publish_bundle_includes_min_backend_version_only_when_given(self):
        from yagent.commands.module import _api

        with patch("yagent.commands.module._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                module_id="mod_1",
                bundle_bytes=b"export default 1;",
                sha256="x" * 64,
                label="Demo",
                icon="box",
                min_host_version=1,
                min_backend_version=2,
                source_digest="y" * 64,
                activate=True,
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["min_backend_version"], "2")

    def test_publish_bundle_includes_description_only_when_given(self):
        from yagent.commands.module import _api

        with patch("yagent.commands.module._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                module_id="mod_1",
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
        from yagent.commands.module.publish import _compose_description

        self.assertEqual(
            _compose_description("fix chart overflow", "2991"), "[2991] fix chart overflow"
        )
        self.assertEqual(_compose_description(None, "2991"), "[2991]")
        self.assertEqual(_compose_description("fix chart overflow", None), "fix chart overflow")
        self.assertIsNone(_compose_description(None, None))


if __name__ == "__main__":
    unittest.main()


class ApiZipBuildTest(unittest.TestCase):
    def test_api_zip_is_deterministic_and_vendors_common(self):
        from yagent.commands.module._build import build_api_bundle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}):
                root = home / "modules" / "consumer"
                root.mkdir(parents=True)
                (root / "__init__.py").write_text("# empty\n", encoding="utf-8")
                (root / "api.py").write_text(
                    "from fastapi import APIRouter\nfrom .common import x\nrouter = APIRouter()\n",
                    encoding="utf-8",
                )
                (root / "ui").mkdir()
                (root / "ui" / "index.tsx").write_text("export const panel = 1\n", encoding="utf-8")
                (root / "tests").mkdir()
                (root / "tests" / "test_x.py").write_text("assert True\n", encoding="utf-8")
                (root / "migration").mkdir()
                (root / "migration" / "001.sql").write_text("SELECT 1;\n", encoding="utf-8")

                common = home / "modules" / "common"
                common.mkdir(parents=True)
                (common / "__init__.py").write_text("x = 1\n", encoding="utf-8")
                (common / "util.py").write_text("y = 2\n", encoding="utf-8")

                first = build_api_bundle("consumer")
                second = build_api_bundle("consumer")
                self.assertIsNotNone(first)
                self.assertEqual(first["sha256"], second["sha256"])
                self.assertEqual(first["bytes"], second["bytes"])
                self.assertIn("api.py", first["entries"])
                self.assertIn("common/__init__.py", first["entries"])
                self.assertIn("common/util.py", first["entries"])
                # Excluded trees must not appear.
                self.assertFalse(any(e.startswith("ui/") for e in first["entries"]))
                self.assertFalse(any(e.startswith("tests/") for e in first["entries"]))
                self.assertFalse(any(e.startswith("migration/") for e in first["entries"]))

                # common's own zip must not re-vendor itself.
                (common / "api.py").write_text(
                    "from fastapi import APIRouter\nrouter = APIRouter()\n",
                    encoding="utf-8",
                )
                common_manifest = build_api_bundle("common")
                self.assertIsNotNone(common_manifest)
                self.assertFalse(
                    any(e.startswith("common/") for e in common_manifest["entries"])
                )

    def test_api_zip_absent_when_no_api_py(self):
        from yagent.commands.module._build import build_api_bundle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}):
                root = home / "modules" / "ui-only"
                root.mkdir(parents=True)
                (root / "ui").mkdir()
                (root / "ui" / "index.tsx").write_text("export const panel = 1\n", encoding="utf-8")
                self.assertIsNone(build_api_bundle("ui-only"))


class LocalCommonInjectionTest(unittest.TestCase):
    def test_local_cli_imports_common_without_publish(self):
        import sys
        from yagent.commands.module._local import import_local_cli, package_name_for

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}):
                common = home / "modules" / "common"
                common.mkdir(parents=True)
                (common / "__init__.py").write_text("FLAG = 'from-common'\n", encoding="utf-8")

                root = home / "modules" / "consumer"
                root.mkdir(parents=True)
                (root / "__init__.py").write_text("# empty\n", encoding="utf-8")
                (root / "cli.py").write_text(
                    "from .common import FLAG\n"
                    "VALUE = FLAG\n",
                    encoding="utf-8",
                )
                try:
                    cli_mod = import_local_cli("consumer")
                    self.assertEqual(cli_mod.VALUE, "from-common")
                finally:
                    pkg = package_name_for("consumer")
                    for key in list(sys.modules):
                        if key == pkg or key.startswith(pkg + "."):
                            sys.modules.pop(key, None)


class CreateScaffoldsEmptyInitTest(unittest.TestCase):
    def test_create_writes_empty_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"Y_AGENT_HOME": str(home)}), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ):
                result = CliRunner().invoke(module_group, ["create", "demo", "--no-register"])
            self.assertEqual(result.exit_code, 0, result.output)
            init_py = home / "modules" / "demo" / "__init__.py"
            self.assertTrue(init_py.is_file())
            body = init_py.read_text(encoding="utf-8")
            self.assertNotIn("import", body)
