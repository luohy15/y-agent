import { useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";

export type ArtifactType = "mermaid" | "vega-lite" | "artifact-svg";

interface ArtifactRendererProps {
  type: ArtifactType;
  spec: string;
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
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const renderId = useMemo(() => `artifact-${type}-${Math.random().toString(36).slice(2)}`, [type, spec]);

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML = "";
    setStatus("loading");
    setError(null);

    async function renderArtifact() {
      try {
        if (type === "artifact-svg") {
          container.innerHTML = sanitizeSvg(spec);
          setStatus("ready");
          return;
        }

        if (type === "mermaid") {
          const mermaid = (await import("mermaid")).default;
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: "dark",
            suppressErrorRendering: true,
          });
          await mermaid.parse(spec);
          const { svg } = await mermaid.render(renderId, spec);
          if (cancelled) return;
          container.innerHTML = sanitizeSvg(svg);
          setStatus("ready");
          return;
        }

        const vegaEmbed = (await import("vega-embed")).default;
        const parsedSpec = JSON.parse(spec);
        await vegaEmbed(container, parsedSpec, {
          actions: { export: false, source: false, compiled: false, editor: false },
          renderer: "svg",
        });
        if (!cancelled) setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        container.innerHTML = "";
        setError(err instanceof Error ? err.message : String(err));
        setStatus("error");
      }
    }

    void renderArtifact();

    return () => {
      cancelled = true;
      container.innerHTML = "";
    };
  }, [renderId, spec, type]);

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
