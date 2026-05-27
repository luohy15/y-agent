import { useMemo } from "react";
import hljs from "highlight.js";
import ArtifactRenderer, { type ArtifactType } from "./ArtifactRenderer";

export type ArtifactMode = "preview" | "raw";
export type { ArtifactType };

interface ArtifactViewProps {
  type: ArtifactType;
  spec: string;
  mode: ArtifactMode;
  onModeChange: (mode: ArtifactMode) => void;
  onOpenInTab?: () => void;
  variant: "inline" | "tab";
}

function rawLanguage(type: ArtifactType): string {
  if (type === "vega-lite") return "json";
  if (type === "artifact-svg") return "xml";
  return "plaintext";
}

function highlightSpec(type: ArtifactType, spec: string): string | null {
  const language = rawLanguage(type);
  try {
    if (hljs.getLanguage(language)) {
      return hljs.highlight(spec, { language }).value;
    }
  } catch {}
  return null;
}

export default function ArtifactView({ type, spec, mode, onModeChange, onOpenInTab, variant }: ArtifactViewProps) {
  const highlighted = useMemo(() => highlightSpec(type, spec), [type, spec]);
  const showOpenInTab = variant === "inline" && !!onOpenInTab;

  return (
    <div className={`${variant === "inline" ? "my-3" : "h-full p-3"} min-w-0`}>
      <div className="rounded border border-sol-base01/30 bg-sol-base03/60">
        <div className="flex items-center justify-end gap-2 border-b border-sol-base01/20 px-2 py-1">
          <button
            type="button"
            onClick={() => onModeChange(mode === "preview" ? "raw" : "preview")}
            className="rounded px-2 py-0.5 font-mono text-xs text-sol-base01 hover:bg-sol-base01/20 hover:text-sol-base1"
            title={mode === "preview" ? "Show raw" : "Show preview"}
          >
            {mode === "preview" ? "Raw" : "Preview"}
          </button>
          <button
            type="button"
            onClick={() => navigator.clipboard.writeText(spec)}
            className="rounded px-2 py-0.5 font-mono text-xs text-sol-base01 hover:bg-sol-base01/20 hover:text-sol-base1"
            title="Copy raw spec"
          >
            Copy
          </button>
          {showOpenInTab && (
            <button
              type="button"
              onClick={onOpenInTab}
              className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-xs text-sol-base01 hover:bg-sol-base01/20 hover:text-sol-base1"
              title="Open in tab"
            >
              <svg className="h-3 w-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 4H3.5A1.5 1.5 0 0 0 2 5.5v7A1.5 1.5 0 0 0 3.5 14h7a1.5 1.5 0 0 0 1.5-1.5V10" />
                <path d="M9 2h5v5" />
                <path d="M8 8l6-6" />
              </svg>
              Open in tab
            </button>
          )}
        </div>
        {mode === "preview" ? (
          <ArtifactRenderer type={type} spec={spec} />
        ) : (
          <pre className="max-h-[70vh] overflow-auto p-3 text-xs leading-relaxed"><code className="hljs whitespace-pre-wrap break-words" dangerouslySetInnerHTML={highlighted ? { __html: highlighted } : undefined}>{highlighted ? undefined : spec}</code></pre>
        )}
      </div>
    </div>
  );
}
