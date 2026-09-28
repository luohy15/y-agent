// Host-side navigation into the RSS module (todo 3708 A2).
// One live authority: a latched `{ kind: "feed", feedId, label, nonce }`
// intent. Selection is not persisted (legacy `selectedFeedId` is plain
// useState, so a reload shows "No feed selected" — kept as-is).
// `feedId: null` is the Clear action; it keeps today's semantics of an
// unfiltered LinkList. `__all_rss__` (ALL_RSS_FEEDS_ID) passes through
// verbatim.
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";

export interface RssIntent {
  kind: "feed";
  feedId: string | null;
  label: string | null;
  nonce: number;
}

export interface RssPayload {
  feedId: string | null;
  label: string | null;
}

/** `{feedId?, label?}` from a host-command payload. `feedId` may be a
 * nonempty string or `null` (Clear); any other shape is invalid. */
export function rssPayloadFromPayload(payload: unknown): RssPayload | null {
  if (!payload || typeof payload !== "object") return null;
  const { feedId, label } = payload as { feedId?: unknown; label?: unknown };
  if (feedId !== null && typeof feedId !== "string") return null;
  const f = typeof feedId === "string" ? feedId.trim() : null;
  if (feedId !== null && !f) return null;
  const l = typeof label === "string" ? label.trim() : "";
  return { feedId: f, label: l || null };
}

/** Latch the intent then open `ui:rss`. Selection is not persisted. */
export function openRss(
  payload: RssPayload,
  handleOpenFile: (path: string) => void,
): void {
  setArtifactIntent("rss", {
    kind: "feed",
    feedId: payload.feedId,
    label: payload.label,
    nonce: Date.now(),
  } satisfies RssIntent);
  handleOpenFile(artifactTabKey("rss"));
}

/** `rss.open` body. An invalid payload is ignored; the tab is not opened. */
export function handleRssOpen(
  payload: unknown,
  handleOpenFile: (path: string) => void,
): void {
  const parsed = rssPayloadFromPayload(payload);
  if (!parsed) return;
  openRss(parsed, handleOpenFile);
}
