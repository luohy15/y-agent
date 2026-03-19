import { useMemo } from "react";
import { type Message, extractContent } from "./MessageList";

interface ChatTocProps {
  messages: Message[];
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export default function ChatToc({ messages, containerRef }: ChatTocProps) {
  const userMessages = useMemo(() => {
    const items: { index: number; text: string }[] = [];
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].role === "user") {
        const raw = extractContent(messages[i].content);
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
    <div className="hidden md:flex flex-col shrink-0 w-8 hover:w-48 transition-all duration-200 overflow-hidden group border-l border-sol-base02">
      {/* Dot indicators (visible when collapsed) */}
      <div className="flex flex-col items-center gap-1.5 py-2 group-hover:hidden">
        {userMessages.map((um) => (
          <div
            key={um.index}
            className="w-2 h-2 rounded-full bg-sol-base01 hover:bg-sol-base0 cursor-pointer shrink-0"
            onClick={() => scrollTo(um.index)}
          />
        ))}
      </div>
      {/* Expanded list (visible on hover) */}
      <div className="hidden group-hover:flex flex-col overflow-y-auto py-1">
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
    </div>
  );
}
