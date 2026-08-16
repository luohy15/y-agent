/**
 * Host contract surface available to UI artifacts via bare imports.
 * Specifiers are resolved at build time to CJS alias shims that read
 * `globalThis.__Y_HOST__` (decision D1). Contract version lives in
 * contract.json and is stamped onto each published version as min_host_version.
 *
 * MODULE SHAPE (pages/decision-2412-module-shape.md)
 * One artifact is ONE module defining up to three production surfaces plus an
 * optional public demo entrypoint (todo 3158):
 *
 *     export const panel = MyPanel;    // required — left sidebar (~280px)
 *     export const detail = MyDetail;  // optional — center / full-width view
 *     export const shell = MyShell;    // optional — persistent center column
 *     export const demo = MyDemo;      // optional in production; required for
 *                                      // public /demo/* delivery
 *
 * A bare `export default MyPanel` is the shorthand for a panel-only artifact.
 * The host gives one sidebar entry per artifact; `detail`, when present, opens
 * in the center surface from the panel header. There is no dedicated URL for
 * a detail view; it restores as a persisted tab like any other file tab.
 * `shell` is claimed in module.json (`"surfaces"`), not inferred from the
 * bundle, is held by at most one module at a time, and falls back to the host's
 * own view when unclaimed. `demo` is introspected from the bundle on the public
 * path only; production loading still accepts older bundles that omit it. No
 * surface receives props.
 */

declare module "react" {
  export type ReactNode = any;
  export type FC<P = {}> = (props: P) => ReactNode;
  export function useState<S>(initial: S | (() => S)): [S, (v: S | ((prev: S) => S)) => void];
  export function useEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void;
  export function useMemo<T>(factory: () => T, deps: readonly unknown[]): T;
  export function useCallback<T extends (...args: any[]) => any>(fn: T, deps: readonly unknown[]): T;
  export function useRef<T>(initial: T): { current: T };
  export function useContext<T>(context: { Provider: any; Consumer: any; _currentValue?: T }): T;
  export function createContext<T>(defaultValue: T): {
    Provider: any;
    Consumer: any;
    _currentValue?: T;
  };
  export function createElement(type: any, props?: any, ...children: any[]): any;
  export function Fragment(props: { children?: any }): any;
  const React: {
    useState: typeof useState;
    useEffect: typeof useEffect;
    useMemo: typeof useMemo;
    useCallback: typeof useCallback;
    useRef: typeof useRef;
    useContext: typeof useContext;
    createContext: typeof createContext;
    createElement: typeof createElement;
    Fragment: typeof Fragment;
  };
  export default React;
}

declare module "react/jsx-runtime" {
  export const jsx: any;
  export const jsxs: any;
  export const Fragment: any;
}

declare namespace JSX {
  interface IntrinsicElements {
    [elemName: string]: any;
  }
  interface Element {
    [key: string]: any;
  }
}

declare module "react-dom" {
  export function createPortal(children: any, container: Element): any;
  const ReactDOM: { createPortal: typeof createPortal };
  export default ReactDOM;
}

declare module "react-dom/client" {
  export function createRoot(container: Element): { render: (node: any) => void; unmount: () => void };
}

declare module "swr" {
  export type Key = string | readonly unknown[] | null | undefined | false;
  export type Fetcher<Data> = (...args: any[]) => Data | Promise<Data>;
  export interface SWRResponse<Data = any, Error = any> {
    data: Data | undefined;
    error: Error | undefined;
    isLoading: boolean;
    isValidating: boolean;
    mutate: (data?: Data | Promise<Data> | ((current?: Data) => Data | undefined), opts?: any) => Promise<Data | undefined>;
  }
  export default function useSWR<Data = any, Error = any>(
    key: Key,
    fetcher?: Fetcher<Data>,
    config?: any,
  ): SWRResponse<Data, Error>;
  export function useSWRConfig(): {
    cache: { keys(): IterableIterator<string>; get(key: string): any; set(key: string, value: any): void; delete(key: string): void };
    mutate: (matcher: any, data?: any, opts?: any) => Promise<any>;
  };
  export const mutate: (matcher: any, data?: any, opts?: any) => Promise<any>;
}

