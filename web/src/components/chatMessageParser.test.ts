import { describe, expect, it } from "vitest";
import { mergeToolArguments, mergeToolResult, parseRawChatMessage } from "./chatMessageParser";

describe("chat message parser", () => {
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
