import { useState } from "react";
import { API, HOST_CONTRACT_VERSION, ListLoading } from "@y/host";

/**
 * Starter UI artifact. Edit this file, then:
 *   y module publish <slug>
 * The host supplies react / @y/host / swr / recharts via the runtime registry.
 *
 * One artifact is one module with two surfaces:
 *   `panel`  (required) renders in the ~280px left sidebar
 *   `detail` (optional) renders full-width in the center surface, opened from
 *            the panel header (no dedicated URL; it restores as a persisted
 *            tab like any other file tab)
 * Delete the `detail` export for a sidebar-only artifact.
 *
 * Outgrowing one file? Keep this file as the thin entry and put sibling
 * modules under a same-named parts directory next to it (e.g.
 * `ui/<slug>/panel.tsx`, `ui/<slug>/format.ts`), imported here with relative
 * specifiers. `y module publish` bundles relative imports and scans the parts
 * directory for Tailwind classes automatically — no other config needed.
 */
function StarterPanel() {
  const [count, setCount] = useState(0);

  return (
    <div className="p-4 bg-sol-base02 text-sol-base0 rounded-lg">
      <h2 className="text-lg font-semibold text-sol-base1 mb-2">Starter panel</h2>
      <p className="text-sm text-sol-base01 mb-3">
        Host API: {API} · contract v{HOST_CONTRACT_VERSION}
      </p>
      <button
        type="button"
        onClick={() => setCount((c) => c + 1)}
        className="px-3 py-1 rounded bg-sol-blue text-sol-base03 hover:bg-sol-cyan"
      >
        clicks: {count}
      </button>
      <div className="mt-3">
        <ListLoading />
      </div>
    </div>
  );
}

function StarterDetail() {
  return (
    <div className="p-6 text-sol-base0">
      <h1 className="text-xl font-semibold text-sol-base1 mb-2">Starter detail view</h1>
      <p className="text-sm text-sol-base01">
        The wide surface: tables, charts, anything that needs more than the sidebar.
      </p>
    </div>
  );
}

export const panel = StarterPanel;
export const detail = StarterDetail;
