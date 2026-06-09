import type { Message } from "../components/MessageList";

// Pure helpers for the "export selected messages as image" feature. Kept separate
// from the DOM capture util so they can be unit-tested without a browser.

// Toggle an index in the selection set, returning a new Set (immutable update for React state).
export function toggleSelection(selected: Set<number>, index: number): Set<number> {
  const next = new Set(selected);
  if (next.has(index)) next.delete(index);
  else next.add(index);
  return next;
}

// Map selected display-list indices back to Message objects, in document order.
// Out-of-range indices are dropped so a stale selection can't crash the export.
export function selectMessagesByIndices(messages: Message[], selectedIndices: Iterable<number>): Message[] {
  const sorted = Array.from(new Set(selectedIndices)).sort((a, b) => a - b);
  const out: Message[] = [];
  for (const i of sorted) {
    if (i >= 0 && i < messages.length) out.push(messages[i]);
  }
  return out;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// Build a download filename like `chat-export-20260609-194512.png`.
export function buildExportFilename(date: Date = new Date()): string {
  const y = date.getFullYear();
  const m = pad2(date.getMonth() + 1);
  const d = pad2(date.getDate());
  const hh = pad2(date.getHours());
  const mm = pad2(date.getMinutes());
  const ss = pad2(date.getSeconds());
  return `chat-export-${y}${m}${d}-${hh}${mm}${ss}.png`;
}
