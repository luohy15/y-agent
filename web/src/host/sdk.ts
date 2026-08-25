// The `@y/host` surface (plan sub-task S5): the curated set of app internals
// an artifact is allowed to depend on without a host redeploy. Published into
// the runtime registry by registry.ts; an artifact imports it as a normal
// bare specifier (`import { API, jsonFetcher } from "@y/host"`), which
// `y ui publish`'s esbuild `alias` resolves to `web/sdk/shims/y-host.cjs`.
import { API, authFetch, getToken, jsonFetcher } from "../api";
import {
  actionBadgeClass,
  CHAT_BADGE,
  getTopicChartColors,
  getTopicColor,
  priorityColorClass,
  statusBadgeClass,
  stripTracePrefix,
  topicBadgeClass,
  TRACE_BADGE,
} from "../components/badges";
import { ListEmpty, ListError, ListLoading } from "../components/ListStates";
import { HOST_CONTRACT_VERSION } from "./contract";
import { sanitizeEmailHtml } from "./sanitizeEmailHtml";
import { runHostCommand } from "./commands";
import { openArtifactDetail, useArtifactIntent } from "./intents";
import { useDetailContext } from "./detailContext";
import { usePanelLocation } from "./panelLocation";
import { navigateTo } from "./navigation";
import { readThemeColors, useThemeColors } from "./theme";
import { optimisticListMutate } from "../utils/optimisticMutate";
import { PatchDiff } from "@pierre/diffs/react";
import ArtifactView from "../components/ArtifactView";
import CodeEditor from "../components/CodeEditor";
import ImageLightbox from "../components/ImageLightbox";
import TagsEditor from "../components/TagsEditor";
import TraceView from "../components/TraceView";
import remarkStripComments from "../utils/remarkStripComments";
import { parseLocalFileReference } from "../utils/localFileLinks";
import { citationDomain, citationHostname } from "../components/citationDomain";
import { normalizeLinks } from "../components/citationLinks";
import { buildExportFilename, pickImageDelivery, toggleSelection, selectMessagesByIndices } from "../utils/messageExport";
import { deliverPng, exportElementToPng } from "../utils/exportImage";
import {
  extractContent,
  filterTrailingEmptyAssistantMessages,
  mergeToolArguments,
  mergeToolResult,
  parseChatMessages,
  parseRawChatMessage,
} from "../components/HostMessageView";

export const hostSdk = {
  HOST_CONTRACT_VERSION,

  // api.ts
  API,
  authFetch,
  jsonFetcher,
  getToken,

  // ListStates.tsx
  ListLoading,
  ListError,
  ListEmpty,

  // theme.ts (resolved colors, for libraries that cannot take a CSS var)
  useThemeColors,
  readThemeColors,

  // badges.tsx
  TRACE_BADGE,
  CHAT_BADGE,
  topicBadgeClass,
  statusBadgeClass,
  priorityColorClass,
  actionBadgeClass,
  getTopicColor,
  getTopicChartColors,
  stripTracePrefix,

  // navigation.ts
  navigateTo,

  // intents.ts
  useArtifactIntent,
  openArtifactDetail,

  // panelLocation.ts (contract v6) — which sidebar a `panel` surface is
  // mounted in ("left" activity bar vs. "right" drawer).
  usePanelLocation,

  // detailContext.ts (contract v8) — per-detail-mount host context.
  useDetailContext,

  // commands.ts (contract v4) — artifact -> host named command channel
  runHostCommand,

  // optimisticMutate.ts (contract v4) — shared list optimistic patcher
  optimisticListMutate,

  // ArtifactView.tsx / @pierre/diffs / ImageLightbox.tsx (contract v5, R2) —
  // host-owned megabyte leaves reached through @y/host instead of bundled.
  ArtifactView,
  PatchDiff,
  ImageLightbox,

  // CodeEditor.tsx (contract v7, todo 3068 H3) — host-owned CodeMirror leaf.
  // Keeps lazy per-language loading (codeEditorLangs.ts) inside the host so a
  // module never chooses which grammars to eagerly bundle; only the wrapper
  // call crosses the boundary.
  CodeEditor,

  // TraceView.tsx (contract v10, todo 3179 H1) — host-owned authenticated todo
  // detail / public-trace leaf. Modules mount the same physical implementation
  // used by the public reserved trace.md tab on /t/:shareId; heavy waterfall +
  // share code stays in the host bundle. Authenticated host FileViewer no longer
  // mounts this tab (todo 3179 H3).
  TraceView,

  // sanitizeEmailHtml.ts (contract v11, todo 3270 A3) — host-owned DOMPurify
  // leaf. The email module cannot resolve npm deps from its build tree, and the
  // host already ships DOMPurify for artifacts / markdown export.
  sanitizeEmailHtml,

  // TagsEditor.tsx (contract v12, todo 3285 S1) — shared chip editor used by
  // host todo detail and the file-module note surface (suggestions +
  // allowNew={false}, canonical tags only).
  TagsEditor,

  // remarkStripComments.ts / localFileLinks.ts / citationDomain.ts /
  // citationLinks.ts (contract v5, R2) — markdown rendering helpers shared
  // with HostMessageView.
  remarkStripComments,
  parseLocalFileReference,
  normalizeLinks,
  citationDomain,
  citationHostname,

  // exportImage.ts / messageExport.ts (contract v5, R2 + V2b) — PNG capture
  // primitive and its pure helpers; the view is supplied by the caller.
  exportElementToPng,
  deliverPng,
  buildExportFilename,
  pickImageDelivery,

  // HostMessageView.tsx (contract v5, R2) — default parsing set a module
  // may use as-is or replace.
  parseRawChatMessage,
  parseChatMessages,
  mergeToolResult,
  mergeToolArguments,
  filterTrailingEmptyAssistantMessages,
  extractContent,
  toggleSelection,
  selectMessagesByIndices,
};

export type { ThemeColors } from "./theme";
export type { ArtifactType, ArtifactMode } from "../components/ArtifactView";
export type {
  TraceViewProps,
  TraceChatsResponse,
  TraceLink,
  TraceNote,
  TraceCalendarEvent,
  TraceChat,
  TodoInfo,
  TodoPatch,
} from "../components/TraceView";
export type { TagsEditorProps } from "../components/TagsEditor";
