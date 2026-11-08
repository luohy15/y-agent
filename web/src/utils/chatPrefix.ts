// Parsing for the dispatch / routine prefix the harness puts at the start of a
// user message (`storage.service.chat.dispatch_content`,
// `storage.service.routine.fire_routine`). Kept pure and React-free so both the
// message chrome and the SDK strip helper share one set of rules.

export interface ChatPrefixInfo {
  traceId?: string;
  fromSkill?: string;
  toSkill?: string;
  fromChatId?: string;
  toChatId?: string;
  routine?: string;
  cleanContent: string;
}

const PREFIX_KEYS = new Set(["trace", "from", "to", "from_chat", "to_chat", "routine"]);

// A prefix is a single leading bracket line of `key:value` tokens, e.g.
// `[from:manager to:leader from_chat:befaec to_chat:b34335]`. Parse it only
// when every token is a known key with a non-empty value, no key repeats, and
// at least one dispatch marker (`trace`, `from`, `routine`) is present, so
// ordinary bracketed prose stays raw. Malformed or partial prefixes (no closing
// bracket, unknown key, multiline) return null and render unchanged.
export function parseChatPrefix(content: string): ChatPrefixInfo | null {
  const match = content.match(/^\[([^\]\n]+)\]\n?/);
  if (!match) return null;
  const fields = new Map<string, string>();
  for (const token of match[1].trim().split(/\s+/)) {
    const sep = token.indexOf(":");
    if (sep <= 0) return null;
    const key = token.slice(0, sep);
    const value = token.slice(sep + 1);
    if (!PREFIX_KEYS.has(key) || !value || fields.has(key)) return null;
    fields.set(key, value);
  }
  if (!fields.has("trace") && !fields.has("from") && !fields.has("routine")) return null;
  return {
    traceId: fields.get("trace"),
    fromSkill: fields.get("from"),
    toSkill: fields.get("to"),
    fromChatId: fields.get("from_chat"),
    toChatId: fields.get("to_chat"),
    routine: fields.get("routine"),
    cleanContent: content.slice(match[0].length),
  };
}
