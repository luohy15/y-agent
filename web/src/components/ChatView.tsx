import { useState, useEffect, useRef, useCallback, useMemo, type RefCallback } from "react";
import { useSWRConfig } from "swr";
import { API, getToken, authFetch } from "../api";
import { isPreview, MAIN_DOMAIN } from "../hooks/useAuth";
import MessageList, { type Message, extractContent } from "./MessageList";
import ChatInput, { type ChatInputHandle } from "./ChatInput";
import ChatToc from "./ChatToc";

interface ChatViewProps {
  chatId: string | null;
  onChatCreated?: (chatId: string) => void;
  onClear?: () => void;
  isLoggedIn: boolean;
  gsiReady?: boolean;
  vmName?: string | null;
  botName?: string | null;
  onWorkDirChange?: (workDir: string | null) => void;
  onTopicChange?: (skill: string | null) => void;
  onTraceIdChange?: (traceId: string | null) => void;
  onBackendChange?: (backend: string | null) => void;
  onComplete?: () => void;
  onOpenFile?: (path: string) => void;
  onSelectChat?: (chatId: string) => void;
  onSelectTrace?: (traceId: string) => void;
}

export default function ChatView({ chatId, onChatCreated, onClear, isLoggedIn, gsiReady, vmName, botName, onWorkDirChange, onTopicChange, onTraceIdChange, onBackendChange, onComplete, onOpenFile, onSelectChat, onSelectTrace }: ChatViewProps) {
  const { mutate } = useSWRConfig();
  const [messages, setMessages] = useState<Message[]>([]);
  const [completed, setCompleted] = useState(false);
  const [chatWorkDir, setChatWorkDir] = useState<string | null>(null);
  const [newPrompt, setNewPrompt] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [sending, setSending] = useState(false);
  const [showProgress, setShowProgress] = useState(() => localStorage.getItem("showProgress") === "true");
  const [contextUsage, setContextUsage] = useState<{ used: number; window: number; input: number; output: number; cacheRead: number; cacheCreation: number } | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const idxRef = useRef(0);
  const inputRef = useRef<ChatInputHandle | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const [showSteerInput, setShowSteerInput] = useState(false);
  useEffect(() => { if (completed) setShowSteerInput(false); }, [completed]);

  // Track scroll position to show/hide scroll-to-bottom button
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowScrollBottom(distFromBottom > 200);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [messages]);

  // Virtual keyboard adaptation: adjust container when keyboard appears on tablets
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const onResize = () => {
      const offset = window.innerHeight - viewport.height;
      if (containerRef.current) {
        containerRef.current.style.paddingBottom = offset > 0 ? `${offset}px` : "";
      }
    };
    viewport.addEventListener("resize", onResize);
    viewport.addEventListener("scroll", onResize);
    return () => {
      viewport.removeEventListener("resize", onResize);
      viewport.removeEventListener("scroll", onResize);
    };
  }, []);

  const addMessage = useCallback((msg: Message) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateToolMessage = useCallback((toolCallId: string, updates: Partial<Message>) => {
    setMessages((prev) => prev.map((m) =>
      m.toolCallId === toolCallId ? { ...m, ...updates } : m
    ));
  }, []);

  // Fetch chat detail (work_dir) when chatId changes or chat completes
  useEffect(() => {
    if (!chatId) return;
    authFetch(`${API}/api/chat/detail?chat_id=${encodeURIComponent(chatId)}`)
      .then((r) => r.json())
      .then((data) => {
        const wd = data.work_dir ?? null;
        setChatWorkDir(wd);
        onWorkDirChange?.(wd);
        onTopicChange?.(data.topic ?? null);
        onTraceIdChange?.(data.trace_id ?? null);
        onBackendChange?.(data.backend ?? null);
        if (data.context_window) {
          const input = data.input_tokens || 0;
          const output = data.output_tokens || 0;
          const cacheRead = data.cache_read_input_tokens || 0;
          const cacheCreation = data.cache_creation_input_tokens || 0;
          const used = input + output + cacheRead + cacheCreation;
          setContextUsage({ used, window: data.context_window, input, output, cacheRead, cacheCreation });
        } else {
          setContextUsage(null);
        }
      })
      .catch(() => {});
  }, [chatId, completed, onWorkDirChange]);

  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const parseRawMessage = useCallback((evt: any): Message[] => {
    const msg = evt.data || evt;
    const role = msg.role || "assistant";
    const content = extractContent(msg.content);
    const timestamp = msg.timestamp;
    const result: Message[] = [];

    if (role === "user") {
      result.push({ role: "user", content, timestamp });
    } else if (role === "assistant" && msg.tool_calls) {
      if (content.trim()) {
        result.push({ role: "assistant", content, timestamp });
      }
      for (const tc of msg.tool_calls) {
        const func = tc.function || {};
        let toolArgs: Record<string, unknown> = {};
        try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
        result.push({ role: "tool_pending", content: "", toolName: func.name, arguments: toolArgs, toolCallId: tc.id, timestamp });
      }
    } else if (role === "tool") {
      const tcId = msg.tool_call_id;
      const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
      if (tcId) {
        result.push({ role: denied ? "tool_denied" : "tool_result", content, toolCallId: tcId, timestamp });
      } else {
        result.push({ role: denied ? "tool_denied" : "tool_result", content, toolName: msg.tool, arguments: msg.arguments, timestamp });
      }
    } else {
      result.push({ role: "assistant", content, timestamp });
    }
    return result;
  }, []);

  const connectSSE = useCallback((chatId: string, fromIndex: number) => {
    if (esRef.current) esRef.current.close();
    setCompleted(false);

    const token = getToken();
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`${API}/api/chat/messages?chat_id=${chatId}&last_index=${fromIndex}${tokenParam}`);
    esRef.current = es;

    const handleMessage = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        idxRef.current = (evt.index ?? idxRef.current) + 1;

        const parsed = parseRawMessage(evt);
        for (const m of parsed) {
          if ((m.role === "tool_result" || m.role === "tool_denied") && m.toolCallId) {
            updateToolMessage(m.toolCallId, { role: m.role, content: m.content });
          } else {
            addMessage(m);
          }
        }
      } catch {}
    };

    es.addEventListener("message", (e) => handleMessage(e.data));
    for (const t of ["text", "tool_use", "tool_result"]) {
      es.addEventListener(t, (e) => handleMessage((e as MessageEvent).data));
    }
    es.addEventListener("done", () => {
      setCompleted(true);
      es.close();
      esRef.current = null;
      onCompleteRef.current?.();
    });
    es.addEventListener("error", () => {});
  }, [addMessage, updateToolMessage, parseRawMessage, mutate]);

  useEffect(() => {
    if (!chatId) return;
    setMessages([]);
    setCompleted(false);
    idxRef.current = 0;

    let cancelled = false;

    authFetch(`${API}/api/chat/messages/snapshot?chat_id=${encodeURIComponent(chatId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;

        // Parse all messages at once
        const allMessages: Message[] = [];
        for (const evt of data.messages) {
          const parsed = parseRawMessage(evt);
          for (const m of parsed) {
            if ((m.role === "tool_result" || m.role === "tool_denied") && m.toolCallId) {
              const pendingIdx = allMessages.findIndex(
                (x) => x.toolCallId === m.toolCallId && x.role === "tool_pending"
              );
              if (pendingIdx !== -1) {
                allMessages[pendingIdx] = { ...allMessages[pendingIdx], role: m.role, content: m.content };
                continue;
              }
            }
            allMessages.push(m);
          }
        }

        setMessages(allMessages);
        idxRef.current = data.messages.length;

        if (data.interrupted) {
          setCompleted(true);
        } else if (data.running) {
          connectSSE(chatId, idxRef.current);
        } else if (data.messages.length > 0) {
          setCompleted(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          connectSSE(chatId, 0);
        }
      });

    return () => {
      cancelled = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  const stopChat = useCallback(async () => {
    if (!chatId) return;
    await authFetch(`${API}/api/chat/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId }),
    });
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setCompleted(true);
  }, [chatId]);

  const [shareLabel, setShareLabel] = useState("share");
  const shareChat = useCallback(() => {
    if (!chatId) return;
    const textPromise = authFetch(`${API}/api/chat/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId }),
    })
      .then((res) => res.json())
      .then((data) => new Blob([`${window.location.origin}/s/${data.share_id}`], { type: "text/plain" }));
    navigator.clipboard.write([new ClipboardItem({ "text/plain": textPromise })]).then(() => {
      setShareLabel("copied!");
      setTimeout(() => setShareLabel("share"), 1500);
    });
  }, [chatId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "c" && !completed) {
        e.preventDefault();
        stopChat();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [completed, stopChat]);

  const sendFollowUp = useCallback(async () => {
    const text = followUp.trim();
    if (!text || sending || !chatId) return;
    setSending(true);
    try {
      await authFetch(`${API}/api/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, prompt: text, ...(vmName ? { vm_name: vmName } : {}), ...(botName ? { bot_name: botName } : {}), ...(chatWorkDir ? { work_dir: chatWorkDir } : {}) }),
      });
      setFollowUp("");
      connectSSE(chatId, idxRef.current);
    } finally {
      setSending(false);
    }
  }, [followUp, sending, chatId, vmName, botName, chatWorkDir, connectSSE]);

  const sendSteer = useCallback(async () => {
    const text = followUp.trim();
    if (!text || sending || !chatId) return;
    setSending(true);
    try {
      await authFetch(`${API}/api/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          prompt: text,
          ...(vmName ? { vm_name: vmName } : {}),
          ...(botName ? { bot_name: botName } : {}),
          ...(chatWorkDir ? { work_dir: chatWorkDir } : {}),
        }),
      });
      setFollowUp("");
      setShowSteerInput(false);
    } finally {
      setSending(false);
    }
  }, [followUp, sending, chatId, vmName, botName, chatWorkDir]);

  const handleOpenFile = useCallback((path: string) => {
    if (chatWorkDir && !path.startsWith("/")) {
      onOpenFile?.(`${chatWorkDir}/${path}`);
    } else {
      onOpenFile?.(path);
    }
  }, [chatWorkDir, onOpenFile]);

  const createChat = useCallback(async () => {
    const text = newPrompt.trim();
    if (!text || sending || !onChatCreated) return;
    setSending(true);
    try {
      const res = await authFetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, ...(vmName ? { vm_name: vmName } : {}), ...(botName ? { bot_name: botName } : {}) }),
      });
      const data = await res.json();
      const now = new Date().toISOString();
      const newChat = { chat_id: data.chat_id, title: text, created_at: now, updated_at: now };
      mutate(
        (key: unknown) => typeof key === "string" && key.startsWith(`${API}/api/chat/list`) && key.includes("offset=0"),
        (current: unknown) => [newChat, ...((current as unknown[]) || [])],
        { revalidate: true },
      );
      setNewPrompt("");
      onChatCreated(data.chat_id);
    } finally {
      setSending(false);
    }
  }, [newPrompt, sending, vmName, botName, mutate, onChatCreated]);

  if (!chatId) {
    if (!isLoggedIn) {
      if (isPreview) {
        const loginUrl = `https://${MAIN_DOMAIN}?auth_redirect=${encodeURIComponent(window.location.origin)}`;
        return (
          <div className="flex-1 flex flex-col items-center justify-center gap-4">
            <a
              href={loginUrl}
              className="px-5 py-2.5 bg-sol-base02 border border-sol-base01 text-sol-base1 rounded-md text-sm font-semibold cursor-pointer hover:bg-sol-base01 hover:text-sol-base2"
            >
              Sign in with Google
            </a>
          </div>
        );
      }
      const signinRef: RefCallback<HTMLDivElement> = (node) => {
        if (!node || !gsiReady) return;
        (window as any).google.accounts.id.renderButton(node, {
          theme: "filled_black",
          size: "large",
          shape: "pill",
        });
      };
      return (
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <a
            href="/t/7ef7c6"
            className="px-4 py-2 bg-sol-cyan text-sol-base03 rounded-md text-sm font-semibold cursor-pointer"
          >
            Demo Trace
          </a>
          <div className="relative inline-flex items-center justify-center">
            <span className="px-5 py-2.5 bg-sol-base02 border border-sol-base021 text-sol-base1 rounded-md text-sm font-semibold pointer-events-none">
              Sign in with Google
            </span>
            <div ref={signinRef} className="absolute inset-0 opacity-[0.01] overflow-hidden [&_iframe]{min-width:100%!important;min-height:100%!important}" />
          </div>
        </div>
      );
    }
    return (
      <div className="flex-1 flex flex-col min-h-0 justify-end sm:justify-start">
        <ChatInput
          ref={inputRef}
          value={newPrompt}
          onChange={setNewPrompt}
          onSubmit={createChat}
          onClear={onClear}
          sending={sending}
          autoFocus
        />
      </div>
    );
  }

  const formatTokens = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M` : n >= 1_000 ? `${Math.round(n / 1_000)}K` : String(n);

  const numTurns = messages.filter((m) => m.role === "user").length;
  const contextBadge = contextUsage ? (() => {
    const pct = Math.min(100, Math.round((contextUsage.used / contextUsage.window) * 100));
    const color = pct >= 80 ? "bg-sol-red" : pct >= 50 ? "bg-sol-yellow" : "bg-sol-green";
    return (
      <span className="relative group inline-flex items-center gap-1.5 font-mono px-2 py-0.5 rounded text-xs sm:text-[0.7rem] font-semibold bg-sol-base02 text-sol-base01 cursor-default">
        <span className="relative w-12 h-1.5 rounded-full bg-sol-base01/30 overflow-hidden">
          <span className={`absolute inset-y-0 left-0 rounded-full ${color}`} style={{ width: `${pct}%` }} />
        </span>
        {pct}%
        <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 z-50">
          <div className="bg-sol-base02 border border-sol-base01/30 rounded px-2.5 py-1.5 text-xs font-mono text-sol-base1 whitespace-nowrap shadow-lg">
            <div className="font-semibold text-sol-base2 mb-1">{formatTokens(contextUsage.used)} / {formatTokens(contextUsage.window)}</div>
            <div className="flex flex-col gap-0.5 text-[0.65rem]">
              <span>Input: {formatTokens(contextUsage.input)}</span>
              <span>Output: {formatTokens(contextUsage.output)}</span>
              <span>Cache read: {formatTokens(contextUsage.cacheRead)}</span>
              <span>Cache write: {formatTokens(contextUsage.cacheCreation)}</span>
              <span>Turns: {numTurns}</span>
            </div>
          </div>
        </div>
      </span>
    );
  })() : null;

  const processDetailButtons = (
    <button
      onClick={() => { const next = !showProgress; setShowProgress(next); localStorage.setItem("showProgress", String(next)); }}
      className={`font-mono cursor-pointer px-2 py-0.5 rounded text-xs sm:text-[0.7rem] font-semibold ${showProgress ? "bg-sol-cyan text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
    >
      {showProgress ? "progress ●" : "progress ○"}
    </button>
  );

  return (
    <div ref={containerRef} className="flex-1 flex flex-col min-w-0 min-h-0 overflow-x-hidden">
      <div className="flex-1 flex min-h-0 relative">
        <MessageList messages={messages} running={!completed} showProgress={showProgress} onOpenFile={handleOpenFile} onSelectChat={onSelectChat} onSelectTrace={onSelectTrace} scrollContainerRef={scrollRef} />
        <ChatToc messages={messages} containerRef={scrollRef} />
        {showScrollBottom && (
          <button
            onClick={() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 w-8 h-8 rounded-full bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center shadow-lg cursor-pointer hover:bg-sol-base01/30"
            title="Scroll to bottom"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        )}
      </div>
      {!completed && (
        <div className="mx-4 border-t border-sol-base02 shrink-0 px-2 py-2 flex items-center gap-3 text-sm sm:text-xs select-none">
          {processDetailButtons}
          {contextBadge}
          <button onClick={() => setShowSteerInput(true)} className="px-2 py-0.5 bg-sol-base02 text-sol-base1 rounded text-xs font-semibold cursor-pointer hover:bg-sol-base01/30">Steer</button>
          <button onClick={stopChat} className="px-2 py-0.5 bg-sol-red text-sol-base3 rounded text-xs font-semibold cursor-pointer">Stop</button>
        </div>
      )}
      {(completed || showSteerInput) && (
        <ChatInput
          ref={inputRef}
          value={followUp}
          onChange={setFollowUp}
          onSubmit={completed ? sendFollowUp : sendSteer}
          onClear={onClear}
          sending={sending}
          autoFocus
          placeholder={completed ? undefined : "Steer the agent..."}
          extraButtons={completed ? <>
            {processDetailButtons}
            {contextBadge}
            <button onClick={shareChat} className={`ml-auto font-mono cursor-pointer px-2 py-0.5 rounded text-xs font-semibold ${shareLabel === "copied!" ? "bg-sol-green text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}>{shareLabel}</button>
          </> : null}
        />
      )}
    </div>
  );
}
