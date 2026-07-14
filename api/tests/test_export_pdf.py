"""Tests for api.controller.file.export_pdf — the server-side WeasyPrint PDF path.

Two layers:
  * Branch tests (always run in CI): empty payload -> 400, renderer_missing
    sentinel -> 503, render_failed sentinel -> 502. The exec channel is mocked,
    so nothing needs WeasyPrint installed.
  * Integration test (skipped unless the render host has weasyprint + pdftotext +
    pypdf): pipes a fixed sample HTML through the *real* render path with a local
    vm_config and asserts (a) a non-empty PDF outline with the expected heading
    titles and (b) CJK text extractable via pdftotext. This is the sub-task 6
    server acceptance; CI (ubuntu, no WeasyPrint) skips it.
"""

import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from api.controller import file as file_controller
from storage.dto.vm import VmConfig

try:
    import pypdf
except ImportError:  # pragma: no cover - optional integration dep
    pypdf = None


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


# A fixed standalone sample mirroring buildHtmlDocument output: H1 + CJK h2/h3.
SAMPLE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Sample</title></head>
<body>
<h1 id="root">Export Sample 导出样例</h1>
<p>Body paragraph verifying the render path end to end.</p>
<h2 id="overview">中文标题 Overview</h2>
<p>这是一段中文正文，用来验证 WeasyPrint 嵌入真实字形而不是豆腐方块。</p>
<h3 id="details">子节 Details</h3>
<p>Nested heading to verify H1 &gt; H2 &gt; H3 nesting in the outline.</p>
</body></html>"""

EXPECTED_TITLES = ["Export Sample 导出样例", "中文标题 Overview", "子节 Details"]

_HAS_RENDER_TOOLS = bool(shutil.which("weasyprint")) and bool(shutil.which("pdftotext")) and pypdf is not None


class ExportPdfBranchTest(unittest.IsolatedAsyncioTestCase):
    """Error branches — exec channel mocked, no WeasyPrint needed."""

    def _patch_runner(self, stack, run_cmd_return=None, run_cmd_exc=None):
        run_cmd = AsyncMock(return_value=run_cmd_return, side_effect=run_cmd_exc)
        runner_instance = SimpleNamespace(run_cmd=run_cmd)
        runner_cls = MagicMock(return_value=runner_instance)
        stack.enter_context(patch.object(file_controller, "_get_cmd_runner_cls", MagicMock(return_value=runner_cls)))
        stack.enter_context(patch("agent.config.resolve_vm_config", MagicMock(return_value=VmConfig())))
        return run_cmd

    async def test_empty_html_400(self):
        body = file_controller.ExportPdfRequest(html="   ")
        with self.assertRaises(HTTPException) as ctx:
            await file_controller.export_pdf(_request(), body, vm_name=None, work_dir=None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_renderer_missing_503(self):
        with ExitStack() as stack:
            self._patch_runner(stack, run_cmd_return="__PDF_ERR__:renderer_missing\n")
            body = file_controller.ExportPdfRequest(html="<h1>Hi</h1>")
            with self.assertRaises(HTTPException) as ctx:
                await file_controller.export_pdf(_request(), body, vm_name=None, work_dir=None)
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_render_failed_502(self):
        with ExitStack() as stack:
            self._patch_runner(stack, run_cmd_return="__PDF_ERR__:render_failed:boom pango error")
            body = file_controller.ExportPdfRequest(html="<h1>Hi</h1>")
            with self.assertRaises(HTTPException) as ctx:
                await file_controller.export_pdf(_request(), body, vm_name=None, work_dir=None)
            self.assertEqual(ctx.exception.status_code, 502)
            self.assertIn("boom pango", ctx.exception.detail)

    async def test_bad_base64_502(self):
        with ExitStack() as stack:
            # non-base64, non-sentinel, non-%PDF output
            self._patch_runner(stack, run_cmd_return="!!!not base64!!!")
            body = file_controller.ExportPdfRequest(html="<h1>Hi</h1>")
            with self.assertRaises(HTTPException) as ctx:
                await file_controller.export_pdf(_request(), body, vm_name=None, work_dir=None)
            self.assertEqual(ctx.exception.status_code, 502)


class ExportPdfContentDispositionTest(unittest.TestCase):
    def test_ascii_filename(self):
        cd = file_controller._pdf_content_disposition("notes.md")
        self.assertIn('filename="notes.pdf"', cd)
        self.assertIn("filename*=UTF-8''notes.pdf", cd)

    def test_cjk_filename_gets_utf8_and_ascii_fallback(self):
        cd = file_controller._pdf_content_disposition("中文笔记")
        self.assertIn("filename*=UTF-8''", cd)
        # percent-encoded UTF-8, ascii fallback degrades to export.pdf
        self.assertIn('filename="export.pdf"', cd)

    def test_strips_path_and_appends_ext(self):
        cd = file_controller._pdf_content_disposition("/a/b/report")
        self.assertIn('filename="report.pdf"', cd)


@unittest.skipUnless(
    _HAS_RENDER_TOOLS,
    "weasyprint + pdftotext + pypdf required for the real render acceptance test",
)
class ExportPdfRenderIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Real render through the controller against a local vm_config."""

    async def _render(self):
        # Local vm_config (empty api_token) -> run_cmd goes through local_exec,
        # invoking the real `weasyprint` on PATH.
        with patch("agent.config.resolve_vm_config", MagicMock(return_value=VmConfig())):
            body = file_controller.ExportPdfRequest(html=SAMPLE_HTML, filename="sample.md")
            return await file_controller.export_pdf(_request(), body, vm_name=None, work_dir=None)

    async def test_outline_and_cjk(self):
        resp = await self._render()
        self.assertEqual(resp.media_type, "application/pdf")
        self.assertTrue(resp.body[:5] == b"%PDF-", "response is not a PDF")
        self.assertIn("sample.pdf", resp.headers["content-disposition"])

        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(resp.body)
            f.flush()

            # (a) non-empty outline with expected heading titles
            reader = pypdf.PdfReader(f.name)
            titles = []

            def walk(items):
                for it in items:
                    if isinstance(it, list):
                        walk(it)
                    else:
                        titles.append(it.title)

            walk(reader.outline)
            self.assertGreater(len(titles), 0, "PDF outline is empty")
            for expected in EXPECTED_TITLES:
                self.assertIn(expected, titles)

            # (b) CJK extractable as real glyphs (not tofu)
            text = subprocess.run(
                ["pdftotext", f.name, "-"], capture_output=True, text=True, timeout=30
            ).stdout
            self.assertIn("这是一段中文正文", text)
            self.assertIn("中文标题", text)


if __name__ == "__main__":
    unittest.main()
