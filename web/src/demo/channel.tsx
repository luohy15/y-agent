// Demo-shell state and command registrations (todo 3158 H8 + H6). All state
// exists only in React memory. The restricted runtime routes `runHostCommand`
// here; chat.open also republishes the host-internal selected-chat intent so
// production ChatShell / ChatPanel mounts stay in sync (shell-intent bridge).
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { setArtifactIntent } from "../host/intents";
import {
  demoFileOpenPayload,
  registerDemoArtifactDetailOpener,
  registerDemoHostCommand,
} from "./commands";
import { DEMO_CHROME } from "./chrome";

export interface DemoFile {
  path: string;
  content: string;
}

export type DemoCentreMode = "files" | "chat";

export interface DemoHostState {
  selectedChatId: string | null;
  selectedTodoId: string | null;
  traceFilter: string | null;
  activeFile: DemoFile | null;
  detailSlug: string | null;
  /** Centre column mode; chat.open / file.open / todo detail flip this. */
  centreMode: DemoCentreMode;
  setCentreMode: (mode: DemoCentreMode) => void;
  /** Open a centre tab for todo full view / trace (files mode). */
  detailTab: "todo" | "trace" | null;
  setDetailTab: (tab: "todo" | "trace" | null) => void;
  blockedReason: string | null;
  dismissBlockedReason: () => void;
  clearActiveFile: () => void;
}

const DemoHostStateContext = createContext<DemoHostState | null>(null);

function stringPayload(payload: unknown, key: string): string | null {
  if (!payload || typeof payload !== "object") return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Host -> chat artifact focus intent (mirrors utils/chatHost.publishSelectedChatIntent).
 * Demo chrome supplies fictional vm/bot/work-dir; modules ignore them when unset. */
function publishDemoChatIntent(
  chatId: string | null,
  traceId: string | null,
): void {
  setArtifactIntent("chat", {
    kind: "selected",
    chatId,
    botName: DEMO_CHROME.botName,
    vmName: DEMO_CHROME.vmName,
    defaultWorkDir: DEMO_CHROME.workDir,
    traceId,
    nonce: Date.now(),
  });
}

export interface DemoHostCommandProviderProps {
  children: ReactNode;
  /** Initial centre mode for deep links (`/demo/todo` → files). Default chat. */
  initialCentreMode?: DemoCentreMode;
  /** Initial detail tab for deep links (`/demo/todo` → todo). Default null. */
  initialDetailTab?: "todo" | "trace" | null;
}

export function DemoHostCommandProvider({
  children,
  initialCentreMode = "chat",
  initialDetailTab = null,
}: DemoHostCommandProviderProps) {
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [selectedTodoId, setSelectedTodoId] = useState<string | null>(null);
  const [traceFilter, setTraceFilter] = useState<string | null>(null);
  const [activeFile, setActiveFile] = useState<DemoFile | null>(null);
  const [detailSlug, setDetailSlug] = useState<string | null>(null);
  const [centreMode, setCentreMode] = useState<DemoCentreMode>(initialCentreMode);
  const [detailTab, setDetailTab] = useState<"todo" | "trace" | null>(initialDetailTab);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);

  // Seed the chat intent once so ChatShell's surface="shell" and both panels
  // share a consistent selection channel before any row click (H6 bridge).
  useEffect(() => {
    publishDemoChatIntent(null, null);
  }, []);

  useEffect(() => {
    const unregisterChatOpen = registerDemoHostCommand("chat.open", (payload) => {
      const chatId = stringPayload(payload, "chatId");
      setSelectedChatId(chatId);
      setCentreMode("chat");
      // Keep the latest trace filter on the intent so the right chat panel
      // continues to honor host-side filtering (plan-3046 R7).
      setTraceFilter((current) => {
        publishDemoChatIntent(chatId, current);
        return current;
      });
    });
    const unregisterTodoOpen = registerDemoHostCommand("todo.open", (payload) => {
      const todoId = stringPayload(payload, "todoId");
      setSelectedTodoId(todoId);
      setDetailTab("todo");
      setCentreMode("files");
    });
    const unregisterTodoTrace = registerDemoHostCommand("todo.openTrace", (payload) => {
      const todoId = stringPayload(payload, "todoId");
      setSelectedTodoId(todoId);
      setTraceFilter(todoId);
      setDetailTab("trace");
      setCentreMode("files");
      setSelectedChatId((chatId) => {
        publishDemoChatIntent(chatId, todoId);
        return chatId;
      });
    });
    const unregisterFileOpen = registerDemoHostCommand("file.open", (payload) => {
      const file = demoFileOpenPayload(payload);
      if (file) {
        setActiveFile(file);
        setDetailTab(null);
        setCentreMode("files");
      }
    });
    const unregisterTraceFilter = registerDemoHostCommand("chat.setTraceFilter", (payload) => {
      const traceId = stringPayload(payload, "traceId");
      setTraceFilter(traceId);
      setSelectedChatId((chatId) => {
        publishDemoChatIntent(chatId, traceId);
        return chatId;
      });
    });
    const unregisterBlocked = registerDemoHostCommand("demo.blocked", (payload) => {
      setBlockedReason(
        typeof payload === "string" ? payload : "This action is unavailable in the demo.",
      );
    });
    const unregisterDetailOpener = registerDemoArtifactDetailOpener((slug) => {
      setDetailSlug(slug);
      // Open the matching centre tab for todo (production openArtifactDetail path).
      if (slug === "todo") {
        setDetailTab("todo");
        setCentreMode("files");
      }
    });
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
      centreMode,
      setCentreMode,
      detailTab,
      setDetailTab,
      blockedReason,
      dismissBlockedReason: () => setBlockedReason(null),
      clearActiveFile: () => setActiveFile(null),
    }),
    [
      selectedChatId,
      selectedTodoId,
      traceFilter,
      activeFile,
      detailSlug,
      centreMode,
      detailTab,
      blockedReason,
    ],
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
