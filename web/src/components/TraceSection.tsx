import { useState } from "react";
import WaterfallChart, { lastSegmentEnd, type TraceChat } from "./WaterfallChart";
import { CHAT_BADGE, chatDisplayTitle, roleLabel, topicBadgeClass } from "./badges";
import { formatDateTime } from "../utils/formatTime";

interface TraceSectionProps {
  chats: TraceChat[];
  onSelectChat?: (chatId: string) => void;
  onOpenContext: (chatId: string) => void;
}

export default function TraceSection({ chats, onSelectChat, onOpenContext }: TraceSectionProps) {
  const [traceOpen, setTraceOpen] = useState(true);

  return (
    <div className="mt-3 border border-sol-base02 rounded">
      <button
        type="button"
        onClick={() => setTraceOpen((v) => !v)}
        aria-expanded={traceOpen}
        className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
      >
        <span className="text-[0.6rem]">{traceOpen ? "▼" : "▶"}</span>
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
        <span className="font-medium text-sol-base0">Trace ({chats.length})</span>
      </button>
      {traceOpen && (
        <div className="px-2 pb-2">
          {chats.length > 0 ? (
            <>
              <WaterfallChart chats={chats} onClickChat={onSelectChat} />
              <div className="mt-2 pt-2 border-t border-sol-base02/60 space-y-0.5" data-testid="trace-context-links">
                {chats.map((chat) => {
                  const title = chatDisplayTitle(chat.title) || chat.chat_id;
                  const end = lastSegmentEnd(chat.segments);
                  const timestamp = end === null ? null : formatDateTime(new Date(end));
                  return (
                    <div
                      key={chat.chat_id}
                      onClick={() => onSelectChat?.(chat.chat_id)}
                      className="px-2 py-1.5 rounded hover:bg-sol-base02 transition-colors cursor-pointer"
                    >
                      <div className="flex flex-wrap items-center gap-1 mb-0.5">
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(chat.chat_id); }}
                          className={`gap-0.5 text-[0.55rem] cursor-pointer ${CHAT_BADGE}`}
                          title="Copy chat ID"
                        >
                          <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                          {chat.chat_id.slice(0, 8)}
                        </button>
                        {chat.role && <span className={`text-[0.55rem] truncate ${topicBadgeClass(chat.role)}`}>{roleLabel(chat.role)}</span>}
                        {chat.skill && chat.skill !== chat.role && <span className="inline-flex items-center px-1 py-0.5 rounded font-mono font-medium shrink-0 text-[0.55rem] bg-sol-base01/20 text-sol-base01">{chat.skill}</span>}
                        <button
                          type="button"
                          className="ml-auto shrink-0 text-[0.6rem] font-mono px-1.5 py-0.5 rounded cursor-pointer bg-sol-base02 text-sol-base01 hover:text-sol-base0"
                          data-testid={`trace-context-${chat.chat_id}`}
                          data-chat-id={chat.chat_id}
                          title="Open participant context"
                          onClick={(e) => { e.stopPropagation(); onOpenContext(chat.chat_id); }}
                        >
                          Context
                        </button>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="flex-1 min-w-0 truncate text-[0.65rem] text-sol-base0" title={chat.title}>{title}</span>
                        {timestamp && <span className="text-[0.65rem] sm:text-[0.5rem] text-sol-base01 shrink-0 text-right">{timestamp.date}<br/>{timestamp.time}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <p className="text-sol-base01 italic text-xs mt-1">No chats found for this todo</p>
          )}
        </div>
      )}
    </div>
  );
}
