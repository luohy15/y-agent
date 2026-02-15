import { useState, useEffect, useRef, useCallback } from "react";
import { useSWRConfig } from "swr";
import { API, getToken, authFetch } from "../api";
import ApprovalModal from "./ApprovalBar";
import MessageList, { type Message, extractContent } from "./MessageList";
import ChatInput, { type ChatInputHandle } from "./ChatInput";

interface ChatViewProps {
  chatId: string | null;
  onChatCreated?: (chatId: string) => void;
  isLoggedIn: boolean;
}

export default function ChatView({ chatId, onChatCreated, isLoggedIn }: ChatViewProps) {
  const { mutate } = useSWRConfig();
  const [messages, setMessages] = useState<Message[]>([]);
  const [showApproval, setShowApproval] = useState(false);
  const [pendingToolCalls, setPendingToolCalls] = useState<Array<{ id: string; function: { name: string; arguments: string }; status?: string }>>([]);
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("autoApprove") === "true");
  const [completed, setCompleted] = useState(false);
  const [newPrompt, setNewPrompt] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [sending, setSending] = useState(false);
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
        body: JSON.stringify({ chat_id: chatId, prompt: text }),
      });
      setFollowUp("");
      connectSSE(chatId, idxRef.current);
    } finally {
      setSending(false);
    }
  }, [followUp, sending, chatId, connectSSE]);

  const createChat = useCallback(async () => {
    const text = newPrompt.trim();
    if (!text || sending || !onChatCreated) return;
    setSending(true);
    try {
      const res = await authFetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, auto_approve: autoApprove }),
      });
      const data = await res.json();
      mutate(`${API}/api/chat/list`);
      setNewPrompt("");
      onChatCreated(data.chat_id);
    } finally {
      setSending(false);
    }
  }, [newPrompt, sending, autoApprove, mutate, onChatCreated]);

  if (!chatId) {
    if (!isLoggedIn) {
      return <div className="flex-1" />;
    }
    return (
      <div className="flex-1 flex flex-col min-h-0" onClick={() => inputRef.current?.focus()}>
        <ChatInput
          ref={inputRef}
          value={newPrompt}
          onChange={setNewPrompt}
          onSubmit={createChat}
          autoApprove={autoApprove}
          onToggleAutoApprove={toggleAutoApprove}
          sending={sending}
          autoFocus
        />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0" onClick={() => inputRef.current?.focus()}>
      <MessageList messages={messages} running={!completed} />
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
      {completed && (
        <ChatInput
          ref={inputRef}
          value={followUp}
          onChange={setFollowUp}
          onSubmit={sendFollowUp}
          autoApprove={autoApprove}
          onToggleAutoApprove={toggleAutoApprove}
          autoFocus
        />
      )}
    </div>
  );
}
