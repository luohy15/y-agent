// Sandboxed HTML preview preparation, shared by the File module's in-app
// preview and the public shared-note HTML viewer (todo 3406). Ported from
// the y-module File surface (todo 3402); this host copy is the canonical
// one going forward, per pages/plan-3406-shared-note-html.md sub-task 1.

const SRCDOC_BASE_HREF = "about:srcdoc";

/** First `<base>` element in tree order carrying a non-empty `href`, per the
 * HTML "frozen base URL" algorithm (a target-only `<base target="_blank">`
 * does not count as an authored base URL). */
function findAuthoredBaseHref(node: Element): Element | null {
  if (node.tagName === "BASE" && node.getAttribute("href")) return node;
  for (const child of Array.from(node.children)) {
    const found = findAuthoredBaseHref(child);
    if (found) return found;
  }
  return null;
}

function serializeDoctype(doctype: DocumentType | null): string {
  if (!doctype) return "";
  const { name, publicId, systemId } = doctype;
  if (publicId) return `<!DOCTYPE ${name} PUBLIC "${publicId}"${systemId ? ` "${systemId}"` : ""}>`;
  if (systemId) return `<!DOCTYPE ${name} SYSTEM "${systemId}">`;
  return `<!DOCTYPE ${name}>`;
}

/** Prepares HTML text for a sandboxed `srcDoc` preview iframe (todo 3402). A
 * srcdoc document's URL is `about:srcdoc`, but a relative `href="#id"` falls
 * back to resolving against the embedding application's URL instead, so
 * activating it navigates the iframe to the app instead of scrolling to the
 * in-document target. Supplying an explicit base keeps fragment navigation
 * (category/back-to-top links, `:target` highlighting) inside the srcdoc
 * document. A document that already authors a `base[href]` is left
 * untouched. Parsing is preparation, not sanitization: the iframe's
 * `sandbox="allow-scripts"` (no `allow-same-origin`) is the security
 * boundary. */
export function preparePreviewHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  if (!findAuthoredBaseHref(doc.documentElement)) {
    const base = doc.createElement("base");
    base.setAttribute("href", SRCDOC_BASE_HREF);
    doc.head.insertBefore(base, doc.head.firstChild);
  }
  return serializeDoctype(doc.doctype) + doc.documentElement.outerHTML;
}

// Sandboxed (origin-null) preview iframes swallow keydown when focused, so the
// parent window's global shortcuts (Ctrl+`, Ctrl+P, Ctrl+1-9) stop firing. This
// bridge forwards Ctrl/Cmd-modified keydowns via postMessage; host App.tsx
// replays them as synthetic window keydowns. Only the in-app File preview
// enables it: public shares have no application keyboard shortcuts to forward.
export const PREVIEW_KBD_BRIDGE = `<script>(function(){window.addEventListener('keydown',function(e){if(e.ctrlKey||e.metaKey){e.preventDefault();parent.postMessage({__yPreviewKeydown:{key:e.key,ctrlKey:e.ctrlKey,metaKey:e.metaKey,shiftKey:e.shiftKey,altKey:e.altKey}},'*');}});})();<\/script>`;

export function withPreviewKbdBridge(html: string): string {
  return PREVIEW_KBD_BRIDGE + preparePreviewHtml(html);
}

/** Reads an HTML document's nonempty `<title>` as plain text, or null when
 * absent/empty (todo 3406). Used to prefer the authored document title over
 * note front matter / content-key fallbacks; reads `Document.title` (a text
 * property), never interpolates the value back into markup. */
export function extractHtmlTitle(html: string): string | null {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const title = doc.title.trim();
  return title.length > 0 ? title : null;
}