// Contract v4 subpath external — same host-instance guarantee as top-level `swr`.
declare module "swr/infinite" {
  import type { Key, Fetcher, SWRResponse } from "swr";
  export type SWRInfiniteKeyLoader = (index: number, previousPageData: any) => Key;
  export interface SWRInfiniteResponse<Data = any, Error = any> extends SWRResponse<Data[], Error> {
    size: number;
    setSize: (size: number | ((size: number) => number)) => Promise<Data[] | undefined>;
  }
  export default function useSWRInfinite<Data = any, Error = any>(
    getKey: SWRInfiniteKeyLoader,
    fetcher?: Fetcher<Data>,
    config?: any,
  ): SWRInfiniteResponse<Data, Error>;
  export function infinite<Data = any, Error = any>(
    getKey: SWRInfiniteKeyLoader,
    fetcher?: Fetcher<Data>,
    config?: any,
  ): SWRInfiniteResponse<Data, Error>;
  export function unstable_serialize(getKey: SWRInfiniteKeyLoader): string;
}

declare module "recharts" {
  export const LineChart: any;
  export const BarChart: any;
  export const ComposedChart: any;
  export const PieChart: any;
  export const AreaChart: any;
  export const RadarChart: any;
  export const RadialBarChart: any;
  export const ScatterChart: any;
  export const Line: any;
  export const Bar: any;
  export const Area: any;
  export const Pie: any;
  export const Cell: any;
  export const XAxis: any;
  export const YAxis: any;
  export const ZAxis: any;
  export const CartesianGrid: any;
  export const Tooltip: any;
  export const Legend: any;
  export const ResponsiveContainer: any;
  export const ReferenceLine: any;
  export const ReferenceArea: any;
  export const Brush: any;
  export const LabelList: any;
  export const Label: any;
}

// Contract v5 external (R3): already eager in the host main chunk today, so
// a module reusing it costs the main chunk 0 bytes.
declare module "react-markdown" {
  export function defaultUrlTransform(value: string): string;
  const ReactMarkdown: (props: {
    children?: string;
    remarkPlugins?: unknown[];
    rehypePlugins?: unknown[];
    urlTransform?: (value: string) => string;
    components?: Record<string, unknown>;
    [key: string]: unknown;
  }) => any;
  export default ReactMarkdown;
}

// Contract v5 external (R3). See react-markdown above for the rationale.
declare module "remark-gfm" {
  const remarkGfm: (options?: unknown) => undefined;
  export default remarkGfm;
}

declare module "lightweight-charts" {
  export const AreaSeries: any;
  export enum ColorType {
    Solid = "solid",
    VerticalGradient = "gradient",
  }
  export function createChart(container: HTMLElement, options?: any): IChartApi;
  export function createSeriesMarkers<T = Time>(
    series: ISeriesApi<any>,
    markers?: SeriesMarker<T>[],
  ): ISeriesMarkersPluginApi<T>;

  export interface IChartApi {
    addSeries<T = unknown>(definition: any, options?: any): ISeriesApi<T>;
    applyOptions(options: any): void;
    timeScale(): { fitContent(): void; [key: string]: any };
    remove(): void;
  }
  export interface ISeriesApi<T = unknown> {
    setData(data: any[]): void;
    [key: string]: any;
  }
  export interface ISeriesMarkersPluginApi<T = Time> {
    setMarkers(markers: SeriesMarker<T>[]): void;
  }
  export interface SeriesMarker<T = Time> {
    time: T;
    position: "aboveBar" | "belowBar" | "inBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle" | "square";
    text?: string;
  }
  export type Time = number | { year: number; month: number; day: number } | string;
  export type UTCTimestamp = number & { readonly __brand: "UTCTimestamp" };
}

/**
 * `@y/host` surface — must match the runtime `hostSdk` object published by
 * the web host (`web/src/host/sdk.ts`). Names that are not on that object
 * typecheck cleanly here but throw at runtime when the shim reads the
 * registry. Do not invent helpers; add them to the host first.
 */
