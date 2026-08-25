// Host-owned shell chrome labels for the public demo (todo 3158 H6,
// pages/plan-3158-full-shell-demo.md decision 8). Domain records stay
// module-owned; these are chrome only and must never come from production.

export const DEMO_CHROME = {
  // Matches the approved design header (pages/design-3158.html).
  traceId: "4f1c9a",
  vmName: "default",
  botName: "default",
  workDir: "/home/demo/notes",
} as const;

/** Live left-rail showcase keys, in design order (Link stays unavailable until L2). */
export const DEMO_SHOWCASE_ORDER = [
  "artifact:todo",
  "artifact:chat",
  "artifact:note",
] as const;

/** Visibly unavailable left-rail destinations (design-3158 lines 97–132 + Link). */
export const DEMO_LEFT_UNAVAILABLE = [
  "links",
  "artifact:module",
  "artifact:tag",
  "artifact:file",
  "artifact:calendar",
  "reminder",
  "routine",
  "artifact:email",
  "english",
  "rss",
  "dev",
] as const;

/** Right-drawer live keys. */
export const DEMO_RIGHT_LIVE = ["artifact:chat", "artifact:note"] as const;

/** Right-drawer unavailable keys (design-3158 lines 658–663). */
export const DEMO_RIGHT_UNAVAILABLE = ["artifact:file", "diff"] as const;

export type DemoShowcaseKey = "chat" | "todo" | "note";

export function showcaseKeyFromPanel(panel: string): DemoShowcaseKey | null {
  if (panel === "artifact:chat") return "chat";
  if (panel === "artifact:todo") return "todo";
  if (panel === "artifact:note") return "note";
  return null;
}

export function panelFromShowcaseKey(key: DemoShowcaseKey): `artifact:${DemoShowcaseKey}` {
  return `artifact:${key}`;
}
