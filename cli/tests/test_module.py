"""Unit tests for `y module` (todo 2412 origin, renamed under todo 3020 phase 1).

API and the node build are mocked; SDK package data and scaffolding are real.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from yagent.commands.module.click import module_group
from yagent.commands.module._paths import (
    MODULE_SOURCE_ROOT,
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


def _source_root(path: Path):
    """Patch the fixed module source root to a temp dir for a test."""
    return patch("yagent.commands.module._paths.MODULE_SOURCE_ROOT", path)


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
        self.assertEqual(contract["version"], 7)
        self.assertIn("react", contract["externals"])
        self.assertIn("@y/host", contract["externals"])
        self.assertIn("lightweight-charts", contract["externals"])
        self.assertIn("swr/infinite", contract["externals"])
        self.assertIn("react-markdown", contract["externals"])
        self.assertIn("remark-gfm", contract["externals"])
        # F1/F2 markers must stay in the build recipe.
        build = (root / "build.mjs").read_text(encoding="utf-8")
        self.assertIn("theme(reference)", build)
        self.assertIn("source(none)", build)
        self.assertIn("@scope", build)
        self.assertIn("hoistAtProperty", build)

    def test_build_mjs_alias_keys_equal_contract_externals(self):
        """The esbuild `alias` map in build.mjs must cover exactly the same
        specifiers as contract.json's externals list (minus none, plus none).
        A specifier added to one and not the other either leaves a bare
        import in the bundle (missing alias) or an unused shim (missing
        external) — this is the drift guard V2 asked for.
        """
        root = package_sdk_root()
        contract = load_contract()
        build = (root / "build.mjs").read_text(encoding="utf-8")

        alias_block_start = build.index("alias: {")
        alias_block_end = build.index("},", alias_block_start)
        alias_block = build[alias_block_start:alias_block_end]
        alias_keys = set(re.findall(r'(?:"([^"]+)"|([\w$]+)):\s*shim\(', alias_block))
        alias_keys = {a or b for a, b in alias_keys}

        self.assertEqual(alias_keys, set(contract["externals"]))

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
            "usePanelLocation",
            "runHostCommand",
            "optimisticListMutate",
            "ArtifactView",
            "PatchDiff",
            "ImageLightbox",
            "CodeEditor",
            "remarkStripComments",
            "parseLocalFileReference",
            "normalizeLinks",
            "citationDomain",
            "citationHostname",
            "exportElementToPng",
            "deliverPng",
            "buildExportFilename",
            "pickImageDelivery",
            "parseRawChatMessage",
            "parseChatMessages",
            "mergeToolResult",
            "mergeToolArguments",
            "filterTrailingEmptyAssistantMessages",
            "extractContent",
            "toggleSelection",
            "selectMessagesByIndices",
            "getToken",
            "stripTracePrefix",
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
    def test_modules_dir_is_the_fixed_constant(self):
        self.assertEqual(modules_dir(), MODULE_SOURCE_ROOT)
        self.assertEqual(MODULE_SOURCE_ROOT, Path("/Users/roy/luohy15/code/y-module"))

    def test_modules_dir_ignores_env_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict(
                "os.environ",
                {"Y_AGENT_HOME": str(home), "Y_AGENT_MODULES_DIR": "/tmp/elsewhere"},
            ):
                self.assertEqual(modules_dir(), MODULE_SOURCE_ROOT)
                self.assertNotEqual(modules_dir(), home / "modules")
                self.assertNotEqual(modules_dir(), Path("/tmp/elsewhere"))


class SdkRefreshTest(unittest.TestCase):
    def test_ensure_sdk_refreshes_when_packaged_content_changes(self):
        """A fix to build.mjs (no contract bump) must re-materialize ~/ui/.sdk."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home), \
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
            with _source_root(home), \
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
            with _source_root(home), \
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
                self.assertEqual(source_path("demo"), home / "demo" / "ui" / "index.tsx")
                self.assertEqual(meta_path("demo"), home / "demo" / "module.json")
                self.assertTrue(source_dir("demo").is_dir())
                # SDK materialized
                self.assertTrue((modules_dir() / ".sdk" / "build.mjs").is_file())
                self.assertTrue((modules_dir() / ".sdk" / "shims" / "react.cjs").is_file())
                self.assertTrue((modules_dir() / ".sdk" / _DIGEST_MARKER).is_file())

    def test_create_help_uses_contract_icon_keys(self):
        result = CliRunner().invoke(module_group, ["create", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        help_output = re.sub(r"-\s*\n\s*", "-", result.output)
        for icon in load_contract()["icons"]:
            self.assertIn(icon, help_output)

    def test_create_rejects_invalid_slug(self):
        result = CliRunner().invoke(module_group, ["create", "Bad Slug"])
        self.assertNotEqual(result.exit_code, 0)
        result2 = CliRunner().invoke(module_group, ["create", "demo_panel"])
        self.assertNotEqual(result2.exit_code, 0)

    def test_create_accepts_digit_start_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home), \
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
            with _source_root(home), \
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
    def test_versions_renders_trace_id_and_description_combinations(self):
        payload_versions = [
            {
                "version_id": "ver_3",
                "version_no": 3,
                "ui_sha256": "c" * 64,
                "label": "Demo",
                "built_at": "2026-08-01T00:00:00Z",
                "description": "fix overflow",
                "trace_id": "3051",
                "dispatch_scope": "authenticated",
            },
            {
                "version_id": "ver_2",
                "version_no": 2,
                "ui_sha256": "b" * 64,
                "label": "Demo",
                "built_at": "2026-07-31T00:00:00Z",
                "description": None,
                "trace_id": "2991",
            },
            {
                "version_id": "ver_1",
                "version_no": 1,
                "ui_sha256": "a" * 64,
                "label": "Demo",
                "built_at": "2026-07-30T00:00:00Z",
                "description": None,
                "trace_id": None,
            },
        ]
        with patch(
            "yagent.commands.module.versions.resolve_module",
            return_value={"module_id": "mod_1", "slug": "demo", "active_version_id": "ver_3"},
        ), patch(
            "yagent.commands.module.versions.list_versions",
            return_value=payload_versions,
        ):
            result = CliRunner().invoke(module_group, ["versions", "demo"])
        self.assertEqual(result.exit_code, 0, result.output)
        v3_line = next(line for line in result.output.splitlines() if "v3" in line)
        v2_line = next(line for line in result.output.splitlines() if "v2" in line)
        v1_line = next(line for line in result.output.splitlines() if "v1" in line)
        self.assertIn("[3051] fix overflow", v3_line)
        self.assertIn("authenticated", v3_line)
        self.assertIn("[2991]", v2_line)
        self.assertNotIn("[", v1_line)
        # Missing dispatch_scope falls back to the default maintainer audience.
        self.assertIn("maintainer", v1_line)
        self.assertNotIn("None", v1_line)


def _scaffold_ui(slug: str, home: Path) -> None:
    """Create the minimum source tree so publish sees a UI half."""
    ui = home / slug / "ui"
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
            with _source_root(home), \
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
                result = CliRunner().invoke(module_group, ["publish", "demo", "--icon", "file"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("v3", result.output)
            self.assertIn("active", result.output)
            kwargs = pub.call_args.kwargs
            self.assertEqual(kwargs["module_id"], "mod_1")
            self.assertEqual(kwargs["sha256"], manifest["sha256"])
            self.assertEqual(kwargs["label"], "Demo")
            self.assertEqual(kwargs["icon"], "file")
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
            with _source_root(home), \
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

    def test_publish_desc_flag_is_not_prefixed(self):
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
            with _source_root(home), \
                 patch.dict("os.environ", {"Y_TRACE_ID": "2991"}), \
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
            self.assertEqual(pub.call_args.kwargs["description"], "fix overflow")
            self.assertEqual(pub.call_args.kwargs["trace_id"], "2991")

    def test_publish_trace_id_defaults_from_env(self):
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
            with _source_root(home), \
                 patch.dict("os.environ", {"Y_TRACE_ID": "3051"}), \
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
                result = CliRunner().invoke(module_group, ["publish", "demo"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(pub.call_args.kwargs["trace_id"], "3051")

    def test_publish_trace_id_flag_overrides_env(self):
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
            with _source_root(home), \
                 patch.dict("os.environ", {"Y_TRACE_ID": "2991"}), \
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
                    module_group, ["publish", "demo", "--trace-id", "3051"]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(pub.call_args.kwargs["trace_id"], "3051")

    def test_publish_no_trace_id_when_unset(self):
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
            import os

            env = dict(os.environ)
            env.pop("Y_TRACE_ID", None)
            with _source_root(home), \
                 patch.dict("os.environ", env, clear=True), \
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
                result = CliRunner().invoke(module_group, ["publish", "demo"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIsNone(pub.call_args.kwargs["trace_id"])

    def test_publish_build_failure_exits_nonzero_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home), \
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
            with _source_root(home), \
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
                (home / "demo" / "api.py").write_text(
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
            self.assertEqual(kwargs["dispatch_scope"], "maintainer")

    def test_publish_rejects_invalid_dispatch_metadata_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module_dir = home / "demo"
            module_dir.mkdir(parents=True)
            (module_dir / "module.json").write_text(
                json.dumps({"dispatch": "public"}), encoding="utf-8"
            )
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact") as ui_fn, \
                 patch("yagent.commands.module.publish.build_api_bundle") as api_fn:
                result = CliRunner().invoke(module_group, ["publish", "demo"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("dispatch must be", result.output)
        ui_fn.assert_not_called()
        api_fn.assert_not_called()

    def test_publish_rejects_invalid_surfaces_metadata_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module_dir = home / "demo"
            module_dir.mkdir(parents=True)
            (module_dir / "module.json").write_text(
                json.dumps({"surfaces": ["panel", "tab"]}), encoding="utf-8"
            )
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact") as ui_fn, \
                 patch("yagent.commands.module.publish.build_api_bundle") as api_fn:
                result = CliRunner().invoke(module_group, ["publish", "demo"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("surfaces must only contain", result.output)
        ui_fn.assert_not_called()
        api_fn.assert_not_called()

    def test_publish_rejects_non_boolean_ui_public_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module_dir = home / "demo"
            module_dir.mkdir(parents=True)
            (module_dir / "module.json").write_text(
                json.dumps({"ui_public": "yes"}), encoding="utf-8"
            )
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact") as ui_fn, \
                 patch("yagent.commands.module.publish.build_api_bundle") as api_fn:
                result = CliRunner().invoke(module_group, ["publish", "demo"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("ui_public must be a boolean", result.output)
        ui_fn.assert_not_called()
        api_fn.assert_not_called()

    def test_publish_rejects_unknown_icon_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module_dir = home / "demo"
            module_dir.mkdir(parents=True)
            (module_dir / "module.json").write_text(
                json.dumps({"icon": "unknown"}), encoding="utf-8"
            )
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact") as ui_fn, \
                 patch("yagent.commands.module.publish.build_api_bundle") as api_fn:
                result = CliRunner().invoke(module_group, ["publish", "demo"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("module icon must be one of", result.output)
        self.assertIn("file-text", result.output)
        ui_fn.assert_not_called()
        api_fn.assert_not_called()

    def test_publish_rejects_unknown_icon_override_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            module_dir = home / "demo"
            module_dir.mkdir(parents=True)
            (module_dir / "module.json").write_text(
                json.dumps({"icon": "file"}), encoding="utf-8"
            )
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact") as ui_fn, \
                 patch("yagent.commands.module.publish.build_api_bundle") as api_fn:
                result = CliRunner().invoke(
                    module_group, ["publish", "demo", "--icon", "unknown"]
                )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("module icon must be one of", result.output)
        self.assertIn("got 'unknown'", result.output)
        ui_fn.assert_not_called()
        api_fn.assert_not_called()

    def test_publish_surfaces_and_ui_public_default_and_deduped_from_module_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle = Path(tmp) / "bundle.js"
            bundle.write_bytes(b"export default 1;\nexport const shell = 2;\n")
            manifest = {
                "slug": "demo",
                "sha256": "abc123" + "0" * 58,
                "source_digest": "src" + "0" * 61,
                "min_host_version": 1,
                "bytes": bundle.stat().st_size,
                "bundle": str(bundle),
            }
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact", return_value=manifest), \
                 patch("yagent.commands.module.publish.build_api_bundle", return_value=None), \
                 patch(
                     "yagent.commands.module.publish.resolve_or_create",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.publish.publish_bundle",
                     return_value={"version_no": 1, "ui_sha256": manifest["sha256"], "version_id": "ver_1"},
                 ) as pub:
                _scaffold_ui("demo", home)
                meta_path("demo").write_text(
                    json.dumps({
                        "label": "Demo",
                        "surfaces": ["shell", "panel", "shell"],
                        "ui_public": True,
                    }),
                    encoding="utf-8",
                )
                result = CliRunner().invoke(module_group, ["publish", "demo"])
            self.assertEqual(result.exit_code, 0, result.output)
            kwargs = pub.call_args.kwargs
            self.assertEqual(kwargs["ui_surfaces"], "shell,panel")
            self.assertTrue(kwargs["ui_public"])

    def test_publish_defaults_surfaces_to_panel_and_ui_public_to_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bundle = Path(tmp) / "bundle.js"
            bundle.write_bytes(b"export default 1;\n")
            manifest = {
                "slug": "demo",
                "sha256": "abc123" + "0" * 58,
                "source_digest": "src" + "0" * 61,
                "min_host_version": 1,
                "bytes": bundle.stat().st_size,
                "bundle": str(bundle),
            }
            with _source_root(home), \
                 patch("yagent.commands.module.publish.build_artifact", return_value=manifest), \
                 patch("yagent.commands.module.publish.build_api_bundle", return_value=None), \
                 patch(
                     "yagent.commands.module.publish.resolve_or_create",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ), \
                 patch(
                     "yagent.commands.module.publish.publish_bundle",
                     return_value={"version_no": 1, "ui_sha256": manifest["sha256"], "version_id": "ver_1"},
                 ) as pub:
                _scaffold_ui("demo", home)
                result = CliRunner().invoke(module_group, ["publish", "demo"])
            self.assertEqual(result.exit_code, 0, result.output)
            kwargs = pub.call_args.kwargs
            self.assertEqual(kwargs["ui_surfaces"], "panel")
            self.assertFalse(kwargs["ui_public"])


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
            with _source_root(home), \
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

    def test_publish_bundle_defaults_dispatch_scope_to_maintainer(self):
        from yagent.commands.module import _api

        with patch("yagent.commands.module._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                module_id="mod_1",
                bundle_bytes=b"export default 1;",
                sha256="x" * 64,
                label="Demo",
                icon="box",
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["dispatch_scope"], "maintainer")

    def test_publish_bundle_defaults_ui_surfaces_and_ui_public(self):
        from yagent.commands.module import _api

        with patch("yagent.commands.module._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                module_id="mod_1",
                bundle_bytes=b"export default 1;",
                sha256="x" * 64,
                label="Demo",
                icon="box",
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["ui_surfaces"], "panel")
        self.assertEqual(kwargs["data"]["ui_public"], "false")

    def test_publish_bundle_sends_given_ui_surfaces_and_ui_public(self):
        from yagent.commands.module import _api

        with patch("yagent.commands.module._api.api_request") as api:
            api.return_value = _resp({"version_no": 1, "sha256": "x" * 64})
            _api.publish_bundle(
                module_id="mod_1",
                bundle_bytes=b"export default 1;",
                sha256="x" * 64,
                label="Demo",
                icon="box",
                ui_surfaces="panel,shell",
                ui_public=True,
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["ui_surfaces"], "panel,shell")
        self.assertEqual(kwargs["data"]["ui_public"], "true")

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
                description="fix overflow",
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["description"], "fix overflow")

    def test_publish_bundle_includes_trace_id_only_when_given(self):
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
                trace_id="3051",
            )
        _, kwargs = api.call_args
        self.assertEqual(kwargs["data"]["trace_id"], "3051")

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
        _, kwargs = api.call_args
        self.assertNotIn("trace_id", kwargs["data"])


if __name__ == "__main__":
    unittest.main()


class ApiZipBuildTest(unittest.TestCase):
    def test_api_zip_is_deterministic_and_vendors_common(self):
        from yagent.commands.module._build import build_api_bundle

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home):
                root = home / "consumer"
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

                common = home / "common"
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
            with _source_root(home):
                root = home / "ui-only"
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
            with _source_root(home):
                common = home / "common"
                common.mkdir(parents=True)
                (common / "__init__.py").write_text("FLAG = 'from-common'\n", encoding="utf-8")

                root = home / "consumer"
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
            with _source_root(home), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_1", "slug": "demo"},
                 ):
                result = CliRunner().invoke(module_group, ["create", "demo", "--no-register"])
            self.assertEqual(result.exit_code, 0, result.output)
            init_py = home / "demo" / "__init__.py"
            self.assertTrue(init_py.is_file())
            body = init_py.read_text(encoding="utf-8")
            self.assertNotIn("import", body)


class CreateScaffoldsDataLayerTest(unittest.TestCase):
    """Plan 4.1: `y module create` scaffolds the module's own DeclarativeBase,
    exported metadata, and hand-applied repository/migration READMEs."""

    def test_create_writes_entities_repository_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_1", "slug": "scratch-data"},
                 ):
                result = CliRunner().invoke(
                    module_group, ["create", "scratch-data", "--no-register"]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            root = home / "scratch-data"
            self.assertTrue((root / "entities" / "__init__.py").is_file())
            self.assertTrue((root / "entities" / "base.py").is_file())
            self.assertTrue((root / "repository" / "README.md").is_file())
            self.assertTrue((root / "migration" / "README.md").is_file())

            entities_init = (root / "entities" / "__init__.py").read_text(encoding="utf-8")
            self.assertIn("metadata", entities_init)
            base_py = (root / "entities" / "base.py").read_text(encoding="utf-8")
            self.assertIn("DeclarativeBase", base_py)
            self.assertNotIn("import storage.entity.base", base_py)
            self.assertNotIn("from storage.entity.base", base_py)

    def test_declared_table_isolated_from_host_metadata(self):
        """A table declared against the scaffolded Base is visible on the
        module's own metadata, and never on storage.entity.base.Base."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_1", "slug": "scratch-data"},
                 ):
                CliRunner().invoke(module_group, ["create", "scratch-data", "--no-register"])

            root = home / "scratch-data"
            (root / "__init__.py").write_text("# empty\n", encoding="utf-8")
            (root / "entities" / "widget.py").write_text(
                "from sqlalchemy import Column, Integer\n"
                "from .base import Base\n\n\n"
                "class Widget(Base):\n"
                "    __tablename__ = 'scratch_widget'\n"
                "    id = Column(Integer, primary_key=True)\n",
                encoding="utf-8",
            )
            init_text = (root / "entities" / "__init__.py").read_text(encoding="utf-8")
            (root / "entities" / "__init__.py").write_text(
                init_text.replace(
                    "from .base import Base  # noqa: F401",
                    "from .base import Base  # noqa: F401\nfrom . import widget  # noqa: F401",
                ),
                encoding="utf-8",
            )

            from yagent.commands.module._local import import_local_entities, package_name_for

            try:
                with _source_root(home):
                    entities_mod = import_local_entities("scratch-data")
                self.assertIn("scratch_widget", entities_mod.metadata.tables)

                import storage.entity.base as host_base

                self.assertNotIn("scratch_widget", host_base.Base.metadata.tables)
            finally:
                import sys

                pkg = package_name_for("scratch-data")
                for key in list(sys.modules):
                    if key == pkg or key.startswith(pkg + "."):
                        sys.modules.pop(key, None)


class SchemaSqlTest(unittest.TestCase):
    """Plan 4.2: `y module schema-sql <slug>` prints DDL, never touches a DB."""

    def _scaffold(self, home: Path, slug: str, table_sql: str | None) -> None:
        with _source_root(home), \
             patch("yagent.commands.module._sdk._ensure_npm_install"), \
             patch("yagent.commands.module.create.resolve_module", return_value=None), \
             patch(
                 "yagent.commands.module.create.create_module",
                 return_value={"module_id": "mod_1", "slug": slug},
             ):
            CliRunner().invoke(module_group, ["create", slug, "--no-register"])
        root = home / slug
        (root / "__init__.py").write_text("# empty\n", encoding="utf-8")
        if table_sql is not None:
            (root / "entities" / "widget.py").write_text(table_sql, encoding="utf-8")
            init_path = root / "entities" / "__init__.py"
            init_path.write_text(
                init_path.read_text(encoding="utf-8").replace(
                    "from .base import Base  # noqa: F401",
                    "from .base import Base  # noqa: F401\nfrom . import widget  # noqa: F401",
                ),
                encoding="utf-8",
            )

    def _cleanup_sys_modules(self, slug: str) -> None:
        import sys

        from yagent.commands.module._local import package_name_for

        pkg = package_name_for(slug)
        for key in list(sys.modules):
            if key == pkg or key.startswith(pkg + "."):
                sys.modules.pop(key, None)

    def test_prints_create_table_ddl_with_database_url_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._scaffold(
                home,
                "scratch-sql",
                "from sqlalchemy import Column, Integer, String\n"
                "from .base import Base\n\n\n"
                "class Widget(Base):\n"
                "    __tablename__ = 'scratch_widget'\n"
                "    id = Column(Integer, primary_key=True)\n"
                "    name = Column(String)\n",
            )
            import os

            env = dict(os.environ)
            env.pop("DATABASE_URL", None)
            env.pop("DATABASE_URL_DEV", None)
            try:
                with _source_root(home), patch.dict("os.environ", env, clear=True):
                    result = CliRunner().invoke(module_group, ["schema-sql", "scratch-sql"])
            finally:
                self._cleanup_sys_modules("scratch-sql")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("CREATE TABLE scratch_widget", result.output)
            self.assertIn("name", result.output)

    def test_external_reference_table_is_not_rendered(self):
        """A stub for a host kernel table resolves the FK but is never DDL'd."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._scaffold(
                home,
                "scratch-ext",
                "from agent.module_host import EXTERNAL_TABLE_INFO_KEY\n"
                "from sqlalchemy import Column, ForeignKey, Integer, Table\n"
                "from .base import Base\n\n\n"
                "Table('user', Base.metadata, Column('id', Integer, primary_key=True),\n"
                "      info={EXTERNAL_TABLE_INFO_KEY: True})\n\n\n"
                "class Widget(Base):\n"
                "    __tablename__ = 'scratch_widget'\n"
                "    id = Column(Integer, primary_key=True)\n"
                "    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'))\n",
            )
            try:
                with _source_root(home):
                    result = CliRunner().invoke(module_group, ["schema-sql", "scratch-ext"])
            finally:
                self._cleanup_sys_modules("scratch-ext")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("CREATE TABLE scratch_widget", result.output)
            self.assertIn('REFERENCES "user" (id) ON DELETE CASCADE', result.output)
            self.assertNotIn('CREATE TABLE "user"', result.output)

    def test_schema_sql_rejects_nonempty_root_before_cli_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "unsafe-root"
            (root / "entities").mkdir(parents=True)
            (root / "__init__.py").write_text(
                "from . import cli\n", encoding="utf-8"
            )
            (root / "cli.py").write_text(
                "raise RuntimeError('cli side effect must not run')\n", encoding="utf-8"
            )
            (root / "entities" / "__init__.py").write_text(
                "metadata = None\n", encoding="utf-8"
            )
            try:
                with _source_root(home):
                    result = CliRunner().invoke(module_group, ["schema-sql", "unsafe-root"])
                from yagent.commands.module._local import package_name_for

                pkg = package_name_for("unsafe-root")
                self.assertNotIn(pkg, sys.modules)
                self.assertNotIn(f"{pkg}.cli", sys.modules)
            finally:
                self._cleanup_sys_modules("unsafe-root")
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("must stay empty", result.output)
            self.assertNotIn("cli side effect", result.output)

    def test_module_with_no_entities_prints_nothing_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _source_root(home), \
                 patch("yagent.commands.module._sdk._ensure_npm_install"), \
                 patch("yagent.commands.module.create.resolve_module", return_value=None), \
                 patch(
                     "yagent.commands.module.create.create_module",
                     return_value={"module_id": "mod_1", "slug": "scratch-empty"},
                 ):
                CliRunner().invoke(module_group, ["create", "scratch-empty", "--no-register"])
            root = home / "scratch-empty"
            (root / "__init__.py").write_text("# empty\n", encoding="utf-8")
            import shutil as _shutil

            _shutil.rmtree(root / "entities")
            try:
                with _source_root(home):
                    result = CliRunner().invoke(module_group, ["schema-sql", "scratch-empty"])
            finally:
                self._cleanup_sys_modules("scratch-empty")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(result.output, "")


def _write_module_cli(
    home: Path,
    slug: str,
    *,
    cli_body: str,
    label: str | None = None,
    init_body: str = "# empty\n",
    module_json: bool = True,
) -> Path:
    root = home / slug
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text(init_body, encoding="utf-8")
    (root / "cli.py").write_text(cli_body, encoding="utf-8")
    if module_json:
        meta = {"label": label or slug.title(), "icon": "box", "parts": ["cli"]}
        (root / "module.json").write_text(json.dumps(meta), encoding="utf-8")
    return root


def _cleanup_ymod(slug: str) -> None:
    import sys

    from yagent.commands.module._local import package_name_for

    pkg = package_name_for(slug)
    for key in list(sys.modules):
        if key == pkg or key.startswith(pkg + "."):
            sys.modules.pop(key, None)


def _ymod_keys_in_sys_modules() -> list[str]:
    """Keys that look like local or published module packages."""
    return [k for k in sys.modules if k == "ymod" or k.startswith("ymod_")]


class LazyModuleDiscoveryTest(unittest.TestCase):
    """Plan 5.1: listdir + module.json only; no module Python on help path."""

    def test_discover_skips_dot_invalid_and_non_cli_entries(self):
        from yagent.commands.module._lazy import discover_module_slugs

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            modules = home
            # Dot entries (SDK + bak) must never become commands.
            (modules / ".sdk").mkdir()
            (modules / ".sdk-node_modules.bak").mkdir()
            # Invalid slug (underscore) and non-dir file.
            (modules / "bad_slug").mkdir()
            (modules / "bad_slug" / "module.json").write_text("{}", encoding="utf-8")
            (modules / "readme.txt").write_text("nope\n", encoding="utf-8")
            # UI-only: module.json but no cli.py.
            ui_only = modules / "ui-only"
            ui_only.mkdir()
            (ui_only / "module.json").write_text(
                json.dumps({"label": "UI Only", "icon": "box"}), encoding="utf-8"
            )
            # Valid CLI module.
            _write_module_cli(
                home,
                "good-mod",
                label="Good Mod",
                cli_body=(
                    "import click\n\n"
                    "@click.group('good-mod')\n"
                    "def group():\n"
                    "    '''Good.'''\n"
                    "    pass\n"
                ),
            )
            with _source_root(home):
                self.assertEqual(discover_module_slugs(), ["good-mod"])

    def test_help_lists_module_label_without_importing_cli(self):
        import sys

        from yagent.command_option import cli
        from yagent.commands.module._local import package_name_for

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "scratch-help",
                label="Scratch Help",
                cli_body=(
                    "import click\n"
                    "raise RuntimeError('cli must not import on --help')\n"
                ),
            )
            try:
                with _source_root(home):
                    before = set(_ymod_keys_in_sys_modules())
                    result = CliRunner().invoke(cli, ["--help"])
                    after = set(_ymod_keys_in_sys_modules())
            finally:
                _cleanup_ymod("scratch-help")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("scratch-help", result.output)
            self.assertIn("Scratch Help", result.output)
            # Help path must not leave any ymod_* import behind.
            self.assertEqual(after - before, set())
            self.assertNotIn(package_name_for("scratch-help"), sys.modules)

    def test_unrelated_command_does_not_import_module_cli(self):
        import sys

        from yagent.command_option import cli
        from yagent.commands.module._local import package_name_for

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "side-effect",
                label="Side Effect",
                cli_body=(
                    "import click\n"
                    "raise RuntimeError('side-effect module imported')\n"
                ),
            )
            try:
                with _source_root(home):
                    before = set(_ymod_keys_in_sys_modules())
                    # `todo --help` is a real built-in; resolving it must not
                    # import any module CLI package.
                    result = CliRunner().invoke(cli, ["todo", "--help"])
                    after = set(_ymod_keys_in_sys_modules())
            finally:
                _cleanup_ymod("side-effect")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(after - before, set())
            self.assertNotIn(package_name_for("side-effect"), sys.modules)
            self.assertNotIn(f"{package_name_for('side-effect')}.cli", sys.modules)


class LazyModuleInvocationTest(unittest.TestCase):
    """Plan 5.1/5.2: import on use, common injection, isolation, collision."""

    def test_module_command_loads_local_cli_and_common(self):
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            common = home / "common"
            common.mkdir(parents=True)
            (common / "__init__.py").write_text("FLAG = 'from-common'\n", encoding="utf-8")
            _write_module_cli(
                home,
                "consumer",
                label="Consumer",
                cli_body=(
                    "import click\n"
                    "from .common import FLAG\n\n"
                    "@click.group('consumer')\n"
                    "def group():\n"
                    "    '''Consumer module.'''\n"
                    "    pass\n\n"
                    "@group.command('ping')\n"
                    "def ping():\n"
                    "    click.echo(FLAG)\n"
                ),
            )
            try:
                with _source_root(home):
                    result = CliRunner().invoke(cli, ["consumer", "ping"])
            finally:
                _cleanup_ymod("consumer")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(result.output.strip(), "from-common")

    def test_broken_module_cli_does_not_break_built_ins(self):
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "broken",
                label="Broken",
                cli_body="raise RuntimeError('broken on purpose')\n",
            )
            try:
                with _source_root(home):
                    broken = CliRunner().invoke(cli, ["broken", "anything"])
                    # Built-in still works in the same process after the failure.
                    todo = CliRunner().invoke(cli, ["todo", "--help"])
            finally:
                _cleanup_ymod("broken")
            self.assertNotEqual(broken.exit_code, 0)
            self.assertIn("Failed to load CLI for module 'broken'", broken.output)
            self.assertIn("broken on purpose", broken.output)
            self.assertEqual(todo.exit_code, 0, todo.output)
            self.assertIn("Manage todos", todo.output)

    def test_built_in_wins_on_name_collision(self):
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            # A module that steals the built-in `todo` name must not be used.
            _write_module_cli(
                home,
                "todo",
                label="Shadow Todo",
                cli_body=(
                    "import click\n\n"
                    "@click.group('todo')\n"
                    "def group():\n"
                    "    '''Shadow.'''\n"
                    "    pass\n\n"
                    "@group.command('list')\n"
                    "def list_cmd():\n"
                    "    click.echo('SHADOW')\n"
                ),
            )
            try:
                with _source_root(home):
                    # Help still lists `todo` once (built-in), and the built-in
                    # help text is the one that appears.
                    help_result = CliRunner().invoke(cli, ["--help"])
                    todo_help = CliRunner().invoke(cli, ["todo", "--help"])
            finally:
                _cleanup_ymod("todo")
            self.assertEqual(help_result.exit_code, 0, help_result.output)
            self.assertEqual(help_result.output.count("  todo"), 1)
            self.assertNotIn("Shadow Todo", help_result.output)
            self.assertEqual(todo_help.exit_code, 0, todo_help.output)
            self.assertIn("Manage todos", todo_help.output)
            self.assertNotIn("SHADOW", todo_help.output)

    def test_module_without_group_export_errors_clearly(self):
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "nogroup",
                label="No Group",
                cli_body="VALUE = 1\n",
            )
            try:
                with _source_root(home):
                    result = CliRunner().invoke(cli, ["nogroup", "--help"])
            finally:
                _cleanup_ymod("nogroup")
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("must export `group`", result.output)

    def test_group_option_parses_and_reaches_callback(self):
        """Regression for F1: a group-level option must not be dropped."""
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "optmod",
                label="Opt Mod",
                cli_body=(
                    "import click\n\n"
                    "@click.group('optmod')\n"
                    "@click.option('--flavor', default='plain')\n"
                    "def group(flavor):\n"
                    "    click.echo(f'group={flavor}')\n\n"
                    "@group.command('sub')\n"
                    "def sub():\n"
                    "    click.echo('sub ran')\n"
                ),
            )
            try:
                with _source_root(home):
                    with_opt = CliRunner().invoke(
                        cli, ["optmod", "--flavor", "spicy", "sub"]
                    )
                    default = CliRunner().invoke(cli, ["optmod", "sub"])
            finally:
                _cleanup_ymod("optmod")
            self.assertEqual(with_opt.exit_code, 0, with_opt.output)
            self.assertIn("group=spicy", with_opt.output)
            self.assertIn("sub ran", with_opt.output)
            # No raw TypeError traceback; a missing option is a clean Click error.
            self.assertNotIn("TypeError", with_opt.output)
            self.assertEqual(default.exit_code, 0, default.output)
            self.assertNotIn("No such option", default.output)

    def test_help_lists_group_option_and_unknown_option_fails_cleanly(self):
        """Help advertises the option, and a bad value is a Click error, not
        a raw traceback."""
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "optmod",
                label="Opt Mod",
                cli_body=(
                    "import click\n\n"
                    "@click.group('optmod')\n"
                    "@click.option('--flavor', default='plain')\n"
                    "def group(flavor):\n"
                    "    pass\n\n"
                    "@group.command('sub')\n"
                    "def sub():\n"
                    "    pass\n"
                ),
            )
            try:
                with _source_root(home):
                    help_result = CliRunner().invoke(cli, ["optmod", "--help"])
                    bad = CliRunner().invoke(
                        cli, ["optmod", "--bogus", "sub"]
                    )
            finally:
                _cleanup_ymod("optmod")
            self.assertEqual(help_result.exit_code, 0, help_result.output)
            self.assertIn("--flavor", help_result.output)
            self.assertNotEqual(bad.exit_code, 0)
            self.assertIn("No such option: --bogus", bad.output)
            self.assertNotIn("Traceback", bad.output)

    def test_invoke_without_command_runs_group_callback(self):
        """Regression for F1: an invoke_without_command group runs its callback
        (not help) when invoked bare."""
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "iwcm",
                label="IWCM",
                cli_body=(
                    "import click\n\n"
                    "@click.group('iwcm', invoke_without_command=True)\n"
                    "def group():\n"
                    "    click.echo('group callback ran')\n\n"
                    "@group.command('ping')\n"
                    "def ping():\n"
                    "    click.echo('ping')\n"
                ),
            )
            try:
                with _source_root(home):
                    bare = CliRunner().invoke(cli, ["iwcm"])
                    sub = CliRunner().invoke(cli, ["iwcm", "ping"])
            finally:
                _cleanup_ymod("iwcm")
            self.assertEqual(bare.exit_code, 0, bare.output)
            self.assertEqual(bare.output.strip(), "group callback ran")
            self.assertEqual(sub.exit_code, 0, sub.output)
            self.assertIn("ping", sub.output)

    def test_group_callback_with_click_pass_context(self):
        """Context arrives through the delegated make_context (PRD story 27).

        A plain group only runs its callback when a subcommand follows, so
        invoke `sub`; the callback must receive a real context, not a
        positional-arg TypeError."""
        from yagent.command_option import cli

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_module_cli(
                home,
                "pcmod",
                label="Pc Mod",
                cli_body=(
                    "import click\n\n"
                    "@click.group('pcmod')\n"
                    "@click.pass_context\n"
                    "def group(ctx):\n"
                    "    click.echo(f'name={ctx.info_name}')\n\n"
                    "@group.command('sub')\n"
                    "def sub():\n"
                    "    click.echo('sub')\n"
                ),
            )
            try:
                with _source_root(home):
                    result = CliRunner().invoke(cli, ["pcmod", "sub"])
            finally:
                _cleanup_ymod("pcmod")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("name=pcmod", result.output)
            self.assertNotIn("Traceback", result.output)
