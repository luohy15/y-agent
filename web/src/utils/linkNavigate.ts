// Host-side navigation into the Link module (todo 3708 A2).
// One live authority: a latched `{ kind: "link", activityId, linkId,
// contentKey, nonce }` intent. Both module surfaces consume it; the three
// `selectedLink*` keys stay the reload fallback (existing legacy behavior).
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";

export const SELECTED_LINK_ID_KEY = "selectedLinkId";
export const SELECTED_LINK_LINK_ID_KEY = "selectedLinkLinkId";
export const SELECTED_LINK_CONTENT_KEY_KEY = "selectedLinkContentKey";

export interface LinkIntent {
  kind: "link";
  activityId: string | null;
  linkId: string | null;
  contentKey: string | null;
  nonce: number;
}

export interface LinkPayload {
  activityId: string | null;
  linkId: string | null;
  contentKey: string | null;
}

/** `{activityId?, linkId?, contentKey?}` from a host-command payload. Needs
 * at least one nonempty ID string (`activityId` or `linkId`); `contentKey`
 * alone is not a valid target. Returns null when invalid. */
export function linkPayloadFromPayload(payload: unknown): LinkPayload | null {
  if (!payload || typeof payload !== "object") return null;
  const { activityId, linkId, contentKey } = payload as {
    activityId?: unknown;
    linkId?: unknown;
    contentKey?: unknown;
  };
  const a = typeof activityId === "string" ? activityId.trim() : "";
  const l = typeof linkId === "string" ? linkId.trim() : "";
  const c = typeof contentKey === "string" ? contentKey.trim() : "";
  if (!a && !l) return null;
  return {
    activityId: a || null,
    linkId: l || null,
    contentKey: c || null,
  };
}

/** Persist the three reload-fallback keys, latch the intent, then open `ui:link`. */
export function openLink(
  payload: LinkPayload,
  handleOpenFile: (path: string) => void,
): void {
  const { activityId, linkId, contentKey } = payload;
  if (!activityId && !linkId) return;
  try {
    if (activityId) localStorage.setItem(SELECTED_LINK_ID_KEY, activityId);
    else localStorage.removeItem(SELECTED_LINK_ID_KEY);
    if (linkId) localStorage.setItem(SELECTED_LINK_LINK_ID_KEY, linkId);
    else localStorage.removeItem(SELECTED_LINK_LINK_ID_KEY);
    if (contentKey) localStorage.setItem(SELECTED_LINK_CONTENT_KEY_KEY, contentKey);
    else localStorage.removeItem(SELECTED_LINK_CONTENT_KEY_KEY);
  } catch { /* private mode / quota — the latched intent still navigates */ }
  setArtifactIntent("link", {
    kind: "link",
    activityId,
    linkId,
    contentKey,
    nonce: Date.now(),
  } satisfies LinkIntent);
  handleOpenFile(artifactTabKey("link"));
}

/** `link.open` body. Invalid payloads are ignored; the tab is not opened. */
export function handleLinkOpen(
  payload: unknown,
  handleOpenFile: (path: string) => void,
): void {
  const parsed = linkPayloadFromPayload(payload);
  if (!parsed) return;
  openLink(parsed, handleOpenFile);
}
