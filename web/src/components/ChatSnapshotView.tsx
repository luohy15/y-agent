import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MessageExportView from "./MessageExportView";
import MessageList, { type CitationLink, type Message } from "./MessageList";
import ChatToc from "./ChatToc";
import SourcesSidebar from "./SourcesSidebar";
import { filterTrailingEmptyAssistantMessages, parseChatMessages } from "./chatMessageParser";
import { toggleSelection, selectMessagesByIndices } from "../utils/messageExport";
import { exportElementToPng, deliverPng } from "../utils/exportImage";

interface ChatSnapshotViewProps {
  chatId: string;
  messages: unknown[];
  onRefresh?: () => void;
}

export default function ChatSnapshotView({ chatId, messages: rawMessages, onRefresh }: ChatSnapshotViewProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [showProgress, setShowProgress] = useState(() => localStorage.getItem("showProgress") === "true");
  const [sourcesPanel, setSourcesPanel] = useState<{ links: CitationLink[]; messageIndex?: number } | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [exporting, setExporting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const displayMessages = useMemo(() => filterTrailingEmptyAssistantMessages(messages), [messages]);

  useEffect(() => {
    setMessages(parseChatMessages(rawMessages));
    setSourcesPanel(null);
  }, [rawMessages]);

  useEffect(() => { setSelectMode(false); setSelectedIndices(new Set()); }, [chatId, rawMessages]);

  const startSelect = useCallback(() => { setSelectMode(true); setSelectedIndices(new Set()); }, []);
  const cancelSelect = useCallback(() => { setSelectMode(false); setSelectedIndices(new Set()); }, []);
  const toggleSelect = useCallback((index: number) => {
    setSelectedIndices((prev) => toggleSelection(prev, index));
  }, []);
  const exportSelected = useCallback(async () => {
    const selectedMessages = selectMessagesByIndices(displayMessages, selectedIndices);
    if (!selectedMessages.length || exporting) return;
    setExporting(true);
    try {
      const { blob, dataUrl } = await exportElementToPng(<MessageExportView messages={selectedMessages} />);
      await deliverPng(blob, dataUrl);
      cancelSelect();
    } finally {
      setExporting(false);
    }
  }, [displayMessages, selectedIndices, exporting, cancelSelect]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const onScroll = () => {
      const distFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
      setShowScrollBottom(distFromBottom > 200);
    };
    element.addEventListener("scroll", onScroll, { passive: true });
    return () => element.removeEventListener("scroll", onScroll);
  }, [messages]);

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

  const processDetailButtons = (
    <button
      onClick={() => { const next = !showProgress; setShowProgress(next); localStorage.setItem("showProgress", String(next)); }}
      className={`font-mono cursor-pointer px-2 py-0.5 rounded text-xs sm:text-[0.7rem] font-semibold ${showProgress ? "bg-sol-cyan text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
    >
      {showProgress ? "progress ●" : "progress ○"}
    </button>
  );

  const selectImageButton = !selectMode && displayMessages.length > 0 ? (
    <button
      onClick={startSelect}
      className="font-mono cursor-pointer px-2 py-0.5 rounded text-xs sm:text-[0.7rem] font-semibold bg-sol-base02 text-sol-base01 hover:bg-sol-base01/30"
      title="Export selected messages as image"
    >
      image
    </button>
  ) : null;

  return (
    <div ref={containerRef} className="flex-1 flex flex-col min-w-0 min-h-0 overflow-x-hidden">
      <div className="flex-1 flex min-h-0 relative">
        <MessageList messages={displayMessages} running={false} showProgress={showProgress} onShowSources={(links, messageIndex) => setSourcesPanel({ links, messageIndex })} scrollContainerRef={scrollRef} selectMode={selectMode} selectedIndices={selectedIndices} onToggleSelect={toggleSelect} />
        <ChatToc messages={displayMessages} containerRef={scrollRef} />
        {selectMode && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-3 rounded-full bg-sol-base02 border border-sol-base01/40 px-4 py-2 shadow-lg text-sm sm:text-xs">
            <span className="font-mono text-sol-base1 font-semibold">{selectedIndices.size} selected</span>
            <button
              onClick={exportSelected}
              disabled={selectedIndices.size === 0 || exporting}
              className="px-2.5 py-0.5 bg-sol-cyan text-sol-base03 rounded font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default"
            >
              {exporting ? "Exporting…" : "Export image"}
            </button>
            <button onClick={cancelSelect} className="px-2.5 py-0.5 bg-sol-base03 text-sol-base1 rounded font-semibold cursor-pointer hover:bg-sol-base01/30">Cancel</button>
          </div>
        )}
        {sourcesPanel && <SourcesSidebar links={sourcesPanel.links} onClose={() => setSourcesPanel(null)} />}
        {showScrollBottom && (
          <button
            onClick={() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "auto" })}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 w-8 h-8 rounded-full bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center shadow-lg cursor-pointer hover:bg-sol-base01/30"
            title="Scroll to bottom"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        )}
      </div>
      <div className="mx-4 border-t border-sol-base02 shrink-0 px-2 py-2 flex items-center gap-3 text-sm sm:text-xs select-none">
        {processDetailButtons}
        {selectImageButton}
        {onRefresh && (
          <button onClick={onRefresh} className="inline-flex items-center gap-1 px-2 py-0.5 bg-sol-base02 text-sol-base1 rounded text-xs font-semibold cursor-pointer hover:bg-sol-base01/30" title="Refresh trace">
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Refresh
          </button>
        )}
      </div>
    </div>
  );
}