declare module "@y/host" {
  /** Contract version of the running host. Artifacts with a higher min_host_version refuse to mount. */
  export const HOST_CONTRACT_VERSION: number;

  // api.ts
  /** API base path used by the host (e.g. "/api"). */
  export const API: string;
  /** Authenticated fetch that attaches the session token. */
  export function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  /** JSON-decoding fetcher for useSWR. */
  export function jsonFetcher<T = any>(url: string): Promise<T>;
  /** Raw session token, e.g. to build an EventSource URL or check logged-in state. */
  export function getToken(): string | null;

  // ListStates.tsx — prop shapes mirror web/src/components/ListStates.tsx.
  // `className` replaces the default "p-2" padding on all three.
  export function ListLoading(props?: { className?: string }): any;
  /** Renders "Error: <message>" from a thrown value; an AbortError renders nothing. */
  export function ListError(props?: { error?: unknown; className?: string }): any;
  /** Renders "No <label> found" — `label` is the noun, e.g. "transactions". */
  export function ListEmpty(props: { label: string; className?: string }): any;

  // theme.ts — resolved colors for libraries that cannot take a CSS var (e.g. recharts)
  export interface ThemeColors {
    base03: string;
    base02: string;
    base01: string;
    base0: string;
    base1: string;
    blue: string;
    red: string;
    green: string;
    yellow: string;
    cyan: string;
    magenta: string;
    violet: string;
    orange: string;
  }
  export function useThemeColors(): ThemeColors;
  export function readThemeColors(): ThemeColors;

  // badges.tsx
  export const TRACE_BADGE: string;
  export const CHAT_BADGE: string;
  export function topicBadgeClass(topic: string): string;
  export function statusBadgeClass(status: string): string;
  export function priorityColorClass(priority: string): string;
  export function actionBadgeClass(action: string): string;
  export function getTopicColor(topic: string): { bg: string; text: string };
  export function getTopicChartColors(topic: string): { fill: string; stroke: string };
  /** Strip a leading `[trace:<id> ...]` prefix from message content. */
  export function stripTracePrefix(content: string): string;

  // navigation.ts — push history + popstate (artifacts cannot import react-router)
  export function navigateTo(path: string): void;

  // intents.ts — host->artifact focus channel (contract v3). The store is
  // retained: a late-mounting subscriber still gets the latest intent set for
  // its slug before it mounted.
  /** Read + subscribe to the latest focus intent the host set for `slug`. */
  export function useArtifactIntent<T = unknown>(slug: string): T | null;
  /** Ask the host to open this artifact's detail surface as a tab. */
  export function openArtifactDetail(slug: string): void;

  // panelLocation.ts (contract v6) — which sidebar this `panel` surface is
  // mounted in. Always "left" outside a "panel" surface (detail/shell do not
  // provide it) and for older/unspecified host call sites.
  /** Which sidebar this `panel` surface is mounted in: "left" or "right". */
  export function usePanelLocation(): "left" | "right";

  // detailContext.ts (contract v8) — host-provided per-detail-mount context.
  // Null outside a detail surface or when the host did not pass detailContext.
  /** Read the host-only context for this detail mount (generic; shape is host-defined). */
  export function useDetailContext<T = unknown>(): T | null;

  // commands.ts — artifact->host named command channel (contract v4). An
  // unregistered name is a silent no-op. Registration is host-internal and
  // not exported here (same partition as setArtifactIntent).
  /**
   * Ask the host to run a named command. Known names include:
   * `todo.open`, `todo.openTrace`, `chat.open`, `chat.setTraceFilter`,
   * `file.open`, `link.open` (`{ activityId, contentKey? }`),
   * `calendar.focusDate` (`{ date }`), `trace.clearRoute` (replace `/trace/:id`).
   */
  export function runHostCommand(name: string, payload?: unknown): void;

