import { extractContent, type Message } from "./MessageList";

function hasDisplayableAssistantContent(message: Message): boolean {
  return message.role === "assistant" && message.content.trim().length > 0;
}

function isDroppableTrailingAssistant(message: Message): boolean {
  return message.role === "assistant"
    && message.content.trim().length === 0
    && !message.images?.length
    && !message.links?.length;
}

export function filterTrailingEmptyAssistantMessages(messages: Message[]): Message[] {
  const result: Message[] = [];
  let turnStart = 0;

  const flushTurn = (turnEnd: number) => {
    let lastContentAssistant = -1;
    for (let i = turnEnd - 1; i >= turnStart; i--) {
      if (hasDisplayableAssistantContent(messages[i])) {
        lastContentAssistant = i;
        break;
      }
    }

    for (let i = turnStart; i < turnEnd; i++) {
      if (lastContentAssistant >= 0 && i > lastContentAssistant && isDroppableTrailingAssistant(messages[i])) {
        continue;
      }
      result.push(messages[i]);
    }
  };

  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === "user" && i > turnStart) {
      flushTurn(i);
      turnStart = i;
    }
  }
  flushTurn(messages.length);

  return result;
}

export function parseRawChatMessage(evt: any): Message[] {
  const msg = evt.data || evt;
  const role = msg.role || "assistant";
  const content = extractContent(msg.content);
  const timestamp = msg.timestamp;
  const images = msg.images;
  const links = msg.links;
  const result: Message[] = [];

  if (role === "user") {
    result.push({ role: "user", content, timestamp, images, links });
  } else if (role === "assistant" && msg.tool_calls) {
    if (content.trim()) {
      result.push({ role: "assistant", content, timestamp, images, links });
    }
    for (const tc of msg.tool_calls) {
      const func = tc.function || {};
      let toolArgs: Record<string, unknown> = {};
      try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
      result.push({ role: "tool_pending", content: "", toolName: func.name, arguments: toolArgs, toolCallId: tc.id, timestamp });
    }
  } else if (role === "tool") {
    const tcId = msg.tool_call_id;
    const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
    const parsed: Message = { role: denied ? "tool_denied" : "tool_result", content, timestamp };
    if (tcId) parsed.toolCallId = tcId;
    if (msg.tool) parsed.toolName = msg.tool;
    if (msg.arguments) parsed.arguments = msg.arguments;
    result.push(parsed);
  } else {
    result.push({ role: "assistant", content, timestamp, images, links });
  }
  return result;
}

export function mergeToolResult(pending: Message, result: Message): Message {
  return {
    ...pending,
    role: result.role,
    content: result.content,
    ...(result.toolName ? { toolName: result.toolName } : {}),
    ...(result.arguments ? { arguments: result.arguments } : {}),
  };
}

export function mergeToolArguments(startArgs?: Record<string, unknown>, resultArgs?: Record<string, unknown>): Record<string, unknown> | undefined {
  const merged = { ...(startArgs || {}), ...(resultArgs || {}) };
  return Object.keys(merged).length > 0 ? merged : undefined;
}
