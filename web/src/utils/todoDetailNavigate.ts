// Host-side navigation into the Todo module's in-place detail (todo 3179 H2).
// External entry points publish a retained `{ kind: "detail", todoId, nonce }`
// intent and open `ui:todo`; the module's `detail` surface consumes it
// (plan decision 3). `nonce` is wall-clock-ish (`Date.now()`) so a genuine
// post-reload navigation cannot collide with a persisted consumed nonce.
//
// Authenticated entry points (todo.openTrace, chat.openTrace, /trace/:traceId,
// header chip, no-chat openTodo fallback) all funnel through these helpers so
// selection never re-enters host `selectedTraceId` / `trace.md`.
import { artifactTabKey } from "../host/artifacts";
import { setArtifactIntent } from "../host/intents";
import { traceIdFromPayload } from "./chatHost";

/** Open the authenticated Todo detail for `todoId` inside `ui:todo`. */
export function openTodoDetail(
  todoId: string,
  handleOpenFile: (path: string) => void,
): void {
  setArtifactIntent("todo", { kind: "detail", todoId, nonce: Date.now() });
  handleOpenFile(artifactTabKey("todo"));
}

/** Parse `{ todoId }` from a host-command payload; null means malformed. */
export function todoIdFromPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const { todoId } = payload as { todoId?: unknown };
  return typeof todoId === "string" ? todoId : null;
}

/** `todo.openTrace` body: open the in-place detail, never host selectedTraceId. */
export function handleTodoOpenTrace(
  payload: unknown,
  handleOpenFile: (path: string) => void,
): void {
  const todoId = todoIdFromPayload(payload);
  if (!todoId) return;
  openTodoDetail(todoId, handleOpenFile);
}

/** `chat.openTrace` body: same destination as todo.openTrace. */
export function handleChatOpenTrace(
  payload: unknown,
  handleOpenFile: (path: string) => void,
): void {
  const traceId = traceIdFromPayload(payload);
  if (!traceId) return;
  openTodoDetail(traceId, handleOpenFile);
}

/**
 * `/trace/:traceId` deep-link body. Publishes the Todo detail intent and opens
 * `ui:todo` (+ optional sidebar focus). Must not accept or call a
 * `setSelectedTraceId` — that dual authority is exactly the H2 regression.
 */
export function openTodoDetailFromDeepLink(
  urlTraceId: string | null | undefined,
  handleOpenFile: (path: string) => void,
  setSidebarPanel?: (panel: "artifact:todo") => void,
): void {
  if (!urlTraceId) return;
  openTodoDetail(urlTraceId, handleOpenFile);
  setSidebarPanel?.("artifact:todo");
}

/** Header trace-chip body: open the filtered todo's detail. */
export function openTodoDetailFromHeaderChip(
  chatListTraceId: string | null,
  handleOpenFile: (path: string) => void,
): void {
  if (!chatListTraceId) return;
  openTodoDetail(chatListTraceId, handleOpenFile);
}
