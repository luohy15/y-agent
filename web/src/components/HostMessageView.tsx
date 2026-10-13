import ChatTurnList from "./chat/ChatTurnList";

export type HostMessageRole = "user" | "assistant" | "tool_pending" | "tool_result" | "tool_denied" | "system";
export type HostCitationLink = string | { url: string; title?: string; snippet?: string; last_updated?: string };
export interface HostMessage {
  role: HostMessageRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  toolCallId?: string;
  timestamp?: string;
  images?: string[];
  links?: HostCitationLink[];
}

interface ContentPart { type: string; text?: string }

function stripInvisible(value: string): string {
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u2028-\u202F\u2060-\u206F\uFEFF\uFFF9-\uFFFC]/g, "");
}

export function extractContent(content?: string | ContentPart[]): string {
  if (!content) return "";
  if (typeof content === "string") return stripInvisible(content);
  return content.map((part) => {
    if (typeof part === "string") return stripInvisible(part);
    if (part.type === "text") return stripInvisible(part.text || "");
    if (part.type === "image") return "[image]";
    return "";
  }).join("");
}

export function filterTrailingEmptyAssistantMessages(messages: HostMessage[]): HostMessage[] {
  const result: HostMessage[] = [];
  let turnStart = 0;
  const flush = (end: number) => {
    let lastContent = -1;
    for (let i = end - 1; i >= turnStart; i -= 1) {
      if (messages[i].role === "assistant" && messages[i].content.trim()) { lastContent = i; break; }
    }
    for (let i = turnStart; i < end; i += 1) {
      const message = messages[i];
      if (lastContent >= 0 && i > lastContent && message.role === "assistant" && !message.content.trim() && !message.images?.length && !message.links?.length) continue;
      result.push(message);
    }
  };
  for (let i = 0; i < messages.length; i += 1) {
    if (messages[i].role === "user" && i > turnStart) { flush(i); turnStart = i; }
  }
  flush(messages.length);
  return result;
}

export function mergeToolArguments(start?: Record<string, unknown>, result?: Record<string, unknown>): Record<string, unknown> | undefined {
  const merged = { ...(start || {}), ...(result || {}) };
  return Object.keys(merged).length ? merged : undefined;
}

export function mergeToolResult(pending: HostMessage, result: HostMessage): HostMessage {
  return { ...pending, role: result.role, content: result.content, ...(result.toolName ? { toolName: result.toolName } : {}), ...(result.arguments ? { arguments: result.arguments } : {}) };
}

export function parseRawChatMessage(event: any): HostMessage[] {
  const message = event.data || event;
  const role = message.role || "assistant";
  const content = extractContent(message.content);
  const common = { timestamp: message.timestamp, images: message.images, links: message.links };
  if (role === "user") return [{ role, content, ...common }];
  if (role === "assistant" && message.tool_calls) {
    const result: HostMessage[] = content.trim() ? [{ role: "assistant", content, ...common }] : [];
    for (const call of message.tool_calls) {
      let args = {};
      try { args = JSON.parse(call.function?.arguments || "{}"); } catch {}
      result.push({ role: "tool_pending", content: "", toolName: call.function?.name, arguments: args, toolCallId: call.id, timestamp: message.timestamp });
    }
    return result;
  }
  if (role === "tool") return [{ role: content.startsWith("ERROR: User denied") ? "tool_denied" : "tool_result", content, toolCallId: message.tool_call_id, toolName: message.tool, arguments: message.arguments, timestamp: message.timestamp }];
  return [{ role: "assistant", content, ...common }];
}

export function parseChatMessages(rawMessages: unknown[]): HostMessage[] {
  const messages: HostMessage[] = [];
  for (const raw of rawMessages) {
    for (const message of parseRawChatMessage(raw)) {
      const pending = message.toolCallId && (message.role === "tool_result" || message.role === "tool_denied")
        ? messages.findIndex((item) => item.toolCallId === message.toolCallId && item.role === "tool_pending") : -1;
      if (pending >= 0) messages[pending] = mergeToolResult(messages[pending], message);
      else messages.push(message);
    }
  }
  return filterTrailingEmptyAssistantMessages(messages);
}

export default function HostMessageView({ messages, running = false, centered = false, scopeId, scrollContainerRef, allowLocalAttachments }: { messages: HostMessage[]; running?: boolean; centered?: boolean; scopeId: string; scrollContainerRef?: React.RefObject<HTMLDivElement | null>; allowLocalAttachments?: boolean }) {
  return <ChatTurnList messages={messages} scopeId={scopeId} running={running} centered={centered} scrollContainerRef={scrollContainerRef} allowLocalAttachments={allowLocalAttachments} />;
}
