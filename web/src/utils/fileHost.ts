// Host-side file control-plane gestures for the future modules/file UI (plan
// sub-task H2, pages/plan-3068-file-module.md decision 6: "File selection
// crosses the existing intent/command seam"). Pure helpers so App.tsx can
// wire host commands / retained context without bloating the shell, and so
// verify unit tests can exercise payload parsing without mounting App. No
// module consumes this yet (M3/M4 build the panel/detail); this is the seam
// only.
import { useEffect } from "react";
import { setArtifactIntent } from "../host/intents";

export interface FileLocationContext {
  vmName: string | null;
  workDir: string | null;
}

/** Module -> host `file.open` request: open the `ui:file` tab and hand the
 * detail surface the requested path plus the VM/work-directory context of
 * the panel that sent it. */
export interface FileOpenAction {
  kind: "open";
  path: string;
  vmName: string | null;
  workDir: string | null;
  nonce: number;
}

/** Module -> host `file.search` request: open the `ui:file` tab and tell the
 * detail surface to show its own search dialog (decision 6: "the module
 * detail owns its internal file tabs and search dialog"). */
export interface FileSearchAction {
  kind: "search";
  vmName: string | null;
  workDir: string | null;
  nonce: number;
}

export type FileAction = FileOpenAction | FileSearchAction;

/** Host -> file artifact retained state, published under the single `"file"`
 * slug (review-3068-file-browser-seam.md finding 1: a `left`/`right` context
 * write and an `open`/`search` action write must not clobber each other,
 * since `useArtifactIntent` keeps only the latest value per slug). `left`
 * and `right` are always both present — right mirrors `selectedVM` +
 * `effectiveWorkDir`, left mirrors the default VM + `currentVmWorkDir` (see
 * the two `<FileTree>` call sites in App.tsx); a future panel mount picks its
 * own half via `usePanelLocation()`. `action` is the most recent open/search
 * request, or `null` before the first one; a future detail surface reacts to
 * `action.nonce` changes. Top-level `nonce` is the shell refresh signal
 * (review-3068-file-panel.md finding 1 / modules/note convention): the host
 * republishes with a fresh value when the right activity rail wants a list
 * refresh, mirroring `refreshKey` on the built-in FileTree. Every publish
 * below reads and re-sends the halves it isn't updating, so a context update
 * never drops an unconsumed action, an action never drops the last-known
 * context, and a refresh never clobbers either. */
export interface FileArtifactIntent {
  left: FileLocationContext;
  right: FileLocationContext;
  action: FileAction | null;
  nonce?: number;
}

const EMPTY_LOCATION: FileLocationContext = { vmName: null, workDir: null };

// Module-scoped mirror of the single published value, so each publish call
// can merge in the half it isn't updating. This is the "one retained state
// shape that always carries both" fix (review finding 1) rather than two
// independent retained slots, since the M3 panel and M4 detail are expected
// to read the same slug together via `usePanelLocation()`.
let lastLeft: FileLocationContext = EMPTY_LOCATION;
let lastRight: FileLocationContext = EMPTY_LOCATION;
let lastAction: FileAction | null = null;
let lastNonce = 0;

function publish(): void {
  setArtifactIntent("file", {
    left: lastLeft,
    right: lastRight,
    action: lastAction,
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

export function publishFileOpenAction(path: string, vmName: string | null, workDir: string | null): void {
  lastAction = { kind: "open", path, vmName, workDir, nonce: Date.now() };
  publish();
}

export function publishFileSearchAction(vmName: string | null, workDir: string | null): void {
  lastAction = { kind: "search", vmName, workDir, nonce: Date.now() };
  publish();
}

/** Host -> file artifact list-refresh signal. Bumps the top-level `nonce`
 * (same field name the note panel reads) without touching left/right/action,
 * so the right activity rail refresh button keeps working after the C1 cut
 * replaces built-in FileTree's `refreshKey` prop. */
export function publishFileRefresh(): void {
  lastNonce = Date.now();
  publish();
}

/** Parse `{ path, vmName?, workDir? }` from a `file.open` host-command
 * payload; `undefined` means malformed (missing/non-string `path`). */
export function fileOpenPayload(
  payload: unknown,
): { path: string; vmName: string | null; workDir: string | null } | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { path, vmName, workDir } = payload as { path?: unknown; vmName?: unknown; workDir?: unknown };
  if (typeof path !== "string") return undefined;
  return {
    path,
    vmName: typeof vmName === "string" ? vmName : null,
    workDir: typeof workDir === "string" ? workDir : null,
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
