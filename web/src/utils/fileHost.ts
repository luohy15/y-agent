// Host-side file control-plane gestures for modules/file (plan sub-task H2/C1,
// pages/plan-3068-file-module.md decision 6). Pure helpers so App.tsx can wire
// host commands / retained context without bloating the shell, and so unit
// tests can exercise payload parsing without mounting App.
import { useEffect } from "react";
import { setArtifactIntent } from "../host/intents";

export interface FileLocationContext {
  vmName: string | null;
  workDir: string | null;
}

/** Host -> file artifact retained state, published under the single `"file"`
 * slug. `left` and `right` are always both present — right mirrors
 * `selectedVM` + `effectiveWorkDir`, left mirrors the default VM +
 * `currentVmWorkDir`. A panel mount picks its own half via
 * `usePanelLocation()`. Top-level `nonce` is the shell refresh signal
 * (modules/note convention): the host republishes with a fresh value when the
 * right activity rail wants a list refresh. Every publish below reads and
 * re-sends the halves it isn't updating. */
export interface FileArtifactIntent {
  left: FileLocationContext;
  right: FileLocationContext;
  nonce?: number;
}

const EMPTY_LOCATION: FileLocationContext = { vmName: null, workDir: null };

// Module-scoped mirror of the single published value, so each publish call
// can merge in the half it isn't updating.
let lastLeft: FileLocationContext = EMPTY_LOCATION;
let lastRight: FileLocationContext = EMPTY_LOCATION;
let lastNonce = 0;

function publish(): void {
  setArtifactIntent("file", {
    left: lastLeft,
    right: lastRight,
    nonce: lastNonce,
  } satisfies FileArtifactIntent);
}

export function publishFileContext(
  leftVmName: string | null,
  leftWorkDir: string | null,
  rightVmName: string | null,
  rightWorkDir: string | null,
): void {
  lastLeft = { vmName: leftVmName, workDir: leftWorkDir };
  lastRight = { vmName: rightVmName, workDir: rightWorkDir };
  publish();
}

/** Publish the retained per-location file context whenever either location's
 * vmName/workDir changes (including to/from null). */
export function usePublishFileContext(
  leftVmName: string | null,
  leftWorkDir: string | null,
  rightVmName: string | null,
  rightWorkDir: string | null,
): void {
  useEffect(() => {
    publishFileContext(leftVmName, leftWorkDir, rightVmName, rightWorkDir);
  }, [leftVmName, leftWorkDir, rightVmName, rightWorkDir]);
}

/** Host -> file artifact list-refresh signal. Bumps the top-level `nonce`
 * without touching left/right, so the right activity rail refresh
 * button keeps working after the C1 cut. */
export function publishFileRefresh(): void {
  lastNonce = Date.now();
  publish();
}

/** Parse `{ path, vmName?, workDir?, line? }` from a `file.open` host-command
 * payload; `undefined` means malformed (missing/non-string `path`). */
export function fileOpenPayload(
  payload: unknown,
): { path: string; vmName: string | null; workDir: string | null; line?: number } | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { path, vmName, workDir, line } = payload as {
    path?: unknown;
    vmName?: unknown;
    workDir?: unknown;
    line?: unknown;
  };
  if (typeof path !== "string") return undefined;
  return {
    path,
    vmName: typeof vmName === "string" ? vmName : null,
    workDir: typeof workDir === "string" ? workDir : null,
    ...(typeof line === "number" && Number.isFinite(line) ? { line } : {}),
  };
}

/** Parse `{ vmName?, workDir? }` from a `file.search` host-command payload.
 * Both fields are optional; a missing/malformed payload just yields nulls. */
export function fileSearchPayload(payload: unknown): { vmName: string | null; workDir: string | null } {
  if (!payload || typeof payload !== "object") return { vmName: null, workDir: null };
  const { vmName, workDir } = payload as { vmName?: unknown; workDir?: unknown };
  return {
    vmName: typeof vmName === "string" ? vmName : null,
    workDir: typeof workDir === "string" ? workDir : null,
  };
}

/** Host special/module-detail tabs (not ordinary files). Ordinary file paths
 * rejoin the host strip as opaque tab ids (todo 3084); this helper still
 * classifies special identities for restore/filter. */
export function isHostWorkspaceTab(path: string): boolean {
  if (!path) return false;
  if (path.startsWith("ui:") || path.startsWith("artifact:") || path.startsWith("diff:")) return true;
  // Ordinary host tab ids are JSON.stringify([vm, workDir, path]).
  if (path.startsWith("[")) return false;
  // Authenticated `trace.md` is retired (todo 3179 H3), and so are the
  // `link.md` / `links.md` specials (todo 3708: Links and RSS are modules);
  // public FileViewer keeps its own permanent tab and never uses this host
  // classification helper.
  return false;
}

export function isOrdinaryFilePath(path: string): boolean {
  const p = path.replace(/^\.\//, "");
  return !!p && !isHostWorkspaceTab(p) && !p.startsWith("[");
}

/** Special host tabs + ordinary descriptor keys. */
export function isHostTabKey(path: string, ordinaryIds?: ReadonlySet<string> | Record<string, unknown>): boolean {
  if (isHostWorkspaceTab(path)) return true;
  if (!ordinaryIds) return false;
  if (ordinaryIds instanceof Set) return ordinaryIds.has(path);
  return path in ordinaryIds;
}
