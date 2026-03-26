import { useMemo, useState } from "react";
import { type Message, extractContent } from "./MessageList";
import { stripTracePrefix } from "./badges";

interface ChatTocProps {
  messages: Message[];
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export default function ChatToc({ messages, containerRef }: ChatTocProps) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("chatTocCollapsed") !== "false");
  const [hovered, setHovered] = useState(false);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("chatTocCollapsed", String(next));
  };

  const expanded = !collapsed || hovered;

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

  if (userMessages.length < 2) return null;

  const scrollTo = (index: number) => {
    const el = containerRef.current?.querySelector(`#user-msg-${index}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <>
      {/* Desktop (lg+): sidebar TOC with hover expand + click toggle */}
      <div
        className={`hidden lg:flex flex-col shrink-0 transition-all duration-200 overflow-hidden border-l border-sol-base02 ${expanded ? "w-48" : "w-8"}`}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Toggle button - visible when expanded */}
        {expanded && (
          <button
            onClick={toggle}
            className="px-2 py-1.5 text-xs text-sol-base01 hover:text-sol-base1 cursor-pointer flex items-center gap-1 border-b border-sol-base02 shrink-0"
            title={collapsed ? "Pin TOC open" : "Unpin TOC"}
          >
            {collapsed ? "▶" : "◀"}
          </button>
        )}
        {/* Dots - only when collapsed AND not hovered */}
        {!expanded && (
          <div
            className="flex flex-col items-center gap-1.5 py-2"
            onMouseEnter={() => setHovered(true)}
          >
            {userMessages.map((um) => (
              <div
                key={um.index}
                className="w-2 h-2 rounded-full bg-sol-base01 hover:bg-sol-base0 cursor-pointer shrink-0"
                onClick={() => scrollTo(um.index)}
              />
            ))}
          </div>
        )}
        {/* Expanded list - when pinned open OR on hover */}
        {expanded && (
          <div className="flex flex-col overflow-y-auto py-1">
            {userMessages.map((um, i) => (
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
        )}
      </div>
      {/* Tablet & Mobile (below lg): dropdown TOC button */}
      <div className="lg:hidden absolute top-2 right-2 z-10">
        <button
          onClick={() => setDropdownOpen((v) => !v)}
          className="w-8 h-8 rounded bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center cursor-pointer hover:bg-sol-base01/30"
          title="Message TOC"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
            <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
          </svg>
        </button>
        {dropdownOpen && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setDropdownOpen(false)} />
            <nav className="absolute right-0 top-10 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded-lg shadow-xl p-2">
              {userMessages.map((um, i) => (
                <button
                  key={um.index}
                  onClick={() => { scrollTo(um.index); setDropdownOpen(false); }}
                  className="w-full flex items-center text-left px-2 py-1.5 text-xs font-mono text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer truncate rounded"
                >
                  <span className="text-sol-base01 mr-1.5">{i + 1}.</span>
                  {um.text}
                </button>
              ))}
            </nav>
          </>
        )}
      </div>
    </>
  );
}
