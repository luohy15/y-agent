import { describe, expect, it } from "vitest";
import { availableFormats, buildHtmlDocument, exportFilename, extractMarkdownHeadings, renderMarkdownBody } from "./markdownExport";

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
    const document = new DOMParser().parseFromString(buildHtmlDocument({ title: "Export", bodyHtml }), "text/html");
    const headings = extractMarkdownHeadings(document.body);
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>(".markdown-toc a"));

    expect(document.querySelector(".markdown-toc")).not.toBeNull();
    expect(headings.map((heading) => heading.text)).toEqual(["重复", "小节", "重复", "Café & tea"]);
    expect(new Set(headings.map((heading) => heading.id)).size).toBe(headings.length);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(headings.map((heading) => `#${heading.id}`));
    expect(links.map((link) => link.textContent)).toEqual(headings.map((heading) => heading.text));
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
});
