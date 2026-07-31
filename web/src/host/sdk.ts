// The `@y/host` surface (plan sub-task S5): the curated set of app internals
// an artifact is allowed to depend on without a host redeploy. Published into
// the runtime registry by registry.ts; an artifact imports it as a normal
// bare specifier (`import { API, jsonFetcher } from "@y/host"`), which
// `y ui publish`'s esbuild `alias` resolves to `web/sdk/shims/y-host.cjs`.
import { API, authFetch, jsonFetcher } from "../api";
import {
  actionBadgeClass,
  CHAT_BADGE,
  getTopicChartColors,
  getTopicColor,
  priorityColorClass,
  statusBadgeClass,
  topicBadgeClass,
  TRACE_BADGE,
} from "../components/badges";
import { ListEmpty, ListError, ListLoading } from "../components/ListStates";
import { HOST_CONTRACT_VERSION } from "./contract";
import { openArtifactDetail, useArtifactIntent } from "./intents";
import { navigateTo } from "./navigation";
import { readThemeColors, useThemeColors } from "./theme";

export const hostSdk = {
  HOST_CONTRACT_VERSION,

  // api.ts
  API,
  authFetch,
  jsonFetcher,

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

  // navigation.ts
  navigateTo,

  // intents.ts
  useArtifactIntent,
  openArtifactDetail,
};

export type { ThemeColors } from "./theme";
