import { preparePreviewHtml, withPreviewKbdBridge } from "../utils/previewHtml";

export interface HtmlPreviewProps {
  /** Raw HTML source; prepared into a sandboxed srcDoc before mounting. */
  source: string;
  /** Iframe title (accessibility name + document identity). */
  title: string;
  /** Iframe sizing/appearance classes; defaults to the in-app File preview's look. */
  className?: string;
  /** Only the in-app File preview enables the postMessage keyboard-shortcut bridge. */
  keyboardBridge?: boolean;
}

/**
 * Sandboxed HTML document preview: the one iframe/srcDoc implementation
 * shared by the File module's in-app preview and the public shared-note HTML
 * viewer (todo 3406, extracted from the y-module File surface repaired in
 * todo 3402). Owns preparation, sandbox flags, and srcDoc construction.
 * Exactly `sandbox="allow-scripts"` — never `allow-same-origin`, popup, or
 * top-navigation flags, and never raw host-DOM insertion.
 */
export default function HtmlPreview({ source, title, className, keyboardBridge = false }: HtmlPreviewProps) {
  const srcDoc = keyboardBridge ? withPreviewKbdBridge(source) : preparePreviewHtml(source);
  return (
    <iframe
      sandbox="allow-scripts"
      srcDoc={srcDoc}
      title={title}
      className={className ?? "w-full h-full border-0 bg-white"}
    />
  );
}
