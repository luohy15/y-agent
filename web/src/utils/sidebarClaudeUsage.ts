import type { SidebarPanel } from "../components/ActivityBar";

export function shouldShowClaudeUsageWidget(sidebarPanel: SidebarPanel): boolean {
  return sidebarPanel === "bots";
}
