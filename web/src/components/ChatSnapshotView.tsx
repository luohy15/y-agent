import { useEffect, useRef, useState } from "react";
import HostMessageView, { parseChatMessages, type HostMessage } from "./HostMessageView";

interface ChatSnapshotViewProps {
  chatId: string;
  messages: unknown[];
  onRefresh?: () => void;
}

export default function ChatSnapshotView({ chatId, messages: rawMessages, onRefresh }: ChatSnapshotViewProps) {
  const [messages, setMessages] = useState<HostMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages(parseChatMessages(rawMessages));
  }, [chatId, rawMessages]);

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-x-hidden">
      <HostMessageView messages={messages} centered scrollContainerRef={scrollRef} />
      {onRefresh && (
        <div className="mx-4 border-t border-sol-base02 shrink-0 px-2 py-2">
          <button onClick={onRefresh} className="inline-flex items-center gap-1 px-2 py-0.5 bg-sol-base02 text-sol-base1 rounded text-xs font-semibold cursor-pointer hover:bg-sol-base01/30" title="Refresh trace">
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Refresh
          </button>
        </div>
      )}
    </div>
  );
}
