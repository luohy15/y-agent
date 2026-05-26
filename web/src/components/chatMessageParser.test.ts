import { describe, expect, it } from "vitest";
import { filterTrailingEmptyAssistantMessages, mergeToolArguments, mergeToolResult, parseRawChatMessage } from "./chatMessageParser";

describe("chat message parser", () => {
  it("drops empty assistant messages after the last content assistant in each turn", () => {
    expect(filterTrailingEmptyAssistantMessages([
      { role: "user", content: "one" },
      { role: "assistant", content: "thinking before reply" },
      { role: "assistant", content: "final reply" },
      { role: "assistant", content: "" },
      { role: "assistant", content: "   " },
      { role: "user", content: "two" },
      { role: "assistant", content: "second reply" },
      { role: "assistant", content: "" },
    ])).toEqual([
      { role: "user", content: "one" },
      { role: "assistant", content: "thinking before reply" },
      { role: "assistant", content: "final reply" },
      { role: "user", content: "two" },
      { role: "assistant", content: "second reply" },
    ]);
  });

  it("preserves mid-turn empty assistants and all tool messages", () => {
    expect(filterTrailingEmptyAssistantMessages([
      { role: "user", content: "run tools" },
      { role: "assistant", content: "" },
      { role: "tool_pending", content: "", toolName: "Read", toolCallId: "call_1" },
      { role: "tool_result", content: "done", toolName: "Read", toolCallId: "call_1" },
      { role: "assistant", content: "final reply" },
      { role: "tool_result", content: "late tool", toolName: "Bash" },
      { role: "assistant", content: "" },
    ])).toEqual([
      { role: "user", content: "run tools" },
      { role: "assistant", content: "" },
      { role: "tool_pending", content: "", toolName: "Read", toolCallId: "call_1" },
      { role: "tool_result", content: "done", toolName: "Read", toolCallId: "call_1" },
      { role: "assistant", content: "final reply" },
      { role: "tool_result", content: "late tool", toolName: "Bash" },
    ]);
  });

  it("keeps empty assistant-only turns without content-bearing replies", () => {
    expect(filterTrailingEmptyAssistantMessages([
      { role: "user", content: "one" },
      { role: "assistant", content: "" },
      { role: "assistant", content: " " },
      { role: "user", content: "two" },
      { role: "assistant", content: "reply" },
    ])).toEqual([
      { role: "user", content: "one" },
      { role: "assistant", content: "" },
      { role: "assistant", content: " " },
      { role: "user", content: "two" },
      { role: "assistant", content: "reply" },
    ]);
  });

  it("forwards user images", () => {
    expect(parseRawChatMessage({
      role: "user",
      content: "look at this",
      images: ["/Users/roy/luohy15/assets/images/user.jpg"],
    })).toEqual([{
      role: "user",
      content: "look at this",
      timestamp: undefined,
      images: ["/Users/roy/luohy15/assets/images/user.jpg"],
    }]);
  });

  it("forwards assistant images without tool calls", () => {
    expect(parseRawChatMessage({
      role: "assistant",
      content: "rendered image",
      images: ["/Users/roy/luohy15/assets/images/assistant.jpg"],
    })).toEqual([{
      role: "assistant",
      content: "rendered image",
      timestamp: undefined,
      images: ["/Users/roy/luohy15/assets/images/assistant.jpg"],
    }]);
  });

  it("forwards assistant citation links", () => {
    const links = [{
      url: "https://www.cnbc.com/foo",
      title: "CNBC story",
      snippet: "A useful excerpt",
      last_updated: "2026-05-26",
    }];

    expect(parseRawChatMessage({
      role: "assistant",
      content: "Answer [1]",
      links,
    })).toEqual([{
      role: "assistant",
      content: "Answer [1]",
      timestamp: undefined,
      images: undefined,
      links,
    }]);
  });

  it("forwards assistant images only on text bubble when tool calls exist", () => {
    expect(parseRawChatMessage({
      role: "assistant",
      content: "using a tool",
      images: ["/Users/roy/luohy15/assets/images/tool-text.jpg"],
      tool_calls: [{
        id: "item_12",
        type: "function",
        function: {
          name: "Read",
          arguments: JSON.stringify({ file_path: "/tmp/App.tsx" }),
        },
      }],
    })).toEqual([
      {
        role: "assistant",
        content: "using a tool",
        timestamp: undefined,
        images: ["/Users/roy/luohy15/assets/images/tool-text.jpg"],
      },
      {
        role: "tool_pending",
        content: "",
        toolName: "Read",
        arguments: { file_path: "/tmp/App.tsx" },
        toolCallId: "item_12",
        timestamp: undefined,
      },
    ]);
  });

  it("merges Codex provider-less tool result while preserving tool details", () => {
    const pending = parseRawChatMessage({
      role: "assistant",
      content: "",
      tool_calls: [{
        id: "item_11",
        type: "function",
        function: {
          name: "Edit",
          arguments: JSON.stringify({ file_path: "" }),
        },
      }],
    });
    const result = parseRawChatMessage({
      role: "tool",
      content: "update /tmp/App.tsx",
      tool: "Edit",
      tool_call_id: "item_11",
      arguments: {
        file_path: "/tmp/App.tsx",
        path: "/tmp/App.tsx",
        changes: [{ path: "/tmp/App.tsx", kind: "update" }],
      },
    });

    expect(pending).toHaveLength(1);
    expect(result).toHaveLength(1);

    const merged = mergeToolResult(pending[0], result[0]);

    expect(merged.role).toBe("tool_result");
    expect(merged.toolName).toBe("Edit");
    expect(merged.content).toBe("update /tmp/App.tsx");
    expect(merged.arguments).toEqual({
      file_path: "/tmp/App.tsx",
      path: "/tmp/App.tsx",
      changes: [{ path: "/tmp/App.tsx", kind: "update" }],
    });
    expect(merged.toolCallId).toBe("item_11");
  });

  it("lets completed tool arguments override assistant-start placeholders", () => {
    expect(mergeToolArguments(
      { file_path: "" },
      {
        file_path: "/tmp/App.tsx",
        path: "/tmp/App.tsx",
        changes: [{ path: "/tmp/App.tsx", kind: "update" }],
      },
    )).toEqual({
      file_path: "/tmp/App.tsx",
      path: "/tmp/App.tsx",
      changes: [{ path: "/tmp/App.tsx", kind: "update" }],
    });
  });
});
