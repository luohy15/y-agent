import { describe, expect, it } from "vitest";
import type { SidebarPanel } from "../components/ActivityBar";
import { shouldShowClaudeUsageWidget } from "./sidebarClaudeUsage";

describe("shouldShowClaudeUsageWidget", () => {
  it("shows the Claude usage footer only on the bots sidebar panel", () => {
    const panels: SidebarPanel[] = [
      "todo",
      "chats",
      "notes",
      "links",
      "rss",
      "entity",
      "bots",
      "files",
      "reminder",
      "routine",
      "calendar",
      "finance",
      "email",
      "dev",
    ];

    expect(panels.filter(shouldShowClaudeUsageWidget)).toEqual(["bots"]);
  });
});
