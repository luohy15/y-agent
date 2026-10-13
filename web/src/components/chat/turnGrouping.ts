// Pure turn grouping shared by public/fallback and authenticated chat lists
// (todo 3892 round 2). Ported verbatim from the chat module's message-list.
import type { ChatMessageRole } from "./ChatMessagePresentation";

export interface GroupableMessage {
  role: ChatMessageRole;
  toolName?: string;
}

export type TurnItem<M extends GroupableMessage> =
  | { type: "message"; message: M; index: number }
  | { type: "process_summary"; toolCounts: Record<string, number>; assistantCount: number; index: number; roundMessages: M[]; roundStartIndex: number };

export type ExpandedProcessItem<M extends GroupableMessage> =
  | { type: "single"; message: M; idx: number; dimmed?: boolean }
  | { type: "file_group"; kind: string; messages: M[]; startIdx: number };

export function isToolMessage(m: GroupableMessage): boolean {
  return m.role === "tool_pending" || m.role === "tool_result" || m.role === "tool_denied";
}

export function fileToolKind(m: GroupableMessage): string | null {
  if (m.role !== "tool_result" && m.role !== "tool_denied") return null;
  const name = m.toolName?.toLowerCase();
  if (name === "file_read" || name === "read") return "Read";
  if (name === "file_write" || name === "write") return "Write";
  if (name === "file_edit" || name === "edit") return "Edit";
  return null;
}

export function getToolLabel(toolName: string): string {
  const n = toolName.toLowerCase();
  if (n === "bash") return "Bash";
  if (n === "read" || n === "file_read") return "Read";
  if (n === "write" || n === "file_write") return "Write";
  if (n === "edit" || n === "file_edit") return "Edit";
  if (n === "grep") return "Grep";
  if (n === "glob") return "Glob";
  if (n === "agent") return "Agent";
  if (n === "websearch" || n === "webfetch") return toolName;
  if (n === "todowrite") return "Todo";
  return toolName;
}

export interface ToolIconMeta { icon: string; color: string; bg: string }

export const toolIconMap: Record<string, ToolIconMeta> = {
  Bash: { icon: ">_", color: "text-sol-blue", bg: "bg-sol-blue/15" },
  Read: { icon: "↓", color: "text-sol-cyan", bg: "bg-sol-cyan/15" },
  Write: { icon: "↑", color: "text-sol-green", bg: "bg-sol-green/15" },
  Edit: { icon: "Δ", color: "text-sol-yellow", bg: "bg-sol-yellow/15" },
  Grep: { icon: "/", color: "text-sol-violet", bg: "bg-sol-violet/15" },
  Glob: { icon: "*", color: "text-sol-violet", bg: "bg-sol-violet/15" },
  Agent: { icon: "◈", color: "text-sol-magenta", bg: "bg-sol-magenta/15" },
  Todo: { icon: "✓", color: "text-sol-green", bg: "bg-sol-green/15" },
};
export const defaultToolIcon: ToolIconMeta = { icon: "◆", color: "text-sol-base01", bg: "bg-sol-base01/15" };

export function collectProcessStats<M extends GroupableMessage>(messages: M[], from: number, to: number): { toolCounts: Record<string, number>; assistantCount: number } {
  const toolCounts: Record<string, number> = {};
  let assistantCount = 0;
  for (let i = from; i < to; i++) {
    const m = messages[i];
    if (isToolMessage(m) && m.toolName) {
      const label = getToolLabel(m.toolName);
      toolCounts[label] = (toolCounts[label] || 0) + 1;
    } else if (m.role === "assistant") {
      assistantCount++;
    }
  }
  return { toolCounts, assistantCount };
}

export function findLastAssistant<M extends GroupableMessage>(messages: M[], from: number, to: number): number {
  for (let i = to - 1; i >= from; i--) {
    if (messages[i].role === "assistant") return i;
  }
  return -1;
}

// Level 0: user + last assistant per round (between user messages) + process summary
export function groupTurns<M extends GroupableMessage>(messages: M[]): TurnItem<M>[] {
  const items: TurnItem<M>[] = [];
  const roundStarts: number[] = [];
  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === "user") roundStarts.push(i);
  }
  if (roundStarts.length === 0 || roundStarts[0] > 0) {
    const end = roundStarts.length > 0 ? roundStarts[0] : messages.length;
    const lastAssistantIdx = findLastAssistant(messages, 0, end);
    if (lastAssistantIdx >= 0) {
      items.push({ type: "message", message: messages[lastAssistantIdx], index: lastAssistantIdx });
    }
  }
  for (let r = 0; r < roundStarts.length; r++) {
    const start = roundStarts[r];
    const end = r + 1 < roundStarts.length ? roundStarts[r + 1] : messages.length;
    items.push({ type: "message", message: messages[start], index: start });
    const stats = collectProcessStats(messages, start + 1, end);
    const totalTools = Object.values(stats.toolCounts).reduce((a, b) => a + b, 0);
    if (totalTools > 0) {
      items.push({ type: "process_summary", toolCounts: stats.toolCounts, assistantCount: stats.assistantCount, index: start + 1, roundMessages: messages.slice(start + 1, end), roundStartIndex: start + 1 });
    }
    const lastAssistantIdx = findLastAssistant(messages, start + 1, end);
    if (lastAssistantIdx >= 0) {
      items.push({ type: "message", message: messages[lastAssistantIdx], index: lastAssistantIdx });
    }
  }
  return items;
}

// Expanded process view: consecutive tool messages, with runs of >=2 same-kind
// file tools folded into one group, interleaved with dimmed assistant narration
// (the round's last assistant is shown outside the summary).
export function expandProcess<M extends GroupableMessage>(roundMessages: M[], roundStartIndex: number): ExpandedProcessItem<M>[] {
  const expandedItems: ExpandedProcessItem<M>[] = [];
  const lastAssistantIdx = findLastAssistant(roundMessages, 0, roundMessages.length);
  let i = 0;
  while (i < roundMessages.length) {
    const m = roundMessages[i];
    if (isToolMessage(m)) {
      const batch: M[] = [];
      const batchStart = i;
      while (i < roundMessages.length && isToolMessage(roundMessages[i])) {
        batch.push(roundMessages[i]);
        i++;
      }
      let j = 0;
      while (j < batch.length) {
        const kind = fileToolKind(batch[j]);
        if (kind) {
          const fileBatch: M[] = [];
          const fileBatchStart = j;
          while (j < batch.length && fileToolKind(batch[j]) === kind) {
            fileBatch.push(batch[j]);
            j++;
          }
          if (fileBatch.length >= 2) {
            expandedItems.push({ type: "file_group", kind, messages: fileBatch, startIdx: roundStartIndex + batchStart + fileBatchStart });
          } else {
            expandedItems.push({ type: "single", message: fileBatch[0], idx: roundStartIndex + batchStart + fileBatchStart });
          }
        } else {
          expandedItems.push({ type: "single", message: batch[j], idx: roundStartIndex + batchStart + j });
          j++;
        }
      }
    } else if (m.role === "assistant") {
      if (i !== lastAssistantIdx) {
        expandedItems.push({ type: "single", message: m, idx: roundStartIndex + i, dimmed: true });
      }
      i++;
    } else {
      i++;
    }
  }
  return expandedItems;
}