  // optimisticMutate.ts — shared optimistic list patcher (contract v4).
  // `swr` must come from `useSWRConfig()`, never the top-level `swr` mutate.
  export type CacheKeyMatcher = string | RegExp | ((key: string) => boolean);
  export interface SWRCacheHandle {
    cache: { keys(): IterableIterator<string>; get(key: string): any; set(key: string, value: any): void; delete(key: string): void };
    mutate: (matcher: any, data?: any, opts?: any) => Promise<any>;
  }
  export function optimisticListMutate<T>(
    swr: SWRCacheHandle,
    matcher: CacheKeyMatcher,
    idKey: keyof T,
    id: string,
    patch: Partial<T>,
    request: () => Promise<unknown>,
  ): Promise<void>;

  // ArtifactView.tsx / @pierre/diffs / ImageLightbox.tsx (contract v5, R2) —
  // host-owned megabyte leaves (mermaid, vega-lite, DOMPurify, highlight.js,
  // @pierre/diffs, react-zoom-pan-pinch). The module owns fence dispatch —
  // deciding a fence's `ArtifactType` and `ArtifactMode` — but renders through
  // these leaves rather than bundling the underlying libraries itself.
  export type ArtifactType = "mermaid" | "vega-lite" | "artifact-svg";
  export type ArtifactMode = "preview" | "raw";
  export function ArtifactView(props: {
    type: ArtifactType;
    spec: string;
    mode: ArtifactMode;
    onModeChange: (mode: ArtifactMode) => void;
    onOpenInTab?: () => void;
    variant: "inline" | "tab";
  }): any;
  export function PatchDiff(props: { patch: string; options?: Record<string, unknown> }): any;
  export function ImageLightbox(props: {
    images: string[];
    index: number;
    onClose: () => void;
    onNext: () => void;
    onPrev: () => void;
  }): any;

  // CodeEditor.tsx (contract v7, todo 3068 H3) — host-owned CodeMirror leaf.
  // Language grammars stay host-lazy via codeEditorLangs.ts; modules only pass
  // the file path / value / save callbacks across the boundary.
  export function CodeEditor(props: {
    value: string;
    onChange: (value: string) => void;
    filePath: string;
    onSave?: (filePath: string) => void;
    readOnly?: boolean;
    className?: string;
    initialLine?: number;
    onInitialLineApplied?: () => void;
  }): any;

  // TraceView.tsx (contract v10, todo 3179 H1) — host-owned authenticated todo
  // detail / public-trace leaf. One physical implementation; modules mount it
  // rather than copying waterfall / share / todo-detail code.
  export interface TraceChat {
    chat_id: string;
    title: string;
    topic: string;
    skill?: string;
    backend?: string;
    bot_name?: string;
    segments: Array<{ start_unix: number; end_unix: number }>;
    messages?: unknown[];
  }
  export interface TodoHistoryEntry {
    timestamp: string;
    action: string;
    note?: string;
  }
  export interface TodoNoteInfo {
    note_id: string;
    content_key: string;
    front_matter?: Record<string, unknown> | null;
    share_id?: string;
    has_password?: boolean;
  }
  export interface TodoInfo {
    todo_id: string;
    name: string;
    status: string;
    desc?: string;
    tags?: string[];
    priority?: string;
    due_date?: string;
    progress?: string;
    completed_at?: string;
    created_at?: string;
    updated_at?: string;
    history?: TodoHistoryEntry[];
    notes?: TodoNoteInfo[];
  }
  export interface TodoPatch {
    name?: string;
    status?: string;
    desc?: string | null;
    tags?: string[] | null;
    priority?: string | null;
    due_date?: string | null;
    progress?: string | null;
  }
  export interface TraceLink {
    link_id: string;
    base_url: string;
    title?: string;
    download_status?: string | null;
    activity_id?: string;
  }
  export interface TraceNote {
    note_id: string;
    content_key: string;
    front_matter?: Record<string, any> | null;
    created_at?: string;
    share_id?: string;
    has_password?: boolean;
  }
  export interface TraceCalendarEvent {
    event_id: string;
    summary: string;
    start_time: string;
    end_time?: string;
    description?: string;
    all_day: boolean;
    status: string;
    source?: string;
  }
  export interface TraceChatsResponse {
    chats: TraceChat[];
    todo_name: string | null;
    todo_status: string | null;
    todo: TodoInfo | null;
    links?: TraceLink[];
    notes?: TraceNote[];
    calendar_events?: TraceCalendarEvent[];
  }
  export interface TraceViewProps {
    isLoggedIn: boolean;
    selectedTraceId: string | null;
    defaultWorkDir?: string;
    onSelectChat?: (chatId: string) => void;
    onPreviewLink?: (activityId: string) => void;
    onSelectCalendarEvent?: (startTime: string) => void;
    onOpenFile?: (path: string) => void;
    onTraceTodoDirtyChange?: (dirty: boolean) => void;
    injectedData?: TraceChatsResponse | null;
    onOpenNote?: (note: TraceNote) => void;
    onBack?: () => void;
    requireTodo?: boolean;
    /** Latched once per selectedTraceId while unavailable; treat as idempotent. */
    onUnavailable?: () => void;
  }
  export function TraceView(props: TraceViewProps): any;

