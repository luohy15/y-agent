import DOMPurify from "dompurify";

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
