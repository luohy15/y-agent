import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router";
import { API, getToken } from "../api";
import MessageList, { type Message, extractContent } from "./MessageList";

function parseMessages(rawMessages: any[]): Message[] {
  // Build tool_call_id → {name, args} map from assistant messages
  const toolCallInfo: Record<string, { name: string; args: Record<string, unknown> }> = {};
  for (const msg of rawMessages) {
    if (msg.role === "assistant" && msg.tool_calls) {
      for (const tc of msg.tool_calls) {
        const func = tc.function || {};
        let toolArgs: Record<string, unknown> = {};
        try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
        toolCallInfo[tc.id] = { name: func.name, args: toolArgs };
      }
    }
  }

  const result: Message[] = [];
  for (const msg of rawMessages) {
    const role = msg.role || "assistant";
    const content = extractContent(msg.content);

    if (role === "user") {
      result.push({ role: "user", content, timestamp: msg.timestamp });
    } else if (role === "assistant" && msg.tool_calls) {
      if (content.trim()) {
        result.push({ role: "assistant", content, timestamp: msg.timestamp });
      }
      // Skip tool_pending — tool_result will show the command
    } else if (role === "tool") {
      const info = toolCallInfo[msg.tool_call_id];
      const toolName = info?.name || msg.tool;
      const toolArgs = info?.args || msg.arguments;
      const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
      result.push({ role: denied ? "tool_denied" : "tool_result", content, toolName, arguments: toolArgs, timestamp: msg.timestamp });
    } else {
      result.push({ role: "assistant", content, timestamp: msg.timestamp });
    }
  }
  return result;
}

export default function ShareView() {
  const { shareId } = useParams<{ shareId: string }>();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showProcess, setShowProcess] = useState(() => localStorage.getItem("showProcess") === "true");
  const [showDetail, setShowDetail] = useState(() => localStorage.getItem("showDetail") === "true");
  const [shareLabel, setShareLabel] = useState("share");
  const isLoggedIn = !!getToken();

  useEffect(() => {
    if (!shareId) return;
    setLoading(true);
    setError(null);
    fetch(`${API}/api/chat/share?share_id=${encodeURIComponent(shareId)}`)
      .then((r) => {
        if (!r.ok) throw new Error("Shared chat not found");
        return r.json();
      })
      .then((data) => {
        setMessages(parseMessages(data.messages || []));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [shareId]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-sol-base01 text-sm">Loading...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-sol-red text-sm">{error}</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-2 border-b border-sol-base02 shrink-0">
        <div className="max-w-3xl mx-auto w-full">
          <span className="text-xs text-sol-base01">Shared conversation</span>
        </div>
      </div>
      <MessageList messages={messages} centered showProcess={showProcess} showDetail={showDetail} />
      <div className="mx-4 border-t border-sol-base02 shrink-0 px-2 py-1 flex items-center justify-center gap-2 text-xs select-none">
        <button
          onClick={() => { const next = !showProcess; setShowProcess(next); localStorage.setItem("showProcess", String(next)); if (!next) { setShowDetail(false); localStorage.setItem("showDetail", "false"); } }}
          className={`font-mono cursor-pointer px-2 py-0.5 rounded text-[0.7rem] font-semibold ${showProcess ? "bg-sol-cyan text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
        >
          {showProcess ? "process ●" : "process ○"}
        </button>
        {showProcess && (
          <button
            onClick={() => { const next = !showDetail; setShowDetail(next); localStorage.setItem("showDetail", String(next)); }}
            className={`font-mono cursor-pointer px-2 py-0.5 rounded text-[0.7rem] font-semibold ${showDetail ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
          >
            {showDetail ? "detail ●" : "detail ○"}
          </button>
        )}
        <button
          onClick={() => { navigator.clipboard.writeText(window.location.href); setShareLabel("copied!"); setTimeout(() => setShareLabel("share"), 1500); }}
          className={`font-mono cursor-pointer px-2 py-0.5 rounded text-[0.7rem] font-semibold ${shareLabel === "copied!" ? "bg-sol-green text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
        >
          {shareLabel}
        </button>
      </div>
      <div className="px-6 py-3 shrink-0 flex items-center justify-center gap-3">
        <button
          onClick={() => navigate(isLoggedIn ? "/" : "/")}
          className="px-4 py-2 bg-sol-blue text-sol-base03 rounded-md text-sm font-semibold cursor-pointer"
        >
          {isLoggedIn ? "Continue chatting" : "Login to chat"}
        </button>
        <a href="https://github.com/luohy15/y-agent" target="_blank" rel="noopener noreferrer" className="flex items-center text-sol-base01 hover:text-sol-base1">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>
      </div>
    </div>
  );
}
