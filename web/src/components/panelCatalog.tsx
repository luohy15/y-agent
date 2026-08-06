import type { ReactNode } from "react";
import { artifactLabel, artifactPanelKey, mountableUiArtifacts, type Module } from "../host/artifacts";

export interface PanelItem<Key extends string = string> {
  key: Key;
  label: string;
  icon: ReactNode;
}

export function artifactIcon(icon?: string | null): ReactNode {
  if (icon === "chart") {
    return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18" /><path d="m7 16 4-5 4 3 5-7" /></svg>;
  }
  if (icon === "calendar") {
    return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>;
  }
  if (icon === "list") {
    return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6h13M8 12h13M8 18h13" /><path d="M3 6h.01M3 12h.01M3 18h.01" /></svg>;
  }
  if (icon === "bot") {
    return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="7" width="14" height="10" rx="2" /><path d="M12 7V3" /><circle cx="9" cy="12" r="1" /><circle cx="15" cy="12" r="1" /><path d="M9 17v2" /><path d="M15 17v2" /></svg>;
  }
  if (icon === "todo") {
    return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>;
  }
  return <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21 8-9-5-9 5 9 5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></svg>;
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

export function buildFilePanelItem(artifacts: Module[]): PanelItem<"artifact:file">[] {
  const file = mountableUiArtifacts(artifacts).find((artifact) => artifact.slug === "file");
  if (!file) return [];
  return [{ key: "artifact:file", label: artifactLabel(file), icon: artifactIcon(file.active_version.icon) }];
}

export function restoreRightPanel(saved: string | null): string {
  if (saved === "git") return "diff";
  if (saved === "chats") return "artifact:chat";
  if (saved === "files") return "artifact:file";
  if (saved === "links") return "notes";
  return saved || "notes";
}

export function resolveRightPanel(current: string, items: PanelItem[], modulesLoaded: boolean): string {
  if (!modulesLoaded) return current;
  return items.some((item) => item.key === current) ? current : "notes";
}
