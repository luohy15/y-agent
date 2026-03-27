import { useState, useEffect, useRef, useMemo } from "react";
import { useParams } from "react-router";
import { API } from "../api";
import { extractContent } from "./MessageList";
import MessageList, { type Message } from "./MessageList";
import WaterfallChart, { type TraceChat } from "./WaterfallChart";
import { skillBadgeClass, getSkillColor, stripTracePrefix, statusBadgeClass, priorityColorClass, actionBadgeClass } from "./badges";

interface TodoHistoryEntry {
  timestamp: string;
  action: string;
  note?: string;
}

interface TodoInfo {
  todo_id: string;
  name: string;
  status: string;
  desc?: string;
  tags?: string[];
  priority?: string;
  due_date?: string;
  progress?: string;
  completed_at?: string;
  created_at?: string;
  updated_at?: string;
  history?: TodoHistoryEntry[];
}

interface TraceShareResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
  todo: TodoInfo | null;
}

function parseMessages(rawMessages: any[]): Message[] {
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

function ShareToc({ messages, containerRef }: { messages: Message[]; containerRef: React.RefObject<HTMLDivElement | null> }) {
  const userMessages = useMemo(() => {
    const items: { index: number; text: string }[] = [];
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].role === "user") {
        const raw = stripTracePrefix(extractContent(messages[i].content));
        const firstLine = raw.split("\n")[0].trim();
        const text = firstLine.length > 30 ? firstLine.slice(0, 30) + "..." : firstLine;
        items.push({ index: i, text });
      }
    }
    return items;
  }, [messages]);

  const scrollTo = (index: number) => {
    const el = containerRef.current?.querySelector(`#user-msg-${index}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="hidden lg:flex flex-col shrink-0 w-48 border border-sol-base02 rounded overflow-y-auto py-1 my-[25vh] mx-2 self-start">
      {userMessages.length >= 2 && userMessages.map((um, i) => (
        <button
          key={um.index}
          onClick={() => scrollTo(um.index)}
          className="flex items-center text-left px-2 h-6 shrink-0 text-[0.7rem] font-mono text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer truncate"
        >
          <span className="text-sol-base01 mr-1">{i + 1}.</span>
          {um.text}
        </button>
      ))}
    </div>
  );
}

export default function ShareTraceView() {
  const { shareId } = useParams<{ shareId: string }>();

  const [data, setData] = useState<TraceShareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [todoDetailOpen, setTodoDetailOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [showProgress, setShowProgress] = useState(() => localStorage.getItem("showProgress") === "true");
  const [shareLabel, setShareLabel] = useState("share");
  const scrollRef = useRef<HTMLDivElement>(null);


  useEffect(() => {
    if (!shareId) return;
    setLoading(true);
    setError(null);
    fetch(`${API}/api/trace/share?share_id=${encodeURIComponent(shareId)}`)
      .then((r) => {
        if (!r.ok) throw new Error("Shared trace not found");
        return r.json();
      })
      .then((d: TraceShareResponse) => {
        setData(d);
        // Default to earliest chat (first in timeline)
        if (d.chats.length > 0) {
          setSelectedChatId(d.chats[0].chat_id);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [shareId]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-sol-base03">
        <span className="text-sol-base01 text-sm">Loading...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="h-full flex items-center justify-center bg-sol-base03">
        <span className="text-sol-red text-sm">{error || "Failed to load"}</span>
      </div>
    );
  }

  const todoInfo = data.todo;
  const selectedChat = data.chats.find((c) => c.chat_id === selectedChatId);
  const selectedMessages = selectedChat ? parseMessages((selectedChat.messages as any[]) || []) : [];

  return (
    <div className="h-full flex flex-col bg-sol-base03">
      {/* Header */}
      <div className="px-6 py-2 border-b border-sol-base02 shrink-0">
        <div className="max-w-4xl mx-auto w-full">
          <span className="text-xs text-sol-base01">Shared Todo Trace</span>
        </div>
      </div>

      {/* 3-column layout: chatlist | content | toc */}
      <div className="flex-1 flex min-h-0 justify-center">
        {/* Left: chat selector list */}
        {data.chats.length > 1 && (
          <div className="hidden lg:flex flex-col shrink-0 w-48 border border-sol-base02 rounded overflow-y-auto py-1 my-[25vh] mx-2 self-start">
            {data.chats.map((c) => {
              const skillColor = getSkillColor(c.skill);
              const isSelected = c.chat_id === selectedChatId;
              const displayTitle = (c.title || "").replace(/^\[.*?\]\s*/, "") || c.chat_id.slice(0, 8);
              return (
                <button
                  key={c.chat_id}
                  onClick={() => setSelectedChatId(c.chat_id)}
                  className={`text-left text-[0.65rem] px-2 py-1 cursor-pointer truncate ${
                    isSelected
                      ? `${skillColor.bg} ${skillColor.text}`
                      : "text-sol-base01 hover:text-sol-base0 hover:bg-sol-base02"
                  }`}
                >
                  <span className="font-medium">{c.skill || "chat"}</span>
                  <span className="ml-1 opacity-70">{displayTitle}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* Center: todo header + waterfall + messages */}
        <div ref={scrollRef} className="flex-1 max-w-3xl overflow-y-auto px-4 py-3">
          {/* Todo header */}
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sol-base1 text-sm font-medium">
                {data.todo_name || "Trace"}
              </span>
              {data.todo_status && (
                <span className={`text-[0.6rem] px-1 rounded ${statusBadgeClass(data.todo_status)}`}>
                  {data.todo_status}
                </span>
              )}
              {data.chats.length > 0 && (
                <div className="flex flex-wrap gap-0.5">
                  {[...new Set(data.chats.map((c) => c.skill).filter(Boolean))].map((s) => (
                    <span key={s} className={`text-[0.6rem] ${skillBadgeClass(s)}`}>
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Todo detail section */}
            {todoInfo && (
              <div className="mb-3 border border-sol-base02 rounded">
                <button
                  onClick={() => setTodoDetailOpen((v) => !v)}
                  className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
                >
                  <span className="text-[0.6rem]">{todoDetailOpen ? "▼" : "▶"}</span>
                  <span className="font-medium text-sol-base0">Todo Detail</span>
                </button>
                {todoDetailOpen && (<>
                  <div className="px-2 pb-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    {todoInfo.desc && (
                      <>
                        <span className="text-sol-base01">Desc</span>
                        <span className="text-sol-base0">{todoInfo.desc}</span>
                      </>
                    )}
                    {todoInfo.priority && (
                      <>
                        <span className="text-sol-base01">Priority</span>
                        <span className={priorityColorClass(todoInfo.priority)}>{todoInfo.priority}</span>
                      </>
                    )}
                    {todoInfo.due_date && (
                      <>
                        <span className="text-sol-base01">Due</span>
                        <span className="text-sol-base0">{todoInfo.due_date}</span>
                      </>
                    )}
                    {todoInfo.tags && todoInfo.tags.length > 0 && (
                      <>
                        <span className="text-sol-base01">Tags</span>
                        <div className="flex flex-wrap gap-1">
                          {todoInfo.tags.map((tag) => (
                            <span key={tag} className="bg-sol-base02 text-sol-base0 px-1.5 py-0.5 rounded text-[0.6rem]">{tag}</span>
                          ))}
                        </div>
                      </>
                    )}
                    {todoInfo.progress && (
                      <>
                        <span className="text-sol-base01">Progress</span>
                        <span className="text-sol-base0 whitespace-pre-wrap">{todoInfo.progress}</span>
                      </>
                    )}
                    {todoInfo.created_at && (
                      <>
                        <span className="text-sol-base01">Created</span>
                        <span className="text-sol-base0 font-mono text-[0.65rem]">{new Date(todoInfo.created_at).toLocaleString()}</span>
                      </>
                    )}
                    {todoInfo.updated_at && (
                      <>
                        <span className="text-sol-base01">Updated</span>
                        <span className="text-sol-base0 font-mono text-[0.65rem]">{new Date(todoInfo.updated_at).toLocaleString()}</span>
                      </>
                    )}
                    {todoInfo.completed_at && (
                      <>
                        <span className="text-sol-base01">Completed</span>
                        <span className="text-sol-green font-mono text-[0.65rem]">{new Date(todoInfo.completed_at).toLocaleString()}</span>
                      </>
                    )}
                  </div>
                  {/* History section */}
                  {todoInfo.history && todoInfo.history.length > 0 && (
                    <div className="px-2 pb-2">
                      <button
                        onClick={() => setHistoryOpen((v) => !v)}
                        className="flex items-center gap-1.5 text-[0.65rem] text-sol-base01 hover:text-sol-base0 cursor-pointer mb-1"
                      >
                        <span className="text-[0.55rem]">{historyOpen ? "▼" : "▶"}</span>
                        <span>History ({todoInfo.history.length})</span>
                      </button>
                      {historyOpen && (
                        <div className="ml-1 border-l border-sol-base02 pl-2 space-y-1.5">
                          {todoInfo.history.map((h, i) => {
                            return (
                              <div key={i} className="flex items-start gap-1.5 relative">
                                <div className="absolute -left-[calc(0.5rem+1px)] top-1 w-1.5 h-1.5 rounded-full bg-sol-base01 border border-sol-base02" />
                                <span className="text-[0.6rem] text-sol-base01 font-mono shrink-0">
                                  {new Date(h.timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                                </span>
                                <span className={`text-[0.55rem] px-1 rounded shrink-0 ${actionBadgeClass(h.action)}`}>{h.action}</span>
                                {h.note && <span className="text-[0.6rem] text-sol-base0 break-all">{h.note}</span>}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </>)}
              </div>
            )}

            {/* Waterfall chart */}
            {data.chats.length > 0 ? (
              <WaterfallChart chats={data.chats} onClickSkill={(chatId) => setSelectedChatId(chatId)} />
            ) : (
              <p className="text-sol-base01 italic text-xs mt-2">No chats found</p>
            )}
          </div>

          {/* Messages */}
          {selectedMessages.length > 0 && (
            <MessageList messages={selectedMessages} showProgress={showProgress} inline />
          )}
        </div>

        {/* Right: TOC */}
        <ShareToc messages={selectedMessages} containerRef={scrollRef} />
      </div>

      {/* Bottom bar */}
      <div className="mx-4 border-t border-sol-base02 shrink-0 px-2 py-1 flex items-center justify-center gap-2 text-xs select-none">
        <button
          onClick={() => { const next = !showProgress; setShowProgress(next); localStorage.setItem("showProgress", String(next)); }}
          className={`font-mono cursor-pointer px-2 py-0.5 rounded text-[0.7rem] font-semibold ${showProgress ? "bg-sol-cyan text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
        >
          {showProgress ? "progress ●" : "progress ○"}
        </button>
        <button
          onClick={() => { navigator.clipboard.writeText(window.location.href); setShareLabel("copied!"); setTimeout(() => setShareLabel("share"), 1500); }}
          className={`font-mono cursor-pointer px-2 py-0.5 rounded text-[0.7rem] font-semibold ${shareLabel === "copied!" ? "bg-sol-green text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
        >
          {shareLabel}
        </button>
      </div>
      <div className="px-6 py-3 shrink-0 flex items-center justify-center gap-3">
        <a href="https://github.com/luohy15/y-agent" target="_blank" rel="noopener noreferrer" className="flex items-center text-sol-base01 hover:text-sol-base1">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>
      </div>
    </div>
  );
}
