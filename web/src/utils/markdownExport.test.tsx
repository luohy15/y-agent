import { describe, expect, it, vi } from "vitest";
import { availableFormats, buildHtmlDocument, exportFilename, extractMarkdownHeadings, renderMarkdownBody, requestPdfExport } from "./markdownExport";

describe("markdown export helpers", () => {
  it("offers HTML and PDF only for Markdown files", () => {
    expect(availableFormats("pages/note.md")).toEqual(["md", "html", "pdf"]);
    expect(availableFormats("scripts/task.py")).toEqual(["md"]);
  });

  it("uses a basename and swaps the extension", () => {
    expect(exportFilename("pages/note.md", "md")).toBe("note.md");
    expect(exportFilename("pages/note.md", "html")).toBe("note.html");
    expect(exportFilename("pages/note.md", "pdf")).toBe("note.pdf");
  });

  it("builds a standalone styled HTML document", () => {
    const document = buildHtmlDocument({ title: "Export", bodyHtml: "<h1>Body</h1>" });
    expect(document).toContain("<!doctype html>");
    expect(document).toContain("<title>Export</title>");
    expect(document).toContain("<h1>Body</h1>");
    expect(document).toContain("<style>");
  });

  it("adds a compact TOC linked to the rendered heading anchors", () => {
    const bodyHtml = renderMarkdownBody("# Title\n\n## 重复\n\n### 小节\n\n## 重复\n\n## Café & tea");
    const rawDocument = buildHtmlDocument({ title: "Export", bodyHtml });
    const document = new DOMParser().parseFromString(rawDocument, "text/html");
    const headings = extractMarkdownHeadings(document.body);
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>(".markdown-toc a"));

    expect(document.querySelector(".markdown-toc")).not.toBeNull();
    expect(headings.map((heading) => heading.text)).toEqual(["重复", "小节", "重复", "Café & tea"]);
    expect(new Set(headings.map((heading) => heading.id)).size).toBe(headings.length);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(headings.map((heading) => `#${heading.id}`));
    expect(links.map((link) => link.textContent)).toEqual(headings.map((heading) => heading.text));

    // The TOC must sit immediately after the first H1, not above it.
    const tocIndex = rawDocument.indexOf('<nav class="markdown-toc"');
    const firstH1CloseIndex = rawDocument.indexOf("</h1>");
    const firstH2Index = rawDocument.indexOf("<h2");
    expect(tocIndex).toBeGreaterThan(firstH1CloseIndex);
    expect(tocIndex).toBeLessThan(firstH2Index);
  });

  it("falls back to top-of-body placement when there is no H1", () => {
    const bodyHtml = renderMarkdownBody("## Only a subheading\n\ncontent");
    const rawDocument = buildHtmlDocument({ title: "Export", bodyHtml });

    const tocIndex = rawDocument.indexOf('<nav class="markdown-toc"');
    const bodyIndex = rawDocument.indexOf("<body>");
    const firstH2Index = rawDocument.indexOf("<h2");
    expect(tocIndex).toBeGreaterThan(bodyIndex);
    expect(tocIndex).toBeLessThan(firstH2Index);
  });

  it("embeds an explicit cross-platform CJK font fallback stack", () => {
    const document = buildHtmlDocument({ title: "导出", bodyHtml: "<p>中文</p>" });
    // Named families for each major OS so CJK glyphs resolve to a real installed
    // font instead of the browser's last-resort fallback (prints tofu otherwise).
    expect(document).toContain("PingFang SC"); // macOS
    expect(document).toContain("Microsoft YaHei"); // Windows
    expect(document).toContain("Noto Sans CJK SC"); // Linux / Android
    // The fallback is applied to both body text and monospace code.
    expect(document).toContain("var(--cjk-fallback), sans-serif");
    expect(document).toContain("var(--cjk-fallback), monospace");
  });

  it("renders Markdown with headings, tables, and CJK text", () => {
    const html = renderMarkdownBody("# Heading 导出\n\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<h1");
    expect(html).toContain("<table>");
    expect(html).toContain("导出");
  });

  it("posts the HTML to the export-pdf endpoint and resolves the returned blob", async () => {
    const pdfBlob = new Blob(["%PDF-1.4"], { type: "application/pdf" });
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(pdfBlob, { status: 200, headers: { "Content-Type": "application/pdf" } })
    );

    const blob = await requestPdfExport(fetchImpl, "/api/file/export-pdf", "<html></html>", "note.pdf");

    expect(fetchImpl).toHaveBeenCalledWith("/api/file/export-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html: "<html></html>", filename: "note.pdf" }),
    });
    expect(blob.type).toBe("application/pdf");
  });

  it("rejects with the server-provided detail message on failure", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "PDF renderer (WeasyPrint) is not installed on the render host" }), { status: 503 })
    );

    await expect(requestPdfExport(fetchImpl, "/api/file/export-pdf", "<html></html>", "note.pdf")).rejects.toThrow(
      "PDF renderer (WeasyPrint) is not installed on the render host"
    );
  });

  it("falls back to a generic status message when the failure body isn't JSON", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("gateway error", { status: 502 }));

    await expect(requestPdfExport(fetchImpl, "/api/file/export-pdf", "<html></html>", "note.pdf")).rejects.toThrow(
      "PDF export failed (502)"
    );
  });
});
