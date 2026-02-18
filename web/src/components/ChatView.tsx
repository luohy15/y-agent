import { useState, useEffect, useRef, useCallback, type RefCallback } from "react";
import { useSWRConfig } from "swr";
import { API, getToken, authFetch } from "../api";
import { isPreview, MAIN_DOMAIN } from "../hooks/useAuth";
import ApprovalModal from "./ApprovalBar";
import MessageList, { type Message, extractContent } from "./MessageList";
import ChatInput, { type ChatInputHandle } from "./ChatInput";

interface ChatViewProps {
  chatId: string | null;
  onChatCreated?: (chatId: string) => void;
  onClear?: () => void;
  isLoggedIn: boolean;
  gsiReady?: boolean;
  vmName?: string | null;
}

export default function ChatView({ chatId, onChatCreated, onClear, isLoggedIn, gsiReady, vmName }: ChatViewProps) {
  const { mutate } = useSWRConfig();
  const [messages, setMessages] = useState<Message[]>([]);
  const [showApproval, setShowApproval] = useState(false);
  const [pendingToolCalls, setPendingToolCalls] = useState<Array<{ id: string; function: { name: string; arguments: string }; status?: string }>>([]);
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("autoApprove") === "true");
  const [completed, setCompleted] = useState(false);
  const [newPrompt, setNewPrompt] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [sending, setSending] = useState(false);
  const [showProcess, setShowProcess] = useState(() => localStorage.getItem("showProcess") === "true");
  const [showDetail, setShowDetail] = useState(() => localStorage.getItem("showDetail") === "true");
  const esRef = useRef<EventSource | null>(null);
  const idxRef = useRef(0);
  const inputRef = useRef<ChatInputHandle | null>(null);

  const toggleAutoApprove = useCallback(async () => {
    const next = !autoApprove;
    setAutoApprove(next);
    localStorage.setItem("autoApprove", String(next));
    if (!chatId) return;
    await authFetch(`${API}/api/chat/auto_approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, auto_approve: next }),
    });
  }, [chatId, autoApprove]);

  const addMessage = useCallback((msg: Message) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateToolMessage = useCallback((toolCallId: string, updates: Partial<Message>) => {
    setMessages((prev) => prev.map((m) =>
      m.toolCallId === toolCallId ? { ...m, ...updates } : m
    ));
  }, []);

  // Fetch chat detail (auto_approve, etc.) when chatId changes
  useEffect(() => {
    if (!chatId) return;
    authFetch(`${API}/api/chat/detail?chat_id=${encodeURIComponent(chatId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.auto_approve !== undefined) setAutoApprove(data.auto_approve);
      })
      .catch(() => {});
  }, [chatId]);

  const connectSSE = useCallback((chatId: string, fromIndex: number) => {
    if (esRef.current) esRef.current.close();
    setCompleted(false);
    setShowApproval(false);
    setPendingToolCalls([]);

    const token = getToken();
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`${API}/api/chat/messages?chat_id=${chatId}&last_index=${fromIndex}${tokenParam}`);
    esRef.current = es;

    const handleMessage = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const msg = evt.data || evt;
        const role = msg.role || "assistant";
        const content = extractContent(msg.content);
        const timestamp = msg.timestamp;
        idxRef.current = (evt.index ?? idxRef.current) + 1;

        if (role === "user") {
          addMessage({ role: "user", content, timestamp });
        } else if (role === "assistant" && msg.tool_calls) {
          if (content.trim()) {
            addMessage({ role: "assistant", content, timestamp });
          }
          for (const tc of msg.tool_calls) {
            const func = tc.function || {};
            let toolArgs: Record<string, unknown> = {};
            try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
            addMessage({ role: "tool_pending", content: "", toolName: func.name, arguments: toolArgs, toolCallId: tc.id, timestamp });
          }
        } else if (role === "tool") {
          const tcId = msg.tool_call_id;
          const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
          if (tcId) {
            updateToolMessage(tcId, { role: denied ? "tool_denied" : "tool_result", content });
          } else {
            addMessage({ role: denied ? "tool_denied" : "tool_result", content, toolName: msg.tool, arguments: msg.arguments, timestamp });
          }
        } else {
          addMessage({ role: "assistant", content, timestamp });
        }
      } catch {}
    };

    const handleAsk = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const data = evt.data || evt;
        const toolCalls = data.tool_calls || [];
        setPendingToolCalls(toolCalls);
        setShowApproval(true);
      } catch {}
    };

    es.addEventListener("message", (e) => handleMessage(e.data));
    for (const t of ["text", "tool_use", "tool_result"]) {
      es.addEventListener(t, (e) => handleMessage((e as MessageEvent).data));
    }
    es.addEventListener("ask", (e) => handleAsk((e as MessageEvent).data));
    es.addEventListener("done", () => {
      setCompleted(true);
      es.close();
      esRef.current = null;
      mutate(`${API}/api/chat/list`);
    });
    es.addEventListener("error", () => {});
  }, [addMessage, updateToolMessage, mutate]);

  useEffect(() => {
    if (!chatId) return;
    setMessages([]);
    idxRef.current = 0;
    connectSSE(chatId, 0);
    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [chatId, connectSSE]);

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
    setShowApproval(false);
    setPendingToolCalls([]);
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
      if (((e.ctrlKey && e.key === "c") || e.key === "Escape") && !completed) {
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
        body: JSON.stringify({ chat_id: chatId, prompt: text, ...(vmName ? { vm_name: vmName } : {}) }),
      });
      setFollowUp("");
      connectSSE(chatId, idxRef.current);
    } finally {
      setSending(false);
    }
  }, [followUp, sending, chatId, vmName, connectSSE]);

  const createChat = useCallback(async () => {
    const text = newPrompt.trim();
    if (!text || sending || !onChatCreated) return;
    setSending(true);
    try {
      const res = await authFetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, auto_approve: autoApprove, ...(vmName ? { vm_name: vmName } : {}) }),
      });
      const data = await res.json();
      mutate(`${API}/api/chat/list`);
      setNewPrompt("");
      onChatCreated(data.chat_id);
    } finally {
      setSending(false);
    }
  }, [newPrompt, sending, autoApprove, vmName, mutate, onChatCreated]);

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
            href="/s/425162"
            className="px-4 py-2 bg-sol-cyan text-sol-base03 rounded-md text-sm font-semibold cursor-pointer"
          >
            Demo
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
          autoApprove={autoApprove}
          onToggleAutoApprove={toggleAutoApprove}
          sending={sending}
          autoFocus
        />
      </div>
    );
  }

  const processDetailButtons = (
    <>
      <button
        onClick={() => { const next = !showProcess; setShowProcess(next); localStorage.setItem("showProcess", String(next)); if (!next) { setShowDetail(false); localStorage.setItem("showDetail", "false"); } }}
        className={`font-mono cursor-pointer px-3 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-[0.7rem] font-semibold ${showProcess ? "bg-sol-cyan text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
      >
        {showProcess ? "process ●" : "process ○"}
      </button>
      {showProcess && (
        <button
          onClick={() => { const next = !showDetail; setShowDetail(next); localStorage.setItem("showDetail", String(next)); }}
          className={`font-mono cursor-pointer px-3 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-[0.7rem] font-semibold ${showDetail ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
        >
          {showDetail ? "detail ●" : "detail ○"}
        </button>
      )}
    </>
  );

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-x-hidden">
      <MessageList messages={messages} running={!completed} showProcess={showProcess} showDetail={showDetail} />
      <ApprovalModal
        chatId={chatId}
        toolCalls={pendingToolCalls}
        visible={showApproval}
        onApproved={() => {
          setShowApproval(false);
          setPendingToolCalls([]);
          mutate(`${API}/api/chat/list`);
        }}
        onClose={() => setShowApproval(false)}
      />
      {!completed && !showApproval && pendingToolCalls.length > 0 && (
        <div className="px-6 py-3 border-t border-sol-base022 shrink-0 flex justify-center">
          <button
            onClick={() => setShowApproval(true)}
            className="px-4 py-2 bg-sol-yellow text-sol-base03 rounded-md text-sm font-semibold cursor-pointer"
          >
            Need Approve
          </button>
        </div>
      )}
      {!completed && (
        <div className="mx-4 border-t border-sol-base02 shrink-0 px-2 py-2 flex items-center gap-3 text-sm sm:text-xs select-none">
          <button onClick={toggleAutoApprove} className={`sm:hidden font-mono cursor-pointer px-3 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-xs font-semibold ${autoApprove ? "bg-sol-violet text-sol-base3" : "bg-sol-base02 text-sol-base01"}`}>{autoApprove ? "auto approve on" : "auto approve off"}</button>
          <span onClick={toggleAutoApprove} className="hidden sm:inline cursor-pointer text-xs"><span className="font-mono">&gt;&gt;</span> <span className={autoApprove ? "text-sol-violet" : "text-sol-base01"}>{autoApprove ? "auto approve on" : "auto approve off"}</span></span>
          {processDetailButtons}
          <button onClick={stopChat} className="sm:hidden px-3 py-1 bg-sol-red text-sol-base3 rounded text-sm sm:text-xs font-semibold cursor-pointer">Stop</button>
          <span className="hidden sm:inline text-sol-base01 font-mono ml-auto">Esc / Ctrl+C to stop</span>
        </div>
      )}
      {completed && (
        <ChatInput
          ref={inputRef}
          value={followUp}
          onChange={setFollowUp}
          onSubmit={sendFollowUp}
          onClear={onClear}
          autoApprove={autoApprove}
          onToggleAutoApprove={toggleAutoApprove}
          sending={sending}
          autoFocus
          extraButtons={<>
            {processDetailButtons}
            <button onClick={shareChat} className={`ml-auto font-mono cursor-pointer px-3 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-xs font-semibold ${shareLabel === "copied!" ? "bg-sol-green text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}>{shareLabel}</button>
          </>}
        />
      )}
    </div>
  );
}
