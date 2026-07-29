/**
 * Host contract surface available to UI artifacts via bare imports.
 * Specifiers are resolved at build time to CJS alias shims that read
 * `globalThis.__Y_HOST__` (decision D1). Contract version lives in
 * contract.json and is stamped onto each published version as min_host_version.
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

  // ListStates.tsx
  export function ListLoading(props?: { label?: string }): any;
  export function ListError(props?: { message?: string; onRetry?: () => void }): any;
  export function ListEmpty(props?: { message?: string }): any;

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

  // navigation.ts — push history + popstate (artifacts cannot import react-router)
  export function navigateTo(path: string): void;
}
