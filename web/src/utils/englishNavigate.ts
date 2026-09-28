// Host-side navigation into the English module (todo 3708 A2).
// One live authority: a latched `{ kind: "correction", correctionId, nonce }`
// intent. Both module surfaces consume it; `selectedCorrectionId` stays the
// reload fallback.
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";

export const SELECTED_CORRECTION_ID_KEY = "selectedCorrectionId";

export interface EnglishIntent {
  kind: "correction";
  correctionId: string;
  nonce: number;
}

/** `{ correctionId }` from a host-command payload. Empty or non-string is invalid. */
export function correctionIdFromPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const { correctionId } = payload as { correctionId?: unknown };
  if (typeof correctionId !== "string") return null;
  const id = correctionId.trim();
  return id.length > 0 ? id : null;
}

/** Persist the reload fallback, latch the intent, then open `ui:english`. */
export function openEnglish(
  correctionId: string,
  handleOpenFile: (path: string) => void,
): void {
  const id = correctionId.trim();
  if (!id) return;
  try {
    localStorage.setItem(SELECTED_CORRECTION_ID_KEY, id);
  } catch { /* private mode / quota — the latched intent still navigates */ }
  setArtifactIntent("english", { kind: "correction", correctionId: id, nonce: Date.now() } satisfies EnglishIntent);
  handleOpenFile(artifactTabKey("english"));
}

/** `english.open` body. Invalid payloads are ignored; the tab is not opened. */
export function handleEnglishOpen(
  payload: unknown,
  handleOpenFile: (path: string) => void,
): void {
  const correctionId = correctionIdFromPayload(payload);
  if (!correctionId) return;
  openEnglish(correctionId, handleOpenFile);
}
