// App-registration seam for authenticated Todo detail entry points (todo 3179 H2).
// Host commands and deep-link/header chip handlers live here so tests can execute
// the same wiring App uses, and so payload/route/filter ids cannot be hard-coded
// at the App call site without editing this seam (which the suite covers).
import { registerHostCommand } from "../host/commands";
import { openTodo, type OpenTodoDeps } from "./tagNavigate";
import {
  handleChatOpenTrace,
  handleTodoOpenTrace,
  openTodoDetailFromDeepLink,
  openTodoDetailFromHeaderChip,
  todoIdFromPayload,
} from "./todoDetailNavigate";

export interface TodoDetailEntryPointDeps {
  handleOpenFile: (path: string) => void;
  setChatListTraceId: (id: string | null) => void;
  setSelectedChatId: (id: string | null) => void;
  setChatHide: (hide: boolean) => void;
  /** Mobile drawer close after todo.open; optional so unit tests can omit it. */
  onAfterTodoOpen?: () => void;
  setSidebarPanel?: (panel: "artifact:todo") => void;
}

/**
 * Register todo.open / todo.openTrace / chat.openTrace. IDs come only from the
 * command payload — never from a host selectedTraceId write or a hard-coded
 * literal at the App call site.
 */
export function registerTodoDetailEntryPoints(deps: TodoDetailEntryPointDeps): () => void {
  const openTodoDeps: OpenTodoDeps = {
    setChatListTraceId: deps.setChatListTraceId,
    setSelectedChatId: deps.setSelectedChatId,
    setChatHide: deps.setChatHide,
    handleOpenFile: deps.handleOpenFile,
  };
  const unregisterOpen = registerHostCommand("todo.open", (payload) => {
    const todoId = todoIdFromPayload(payload);
    if (!todoId) return;
    openTodo(todoId, openTodoDeps);
    deps.onAfterTodoOpen?.();
  });
  const unregisterOpenTrace = registerHostCommand("todo.openTrace", (payload) => {
    handleTodoOpenTrace(payload, deps.handleOpenFile);
  });
  const unregisterChatOpenTrace = registerHostCommand("chat.openTrace", (payload) => {
    handleChatOpenTrace(payload, deps.handleOpenFile);
  });
  return () => {
    unregisterOpen();
    unregisterOpenTrace();
    unregisterChatOpenTrace();
  };
}

/** `/trace/:traceId` deep-link body. App must pass the route param as-is. */
export function applyTodoDeepLink(
  urlTraceId: string | null | undefined,
  deps: Pick<TodoDetailEntryPointDeps, "handleOpenFile" | "setSidebarPanel">,
): void {
  openTodoDetailFromDeepLink(urlTraceId, deps.handleOpenFile, deps.setSidebarPanel);
}

/** Header trace-chip body. App must pass chatListTraceId as-is. */
export function applyTodoHeaderChip(
  chatListTraceId: string | null,
  deps: Pick<TodoDetailEntryPointDeps, "handleOpenFile">,
): void {
  openTodoDetailFromHeaderChip(chatListTraceId, deps.handleOpenFile);
}
