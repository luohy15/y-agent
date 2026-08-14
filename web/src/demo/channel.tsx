// Demo-shell state and command registrations (todo 3158 H8). All state exists
// only in React memory. The H6 shell consumes this channel instead of importing
// the authenticated host command registry.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  demoFileOpenPayload,
  registerDemoArtifactDetailOpener,
  registerDemoHostCommand,
} from "./commands";

export interface DemoFile {
  path: string;
  content: string;
}

export interface DemoHostState {
  selectedChatId: string | null;
  selectedTodoId: string | null;
  traceFilter: string | null;
  activeFile: DemoFile | null;
  detailSlug: string | null;
  blockedReason: string | null;
  dismissBlockedReason: () => void;
}

const DemoHostStateContext = createContext<DemoHostState | null>(null);

function stringPayload(payload: unknown, key: string): string | null {
  if (!payload || typeof payload !== "object") return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function DemoHostCommandProvider({ children }: { children: ReactNode }) {
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [selectedTodoId, setSelectedTodoId] = useState<string | null>(null);
  const [traceFilter, setTraceFilter] = useState<string | null>(null);
  const [activeFile, setActiveFile] = useState<DemoFile | null>(null);
  const [detailSlug, setDetailSlug] = useState<string | null>(null);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);

  useEffect(() => {
    const unregisterChatOpen = registerDemoHostCommand("chat.open", (payload) => {
      setSelectedChatId(stringPayload(payload, "chatId"));
    });
    const unregisterTodoOpen = registerDemoHostCommand("todo.open", (payload) => {
      setSelectedTodoId(stringPayload(payload, "todoId"));
    });
    const unregisterTodoTrace = registerDemoHostCommand("todo.openTrace", (payload) => {
      const todoId = stringPayload(payload, "todoId");
      setSelectedTodoId(todoId);
      setTraceFilter(todoId);
    });
    const unregisterFileOpen = registerDemoHostCommand("file.open", (payload) => {
      const file = demoFileOpenPayload(payload);
      if (file) setActiveFile(file);
    });
    const unregisterTraceFilter = registerDemoHostCommand("chat.setTraceFilter", (payload) => {
      setTraceFilter(stringPayload(payload, "traceId"));
    });
    const unregisterBlocked = registerDemoHostCommand("demo.blocked", (payload) => {
      setBlockedReason(typeof payload === "string" ? payload : "This action is unavailable in the demo.");
    });
    const unregisterDetailOpener = registerDemoArtifactDetailOpener(setDetailSlug);
    return () => {
      unregisterChatOpen();
      unregisterTodoOpen();
      unregisterTodoTrace();
      unregisterFileOpen();
      unregisterTraceFilter();
      unregisterBlocked();
      unregisterDetailOpener();
    };
  }, []);

  const value = useMemo<DemoHostState>(
    () => ({
      selectedChatId,
      selectedTodoId,
      traceFilter,
      activeFile,
      detailSlug,
      blockedReason,
      dismissBlockedReason: () => setBlockedReason(null),
    }),
    [selectedChatId, selectedTodoId, traceFilter, activeFile, detailSlug, blockedReason],
  );
  return <DemoHostStateContext.Provider value={value}>{children}</DemoHostStateContext.Provider>;
}

export function useDemoHostState(): DemoHostState {
  const state = useContext(DemoHostStateContext);
  if (!state) throw new Error("useDemoHostState must be rendered under DemoHostCommandProvider");
  return state;
}

/** A short, non-blocking explanation for a demo action that cannot honestly be
 * simulated. The shell keeps this mounted so every surface shares one toast. */
export function DemoBlockedToast() {
  const { blockedReason, dismissBlockedReason } = useDemoHostState();

  useEffect(() => {
    if (!blockedReason) return;
    const timer = window.setTimeout(dismissBlockedReason, 2200);
    return () => window.clearTimeout(timer);
  }, [blockedReason, dismissBlockedReason]);

  if (!blockedReason) return null;
  return (
    <div
      role="status"
      className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded border border-sol-base02 bg-sol-base02 px-3 py-1.5 text-xs text-sol-base1 shadow-float"
    >
      {blockedReason}
    </div>
  );
}
