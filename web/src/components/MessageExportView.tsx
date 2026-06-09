import MessageBubble from "./MessageBubble";
import type { Message } from "./MessageList";

interface MessageExportViewProps {
  messages: Message[];
  // Optional small caption under the header (e.g. chat title).
  title?: string;
  width?: number;
}

function formatExportDate(date: Date = new Date()): string {
  return date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
}

// Offscreen, fixed-width rendering of the selected prose messages, styled to match
// the solarized-dark chat. Captured to PNG by `exportMessagesToPng`. Renders full
// height (no max-h clipping) so the screenshot becomes a tall, phone-friendly image.
export default function MessageExportView({ messages, title, width = 390 }: MessageExportViewProps) {
  return (
    <div
      className="bg-sol-base03 text-sol-base0 font-mono"
      style={{ width: `${width}px`, padding: "20px" }}
    >
      <div className="flex items-baseline justify-between border-b border-sol-base02 pb-2 mb-3">
        <span className="text-sol-cyan text-sm font-semibold">y-agent</span>
        <span className="text-sol-base01 text-[0.65rem]">{formatExportDate()}</span>
      </div>
      {title && <div className="text-sol-base01 text-[0.7rem] mb-3 break-words">{title}</div>}
      <div className="flex flex-col gap-3 text-xs">
        {messages.map((m, i) => (
          <MessageBubble
            key={i}
            role={m.role}
            content={m.content}
            images={m.images}
            links={m.links}
            toolName={m.toolName}
            arguments={m.arguments}
            timestamp={m.timestamp}
          />
        ))}
      </div>
      <div className="border-t border-sol-base02 pt-2 mt-3 text-sol-base01 text-[0.6rem] text-center">
        yovy.app
      </div>
    </div>
  );
}
