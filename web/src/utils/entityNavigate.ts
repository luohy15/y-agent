// Host-side navigation into the Entity module (todo 3708 A2).
// One live authority: a latched `{ kind: "entity", entityId, nonce }` intent.
// Both module surfaces consume it; `selectedEntityId` stays the reload fallback.
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";

export const SELECTED_ENTITY_ID_KEY = "selectedEntityId";

export interface EntityIntent {
  kind: "entity";
  entityId: string;
  nonce: number;
}

/** `{ entityId }` from a host-command payload. Empty or non-string is invalid. */
export function entityIdFromPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const { entityId } = payload as { entityId?: unknown };
  if (typeof entityId !== "string") return null;
  const id = entityId.trim();
  return id.length > 0 ? id : null;
}

/** Persist the reload fallback, latch the intent, then open `ui:entity`. */
export function openEntity(
  entityId: string,
  handleOpenFile: (path: string) => void,
): void {
  const id = entityId.trim();
  if (!id) return;
  try {
    localStorage.setItem(SELECTED_ENTITY_ID_KEY, id);
  } catch { /* private mode / quota — the latched intent still navigates */ }
  setArtifactIntent("entity", { kind: "entity", entityId: id, nonce: Date.now() } satisfies EntityIntent);
  handleOpenFile(artifactTabKey("entity"));
}

/** `entity.open` body. Invalid payloads are ignored; the tab is not opened. */
export function handleEntityOpen(
  payload: unknown,
  handleOpenFile: (path: string) => void,
): void {
  const entityId = entityIdFromPayload(payload);
  if (!entityId) return;
  openEntity(entityId, handleOpenFile);
}
