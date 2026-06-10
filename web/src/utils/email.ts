import DOMPurify from "dompurify";

export function formatEmailDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// Gmail-style expanded-header timestamp, e.g. "Sat, Feb 28, 3:40 AM"; the year is
// shown only for messages from a previous year.
export function formatEmailDateTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  const opts: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleString(undefined, opts);
}

// Full timestamp for the recipient-details panel, e.g. "Feb 28, 2026, 3:40 AM"
// (year always shown, unlike formatEmailDateTime).
export function formatEmailDateFull(ts: number): string {
  if (!ts) return "";
  return new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

// Parse a `From:` header value into a display name + bare email. Falls back to the
// raw string for both fields when there is no `Name <addr>` shape.
export function parseSender(from: string | undefined): { name: string; email: string } {
  if (!from) return { name: "", email: "" };
  const m = from.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
  if (m) {
    const email = m[2].trim();
    return { name: m[1].trim() || email, email };
  }
  const trimmed = from.trim();
  return { name: trimmed, email: trimmed };
}

// Split an email body into the author's own text and the trailing quoted reply
// chain (everything from the first `On ... wrote:` marker onward).
export function splitOwnAndQuoted(s: string | undefined): { own: string; quoted: string } {
  if (!s) return { own: "", quoted: "" };
  const match = s.search(/^>?\s*On .+wrote:\s*$/m);
  if (match < 0) return { own: s.trim(), quoted: "" };
  return { own: s.slice(0, match).trim(), quoted: s.slice(match).trim() };
}

// Heuristic for HTML-only email bodies (Gmail sync stores raw HTML in `content`
// when no text/plain part exists). Only structural tags trigger, so plain text
// mentioning "<3" or "a < b" stays on the plain-text path.
export function isHtmlContent(s: string | undefined): boolean {
  if (!s) return false;
  return /<(?:!doctype|html|head|body|table|div|p|br|span|a|img|style)[\s/>]/i.test(s);
}

// XSS-safe HTML for rendering an untrusted email body. DOMPurify defaults strip
// scripts / event handlers / javascript: URIs; on top of that, forbid embedding
// and form tags. <style> and http(s) <img> stay allowed so emails look right
// (Gmail-with-images behavior). WHOLE_DOCUMENT keeps <style> blocks that live in
// <head> of full HTML documents.
export function sanitizeEmailHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    WHOLE_DOCUMENT: true,
    FORBID_TAGS: ["script", "iframe", "object", "embed", "form", "input", "button", "meta", "link", "base"],
  });
}

// Plain-text projection of an HTML body for snippets. DOMParser is inert (no
// script execution, no resource loading), so the raw HTML is safe to parse.
export function htmlToText(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("style, script, title").forEach((el) => el.remove());
  return (doc.body?.textContent || "").replace(/\s+/g, " ").trim();
}

// One-line snippet for list rows / collapsed thread rows: own text before the
// quoted reply chain for plain bodies, tag-stripped text for HTML bodies.
export function emailSnippet(content: string | undefined): string {
  if (!content) return "";
  if (isHtmlContent(content)) return htmlToText(content);
  return splitOwnAndQuoted(content).own.replace(/\n+/g, " ").trim();
}
