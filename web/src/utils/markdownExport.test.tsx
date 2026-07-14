import { describe, expect, it } from "vitest";
import { availableFormats, buildHtmlDocument, exportFilename, renderMarkdownBody } from "./markdownExport";

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

  it("renders Markdown with headings, tables, and CJK text", () => {
    const html = renderMarkdownBody("# Heading 导出\n\n| a | b |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<h1");
    expect(html).toContain("<table>");
    expect(html).toContain("导出");
  });
});
