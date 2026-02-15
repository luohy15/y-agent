import { useState, useEffect, useRef, useCallback, type RefCallback } from "react";
import { useSWRConfig } from "swr";
import { API, getToken, authFetch } from "../api";
import ApprovalModal from "./ApprovalBar";
import NewChatInput from "./NewChatInput";
import MessageList, { type Message, extractContent } from "./MessageList";

interface ChatViewProps {
  chatId: string | null;
  onChatCreated?: (chatId: string) => void;
  isLoggedIn: boolean;
  gsiReady: boolean;
}

export default function ChatView({ chatId, onChatCreated, isLoggedIn, gsiReady }: ChatViewProps) {
  const { mutate } = useSWRConfig();
  const [messages, setMessages] = useState<Message[]>([]);
  const [showApproval, setShowApproval] = useState(false);
  const [pendingToolCalls, setPendingToolCalls] = useState<Array<{ id: string; function: { name: string; arguments: string }; status?: string }>>([]);
  const [autoApprove, setAutoApprove] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [sending, setSending] = useState(false);
  const [sharing, setSharing] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const idxRef = useRef(0);

  const toggleAutoApprove = useCallback(async () => {
    if (!chatId) return;
    const next = !autoApprove;
    setAutoApprove(next);
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

  const shareChat = useCallback(async () => {
    if (!chatId || sharing) return;
    setSharing(true);
    try {
      const res = await authFetch(`${API}/api/chat/share`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId }),
      });
      const data = await res.json();
      const shareUrl = `${window.location.origin}/s/${data.share_id}`;
      await navigator.clipboard.writeText(shareUrl);
    } finally {
      setSharing(false);
    }
  }, [chatId, sharing]);

  const sendFollowUp = useCallback(async () => {
    const text = followUp.trim();
    if (!text || sending || !chatId) return;
    setSending(true);
    try {
      await authFetch(`${API}/api/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, prompt: text }),
      });
      setFollowUp("");
      connectSSE(chatId, idxRef.current);
    } finally {
      setSending(false);
    }
  }, [followUp, sending, chatId, connectSSE]);

  const signinRef: RefCallback<HTMLDivElement> = useCallback((node) => {
    if (!node || isLoggedIn || !gsiReady) return;
    (window as any).google.accounts.id.renderButton(node, {
      theme: "filled_black",
      size: "large",
      shape: "pill",
    });
  }, [isLoggedIn, gsiReady]);

  if (!chatId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        {isLoggedIn && onChatCreated ? (
          <NewChatInput onCreated={onChatCreated} />
        ) : (
          <div className="relative inline-flex items-center justify-center">
            <span className="px-5 py-2.5 bg-sol-base02 border border-sol-base01 text-sol-base1 rounded-md text-sm font-semibold pointer-events-none">
              Sign in with Google
            </span>
            <div ref={signinRef} className="absolute inset-0 opacity-[0.01] overflow-hidden [&_iframe]{min-width:100%!important;min-height:100%!important}" />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="flex items-center justify-between px-6 py-2 border-b border-sol-base02 shrink-0">
        <label className="flex items-center gap-2 text-xs text-sol-base1 cursor-pointer select-none">
          <span>Auto-approve</span>
          <button
            onClick={toggleAutoApprove}
            className={`relative w-8 h-4 rounded-full transition-colors ${autoApprove ? "bg-sol-green" : "bg-sol-base02"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-sol-base3 transition-transform ${autoApprove ? "translate-x-4" : ""}`} />
          </button>
        </label>
        <button
          onClick={shareChat}
          disabled={sharing}
          className="px-3 py-1 text-xs text-sol-base1 border border-sol-base01 rounded-md hover:bg-sol-base02 cursor-pointer disabled:opacity-40 disabled:cursor-default"
        >
          {sharing ? "..." : "Share"}
        </button>
      </div>
      <MessageList messages={messages} />
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
      {!completed && !showApproval && (
        <div className="px-6 py-3 border-t border-sol-base02 shrink-0 flex justify-center gap-3">
          {pendingToolCalls.length > 0 && (
            <button
              onClick={() => setShowApproval(true)}
              className="px-4 py-2 bg-sol-yellow text-sol-base03 rounded-md text-sm font-semibold cursor-pointer"
            >
              Need Approve
            </button>
          )}
          <button
            onClick={stopChat}
            className="px-4 py-2 bg-sol-red text-sol-base3 rounded-md text-sm font-semibold cursor-pointer"
          >
            Stop
          </button>
        </div>
      )}
      {completed && (
        <div className="px-6 py-3 border-t border-sol-base02 shrink-0">
          <div className="flex gap-2">
            <input
              type="text"
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendFollowUp(); } }}
              placeholder="Send a follow-up message..."
              autoFocus
              className="flex-1 px-3 py-2 bg-sol-base02 border border-sol-base01 rounded-md text-base text-sol-base0 outline-none focus:border-sol-blue"
            />
            <button
              onClick={sendFollowUp}
              disabled={!followUp.trim() || sending}
              className="px-4 py-2 bg-sol-blue text-sol-base03 rounded-md text-sm font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default"
            >
              {sending ? "..." : "Send"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
