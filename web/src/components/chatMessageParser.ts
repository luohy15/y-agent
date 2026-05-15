import { extractContent, type Message } from "./MessageList";

export function parseRawChatMessage(evt: any): Message[] {
  const msg = evt.data || evt;
  const role = msg.role || "assistant";
  const content = extractContent(msg.content);
  const timestamp = msg.timestamp;
  const images = msg.images;
  const result: Message[] = [];

  if (role === "user") {
    result.push({ role: "user", content, timestamp, images });
  } else if (role === "assistant" && msg.tool_calls) {
    if (content.trim()) {
      result.push({ role: "assistant", content, timestamp, images });
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
    result.push({ role: "assistant", content, timestamp, images });
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