  // remarkStripComments.ts / localFileLinks.ts / citationDomain.ts /
  // citationLinks.ts (contract v5, R2) — markdown rendering helpers shared
  // with HostMessageView.
  /** Remark plugin: drop standalone/inline HTML-comment mdast nodes. */
  export function remarkStripComments(): (tree: unknown) => void;
  export interface LocalFileReference {
    path: string;
    line?: number;
    column?: number;
  }
  export function parseLocalFileReference(
    href?: string | null,
    options?: { allowRelative?: boolean },
  ): LocalFileReference | null;
  export type NormalizedCitationLink = {
    url: string;
    title?: string;
    snippet?: string;
    last_updated?: string;
  };
  export function normalizeLinks(links?: unknown[]): NormalizedCitationLink[];
  export function citationDomain(url: string): string;
  export function citationHostname(url: string): string;

  // exportImage.ts / messageExport.ts (contract v5, R2 + V2b) — PNG capture
  // primitive and its pure helpers; the caller supplies the React element to
  // render offscreen, so a module-rendered conversation exports module bubbles.
  export function exportElementToPng(
    element: unknown,
    opts?: { scale?: number; backgroundColor?: string },
  ): Promise<{ blob: Blob; dataUrl: string }>;
  export function deliverPng(blob: Blob, dataUrl: string, filename?: string): Promise<void>;
  export function buildExportFilename(date?: Date): string;
  export function pickImageDelivery(signals: { canShareFiles: boolean; isTouch: boolean }): "share" | "download";

  // chatMessageParser.ts / MessageList.tsx (contract v5, R2) — default
  // parsing set the module may use as-is or replace with its own.
  export interface ChatMessage {
    role: string;
    content: string;
    toolName?: string;
    arguments?: Record<string, unknown>;
    toolCallId?: string;
    timestamp?: string;
    images?: string[];
    links?: NormalizedCitationLink[] | string[];
  }
  export function parseRawChatMessage(evt: unknown): ChatMessage[];
  /** Batch wrapper over parseRawChatMessage + mergeToolResult + the trailing-empty filter. */
  export function parseChatMessages(rawMessages: unknown[]): ChatMessage[];
  export function mergeToolResult(pending: ChatMessage, result: ChatMessage): ChatMessage;
  export function mergeToolArguments(
    startArgs?: Record<string, unknown>,
    resultArgs?: Record<string, unknown>,
  ): Record<string, unknown> | undefined;
  export function filterTrailingEmptyAssistantMessages(messages: ChatMessage[]): ChatMessage[];
  export function extractContent(content?: string | Array<{ type: string; text?: string }>): string;
  export function toggleSelection(selected: Set<number>, index: number): Set<number>;
  export function selectMessagesByIndices(messages: ChatMessage[], selectedIndices: Iterable<number>): ChatMessage[];
}
