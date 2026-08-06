// Host-side note control-plane gestures for the future modules/note UI (plan
// H2, pages/plan-3071-note-module.md decision 7). Mirrors chatHost's
// `usePublishSelectedChatIntent`: one retained intent under the `"note"`
// artifact slug, republished whenever the trace filter or either location's
// VM/work-directory changes. File opens reuse 3068's `file.open` host
// command unchanged (decision 7: "reuse it unchanged" — no `note.openFile`
// twin is registered here).
import { useEffect } from "react";
import { setArtifactIntent } from "../host/intents";

export interface NoteLocationContext {
  vmName: string | null;
  workDir: string | null;
}

/** Host -> note artifact intent: the trace scope (`chatListTraceId`) plus the
 * per-location VM/work-directory context the future panel's left (tab
 * browser) and right (todo-scoped) modes each need via `usePanelLocation()`. */
export function publishNoteIntent(
  todoId: string | null,
  leftVmName: string | null,
  leftWorkDir: string | null,
  rightVmName: string | null,
  rightWorkDir: string | null,
): void {
  setArtifactIntent("note", {
    kind: "trace-scope",
    todoId,
    left: { vmName: leftVmName, workDir: leftWorkDir } satisfies NoteLocationContext,
    right: { vmName: rightVmName, workDir: rightWorkDir } satisfies NoteLocationContext,
    nonce: Date.now(),
  });
}

/** Publish the note intent on every todoId/left/right change (including null). */
export function usePublishNoteIntent(
  todoId: string | null,
  leftVmName: string | null,
  leftWorkDir: string | null,
  rightVmName: string | null,
  rightWorkDir: string | null,
): void {
  useEffect(() => {
    publishNoteIntent(todoId, leftVmName, leftWorkDir, rightVmName, rightWorkDir);
  }, [todoId, leftVmName, leftWorkDir, rightVmName, rightWorkDir]);
}
