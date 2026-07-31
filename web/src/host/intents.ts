// The host->artifact focus channel (contract v3, plan sub-task S0,
// pages/plan-2979-calendar-dynamic-ui.md Part D). Two problems, one file:
//
// - G1 (host -> artifact focus): built-in host code (App.tsx, tagNavigate.ts)
//   needs to tell an artifact "show me this thing" with no props channel
//   (`ArtifactMount` renders `<Artifact />` with no props by contract). The
//   store below is retained (latched), not a fire-and-forget event: the host
//   sets the intent and opens the tab in the same tick, but the artifact
//   mount is async (authFetch -> sha256 verify -> blob import). A plain
//   `window.dispatchEvent` would be dispatched before any listener exists, so
//   the *first* focus -- the common case -- would be silently lost. Reading
//   the current value out of the `intents` map on first render (mirroring
//   `theme.ts`'s `current` snapshot) means a late-mounting subscriber still
//   sees the latest intent.
// - G2 (artifact -> its own detail tab): an artifact-initiated action (e.g. a
//   panel row click) needs to open its own detail surface as a host tab.
//   Opening a tab is host state (`App.tsx`'s `openFiles`/`activeFile`), so the
//   artifact-facing `openArtifactDetail` defers to a handler App.tsx
//   registers. By the time any artifact can call it, the host has already
//   mounted and registered (this is only ever invoked from an event handler,
//   never during initial render), so no latch is needed here.
import { useEffect, useState } from "react";

const intents = new Map<string, unknown>();
const listeners = new Map<string, Set<(intent: unknown) => void>>();

/** Host-internal setter. Not exported through `@y/host` — only built-in host
 * code (App.tsx, tagNavigate.ts) may set an artifact's focus intent. */
export function setArtifactIntent(slug: string, intent: unknown): void {
  intents.set(slug, intent);
  const subs = listeners.get(slug);
  if (subs) for (const listener of subs) listener(intent);
}

/** Read + subscribe to the latest focus intent the host set for `slug`. */
export function useArtifactIntent<T = unknown>(slug: string): T | null {
  const [intent, setIntent] = useState<T | null>(() => (intents.get(slug) as T | undefined) ?? null);
  useEffect(() => {
    // Re-sync on mount / slug change in case the intent changed between the
    // initializer above and this effect running (unlikely, but cheap to be
    // exact) and to switch subscription targets.
    setIntent((intents.get(slug) as T | undefined) ?? null);
    let subs = listeners.get(slug);
    if (!subs) {
      subs = new Set();
      listeners.set(slug, subs);
    }
    const listener = (next: unknown) => setIntent((next as T | undefined) ?? null);
    subs.add(listener);
    return () => {
      subs!.delete(listener);
      if (subs!.size === 0) listeners.delete(slug);
    };
  }, [slug]);
  return intent;
}

type DetailOpener = (slug: string) => void;

let detailOpener: DetailOpener | null = null;

/** Host-internal registration. App.tsx wires this to the same tab-open path
 * its "Open <label> full view" button uses (`handleOpenFile(artifactTabKey(slug))`). */
export function registerArtifactDetailOpener(opener: DetailOpener): () => void {
  detailOpener = opener;
  return () => {
    if (detailOpener === opener) detailOpener = null;
  };
}

/** Ask the host to open this artifact's detail surface as a tab. */
export function openArtifactDetail(slug: string): void {
  detailOpener?.(slug);
}
