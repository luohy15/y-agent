import type { ReactNode } from "react";
import { artifactLabel, artifactPanelKey, mountableUiArtifacts, type Module } from "../host/artifacts";

export interface PanelItem<Key extends string = string> {
  key: Key;
  label: string;
  icon: ReactNode;
}

export const DEFAULT_MODULE_ICON = (
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21 8-9-5-9 5 9 5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></svg>
);

export const MODULE_ICONS: Record<string, ReactNode> = {
  chart: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18" /><path d="m7 16 4-5 4 3 5-7" /></svg>,
  calendar: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>,
  list: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6h13M8 12h13M8 18h13" /><path d="M3 6h.01M3 12h.01M3 18h.01" /></svg>,
  bot: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="7" width="14" height="10" rx="2" /><path d="M12 7V3" /><circle cx="9" cy="12" r="1" /><circle cx="15" cy="12" r="1" /><path d="M9 17v2" /><path d="M15 17v2" /></svg>,
  todo: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>,
  file: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>,
  "file-text": <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>,
  package: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m7.5 4.27 9 5.15M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="M3.29 7 12 12l8.71-5M12 22V12" /></svg>,
  box: DEFAULT_MODULE_ICON,
  message: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z" /></svg>,
  tag: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z" /><path d="M7 7h.01" /></svg>,
  activity: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg>,
};

export function artifactIcon(icon?: string | null): ReactNode {
  return (icon && MODULE_ICONS[icon]) || DEFAULT_MODULE_ICON;
}

export function buildModulePanelItems(artifacts: Module[]): PanelItem<`artifact:${string}`>[] {
  return mountableUiArtifacts(artifacts).map((artifact) => ({
    key: artifactPanelKey(artifact.slug),
    label: artifactLabel(artifact),
    icon: artifactIcon(artifact.active_version.icon),
  }));
}

// Round-2 gap closure (plan-3046-right-sidebar.md R1) + C1 (plan-3068): the
// right drawer only resolves chat and file modules dynamically — arbitrary
// module panels remain left-activity-bar only. Returns [] while the target
// module is not yet mountable (cold-loading, disabled, unpublished), which
// resolveRightPanel's cold-retention / removed-module-fallback logic already
// handles the same way it does for any other catalog item.
export function buildChatPanelItem(artifacts: Module[]): PanelItem<"artifact:chat">[] {
  const chat = mountableUiArtifacts(artifacts).find((artifact) => artifact.slug === "chat");
  if (!chat) return [];
  return [{ key: "artifact:chat", label: artifactLabel(chat), icon: artifactIcon(chat.active_version.icon) }];
}

export function buildNotePanelItem(artifacts: Module[]): PanelItem<"artifact:note">[] {
  const note = mountableUiArtifacts(artifacts).find((artifact) => artifact.slug === "note");
  if (!note) return [];
  return [{ key: "artifact:note", label: artifactLabel(note), icon: artifactIcon(note.active_version.icon) }];
}

export function buildFilePanelItem(artifacts: Module[]): PanelItem<"artifact:file">[] {
  const file = mountableUiArtifacts(artifacts).find((artifact) => artifact.slug === "file");
  if (!file) return [];
  return [{ key: "artifact:file", label: artifactLabel(file), icon: artifactIcon(file.active_version.icon) }];
}

export function restoreRightPanel(saved: string | null): string {
  if (saved === "git") return "diff";
  if (saved === "chats") return "artifact:chat";
  if (saved === "notes" || saved === "links") return "artifact:note";
  if (saved === "files") return "artifact:file";
  return saved || "artifact:note";
}

export function resolveRightPanel(current: string, items: PanelItem[], modulesLoaded: boolean): string {
  if (!modulesLoaded) return current;
  return items.some((item) => item.key === current) ? current : "artifact:note";
}
