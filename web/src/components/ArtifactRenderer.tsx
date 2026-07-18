import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";

export type ArtifactType = "mermaid" | "vega-lite" | "artifact-svg";

interface ArtifactRendererProps {
  type: ArtifactType;
  spec: string;
}

// Module-level cache of already-rendered artifact HTML, keyed by type+theme+spec.
// Rendering is async (dynamic import + mermaid/vega), so without a cache every
// remount of a bubble (which happens on each streamed chunk, since the displayed
// "last assistant" message index advances) collapses the container back to the
// loading placeholder until the async render finishes. That transient height
// collapse makes MessageList's scroll-to-bottom measure a too-small scrollHeight
// and strands the view near the top. Caching lets a remount restore the rendered
// SVG synchronously (in a layout effect, before paint), so the height never
// collapses and scroll stays put. Theme darkness is part of the key so a light↔dark
// switch re-renders instead of restoring a stale palette.
const renderCache = new Map<string, string>();

let artifactSeq = 0;

/** Local isDark until ST2 lands utils/theme.ts (ST5 stays independent). */
const DARK_THEMES = new Set(["dark", "solarized-dark"]);

function isDark(theme?: string | null): boolean {
  const t =
    theme ??
    (typeof document !== "undefined" ? document.documentElement.dataset.theme : undefined) ??
    "light";
  return DARK_THEMES.has(t);
}

function artifactLabel(type: ArtifactType): string {
  if (type === "vega-lite") return "chart";
  if (type === "mermaid") return "diagram";
  return "svg";
}

function sanitizeSvg(svg: string): string {
  // Two non-obvious rules keep mermaid diagrams from rendering as an empty box:
  //
  // 1. No custom ALLOWED_URI_REGEXP. DOMPurify URI-validates every attribute that
  //    isn't in its URI-safe allowlist, so a narrow regexp rejects the values of
  //    geometry attributes (transform, viewBox, d, points, x/y, width/height…) and
  //    collapses the whole diagram to the origin. The default regexp still blocks
  //    javascript:/external schemes.
  // 2. Allow <foreignObject> + the html profile. mermaid 11 renders flowchart NODE
  //    labels as HTML inside <foreignObject> even with flowchart.htmlLabels:false
  //    (forcing it truly off makes node labels render empty), so forbidding it drops
  //    every node label. DOMPurify still sanitizes that embedded HTML (script tags,
  //    on* handlers, javascript: URIs are stripped), and href/xlink:href/src are
  //    forbidden below, so the label HTML stays inert.
  return DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true, html: true },
    ADD_TAGS: ["foreignObject"],
    HTML_INTEGRATION_POINTS: { foreignobject: true },
    FORBID_TAGS: ["script", "iframe", "object", "embed"],
    FORBID_ATTR: ["onerror", "onload", "onclick", "onmouseover", "onfocus", "src", "href", "xlink:href"],
  });
}

function ArtifactError({ type, error, spec }: { type: ArtifactType; error: string; spec: string }) {
  return (
    <div className="my-3 rounded border border-sol-red/60 bg-sol-red/10 p-3 text-sol-red">
      <div className="font-mono text-xs font-semibold">Could not render {artifactLabel(type)}: {error}</div>
      <details className="mt-2 text-sol-base0">
        <summary className="cursor-pointer text-xs text-sol-base01">Show raw spec</summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-sol-base03 p-2 text-xs"><code>{spec}</code></pre>
      </details>
    </div>
  );
}

export default function ArtifactRenderer({ type, spec }: ArtifactRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dark, setDark] = useState(() => isDark());
  const cacheKey = `${type}:${dark ? "dark" : "light"}:${spec}`;
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    () => (renderCache.has(cacheKey) ? "ready" : "loading"),
  );
  const [error, setError] = useState<string | null>(null);
  const renderId = useMemo(
    () => `artifact-${type}-${dark ? "d" : "l"}-${artifactSeq++}`,
    [type, spec, dark],
  );

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setDark(isDark(root.dataset.theme));
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  // Layout effect (runs before paint, child-before-parent) so a cached restore
  // is in place before MessageList's scroll-to-bottom reads scrollHeight.
  useLayoutEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;

    // Cache hit: restore synchronously, no async gap, no height collapse.
    const cached = renderCache.get(cacheKey);
    if (cached !== undefined) {
      container.innerHTML = cached;
      setStatus("ready");
      setError(null);
      return;
    }

    container.innerHTML = "";
    setStatus("loading");
    setError(null);

    async function renderArtifact() {
      const el = containerRef.current;
      if (!el) return;
      try {
        if (type === "artifact-svg") {
          const html = sanitizeSvg(spec);
          el.innerHTML = html;
          renderCache.set(cacheKey, html);
          setStatus("ready");
          return;
        }

        if (type === "mermaid") {
          const mermaid = (await import("mermaid")).default;
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: dark ? "dark" : "default",
            suppressErrorRendering: true,
          });
          await mermaid.parse(spec);
          const { svg } = await mermaid.render(renderId, spec);
          if (cancelled) return;
          const html = sanitizeSvg(svg);
          el.innerHTML = html;
          renderCache.set(cacheKey, html);
          setStatus("ready");
          return;
        }

        const vegaEmbed = (await import("vega-embed")).default;
        const parsedSpec = JSON.parse(spec);
        await vegaEmbed(el, parsedSpec, {
          actions: { export: false, source: false, compiled: false, editor: false },
          renderer: "svg",
          // vega-themes: 'dark' for dark palettes; omit for light default.
          ...(dark ? { theme: "dark" as const } : {}),
        });
        if (cancelled) return;
        renderCache.set(cacheKey, el.innerHTML);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        el.innerHTML = "";
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
      }
    }

    void renderArtifact();

    return () => {
      cancelled = true;
    };
  }, [renderId, spec, type, cacheKey, dark]);

  if (status === "error") {
    return <ArtifactError type={type} error={error || "unknown error"} spec={spec} />;
  }

  return (
    <div className="my-3 overflow-x-auto rounded border border-sol-base01/30 bg-sol-base03/60 p-3">
      {status === "loading" ? <div className="font-mono text-xs text-sol-base01">Rendering {artifactLabel(type)}…</div> : null}
      <div ref={containerRef} className="artifact-renderer min-w-0 [&_svg]:max-w-full [&_svg]:h-auto" />
    </div>
  );
}

export { sanitizeSvg };
