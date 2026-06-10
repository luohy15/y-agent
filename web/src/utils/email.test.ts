import { describe, expect, it } from "vitest";
import { emailSnippet, htmlToText, isHtmlContent, sanitizeEmailHtml } from "./email";

// Shape of the usvisascheduling.com confirmation email: full HTML document with
// <style> rules in <head> and a table-based body.
const HTML_DOC = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>.title { color: red; } table { width: 100%; }</style>
</head>
<body>
<table><tr><td>
<p class="title">Your appointment is confirmed.</p>
<img src="https://example.com/logo.png" alt="logo">
<a href="https://example.com/details">Details</a>
</td></tr></table>
</body>
</html>`;

const PLAIN_REPLY = "Hello\nworld\n\nOn Mon, Jan 5, 2026 at 9:00 AM Aria <aria@example.com> wrote:\n> earlier text";

describe("isHtmlContent", () => {
  it("detects HTML documents and fragments", () => {
    expect(isHtmlContent(HTML_DOC)).toBe(true);
    expect(isHtmlContent('<div class="x">hi</div>')).toBe(true);
    expect(isHtmlContent("line one<br/>line two")).toBe(true);
    expect(isHtmlContent("<p>hi</p>")).toBe(true);
  });

  it("does not trigger on plain text", () => {
    expect(isHtmlContent("just a plain email body")).toBe(false);
    expect(isHtmlContent("math: a < b and hearts <3")).toBe(false);
    expect(isHtmlContent(PLAIN_REPLY)).toBe(false);
    expect(isHtmlContent("")).toBe(false);
    expect(isHtmlContent(undefined)).toBe(false);
  });
});

describe("sanitizeEmailHtml", () => {
  it("strips scripts, event handlers, and javascript: URIs", () => {
    const dirty = '<p>hi</p><script>alert(1)</script><img src="https://e.com/x.png" onerror="alert(1)"><a href="javascript:alert(1)">x</a>';
    const clean = sanitizeEmailHtml(dirty);
    expect(clean).not.toContain("script");
    expect(clean).not.toContain("alert(1)");
    expect(clean).not.toContain("onerror");
    expect(clean).not.toContain("javascript:");
    expect(clean).toContain('src="https://e.com/x.png"');
  });

  it("strips embedding and form tags", () => {
    const dirty = '<iframe src="https://e.com"></iframe><form><input><button>go</button></form><object></object><embed><base href="https://e.com"><link rel="stylesheet" href="https://e.com/a.css">';
    const clean = sanitizeEmailHtml(dirty);
    for (const tag of ["iframe", "form", "input", "button", "object", "embed", "base", "link"]) {
      expect(clean).not.toContain(`<${tag}`);
    }
  });

  it("keeps style blocks, tables, and http(s) images", () => {
    const clean = sanitizeEmailHtml(HTML_DOC);
    expect(clean).toContain(".title { color: red; }");
    expect(clean).toContain("<table>");
    expect(clean).toContain('<img src="https://example.com/logo.png"');
    expect(clean).toContain("Your appointment is confirmed.");
  });
});

describe("htmlToText", () => {
  it("strips tags and embedded CSS, collapsing whitespace", () => {
    const text = htmlToText(HTML_DOC);
    expect(text).toContain("Your appointment is confirmed.");
    expect(text).toContain("Details");
    expect(text).not.toContain("<");
    expect(text).not.toContain("color: red");
    expect(text).not.toMatch(/\s{2,}/);
  });
});

describe("emailSnippet", () => {
  it("keeps the plain-text path (own text before quote marker, newlines collapsed)", () => {
    expect(emailSnippet(PLAIN_REPLY)).toBe("Hello world");
  });

  it("strips HTML bodies to readable text", () => {
    const snippet = emailSnippet(HTML_DOC);
    expect(snippet).toContain("Your appointment is confirmed.");
    expect(snippet).not.toContain("<");
    expect(snippet).not.toContain("color: red");
  });

  it("handles empty content", () => {
    expect(emailSnippet("")).toBe("");
    expect(emailSnippet(undefined)).toBe("");
  });
});
