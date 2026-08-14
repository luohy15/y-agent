// The restricted public demo runtime (todo 3158 H3,
// docs/prd/public-module-demos.md, pages/plan-3158-public-module-demos.md D5/D6).
//
// A `/demo/*` page loads the *production* module UI bundle and mounts its
// `demo` export. The only thing standing between that production component
// tree and the authenticated origin is this file, so the install order is
// load-bearing and every step is fail-closed:
//
//   1. capture the one fetch function the page is allowed to use,
//   2. deny global fetch / XHR / WebSocket / EventSource,
//   3. replace durable browser storage (Web Storage, cookies, IndexedDB) with
//      memory-only shims, and remove the service worker container,
//   4. verify every one of those postconditions, and abort the whole install
//      if any of them is not observably true,
//   5. only then grant capabilities: pin the loader's public-bundle fetch and
//      install the restricted `@y/host` registry,
//   6. only then import and mount module bytes (see bootstrap.tsx).
//
// Doing (1) after (2) would capture the denier; doing (5) before (4) would let
// a page that failed to restrict itself run module code anyway. Nothing here
// infers demo mode from a missing token: the page selects it from its own
// route before any module code exists (PRD story 30).
//
// OPEN RESIDUAL RISK (review round 1, finding 1 — pending an architecture
// decision, deliberately not fixed here): these replacements restrict the
// page's own realm. Module code keeps ordinary DOM access, so it can create a
// same-origin `about:blank` iframe and read native `fetch` / `localStorage` /
// `indexedDB` / `document.cookie` out of that fresh realm. Closing it means
// running module code somewhere it cannot obtain same-origin ambient
// capabilities (a sandboxed opaque-origin iframe with a narrow message
// bridge), which changes the mount architecture rather than this file. Until
// then the guardrail below is in-realm only.
//
// Scope note: this denies the request paths module code can reach
// programmatically. It does not (and cannot) block `<img>`/`<a>`/third-party
// tags already in index.html; those carry no ambient identity for this origin
// and are not part of the module boundary.
import { API } from "../api";
import { hostSdk } from "../host/sdk";
import { installHostRegistry } from "../host/registry";
import { publicBundleFetcher } from "../host/loader";
import { demoRouteFor, DEMO_ROUTES } from "./routes";
import { openDemoArtifactDetail, runDemoHostCommand } from "./commands";

const PUBLIC_DEMO_PREFIX = "/api/module/public-demo/";
const PUBLIC_BUNDLE_PREFIX = "/api/module/public-bundle/";

// Fictional, non-resolvable base (RFC 2606 reserved TLD) handed to module code
// as `API`. A demo must never compose a real origin URL: if some production
// path still builds one, it fails visibly here instead of reaching an
// authenticated route with the visitor's cookies.
export const DEMO_API_BASE = "https://demo.invalid";

function denied(capability: string): never {
  throw new Error(`[y-demo] ${capability} is not available in the public demo runtime`);
}

// Captured once, at the first install, and never re-captured: a second capture
// after the globals were denied would pin the denier as "the allowed fetcher".
let capturedFetch: typeof fetch | null = null;

/** The only network capability on a demo page: same-origin GETs of the public
 * demo projection and the content-addressed public bundle. Everything else —
 * including any other `/api/module/*` route — throws. */
export function allowedDemoFetch(input: string, init?: RequestInit): Promise<Response> {
  // Gated on a fully verified install: an aborted install must leave the page
  // with no usable network capability at all.
  if (!installed || !capturedFetch) denied("network access before the demo runtime is installed");
  const url = new URL(input, window.location.href);
  const base = new URL(API, window.location.href);
  if (url.origin !== base.origin) denied(`cross-origin request to ${url.origin}`);

  const path = url.pathname;
  let allowed = false;
  if (path.startsWith(PUBLIC_DEMO_PREFIX)) {
    const key = decodeURIComponent(path.slice(PUBLIC_DEMO_PREFIX.length));
    allowed = DEMO_ROUTES.some((route) => route.key === key);
  } else if (path.startsWith(PUBLIC_BUNDLE_PREFIX)) {
    const rest = path.slice(PUBLIC_BUNDLE_PREFIX.length);
    allowed = rest.length > 0 && !rest.includes("/");
  }
  if (!allowed) denied(`request to ${path}`);

  // `credentials: "omit"` so an origin cookie can never turn an anonymous
  // public GET into an identified one, and no Authorization header is ever
  // attached (that is the loader's contract too).
  return capturedFetch(url.toString(), { ...init, credentials: "omit" });
}

// Attempt only. Nothing here decides whether the page is safe: every
// replacement is re-read afterwards by `verifyRestrictions`, which is the sole
// authority. A silent failure to restrict must not be a warning the page
// continues past (round 1 finding 3).
function replaceGlobal(target: object, name: string, value: unknown): void {
  try {
    (target as Record<string, unknown>)[name] = value;
    if ((target as Record<string, unknown>)[name] === value) return;
  } catch {
    // fall through to defineProperty
  }
  try {
    Object.defineProperty(target, name, { value, configurable: true, writable: true });
  } catch {
    // Reported by verifyRestrictions, which aborts the install.
  }
}

// The sentinels are module-level so verification can identity-check what is
// actually installed. Probing by *calling* them would be wrong: if a
// replacement silently failed, calling `new WebSocket(url)` to find out would
// open the very connection this is meant to prevent.
const BLOCKED_NETWORK_GLOBALS: Record<string, unknown> = {
  fetch: () => denied("fetch"),
  // Constructors, not calls: `new XMLHttpRequest()` / `new WebSocket(...)` /
  // `new EventSource(...)` (the SSE path a live chat surface would use) must
  // fail the same way a fetch does.
  XMLHttpRequest: function BlockedXMLHttpRequest() {
    denied("XMLHttpRequest");
  },
  WebSocket: function BlockedWebSocket() {
    denied("WebSocket");
  },
  EventSource: function BlockedEventSource() {
    denied("EventSource");
  },
};

function denyGlobalNetwork(): void {
  for (const [name, sentinel] of Object.entries(BLOCKED_NETWORK_GLOBALS)) {
    replaceGlobal(globalThis, name, sentinel);
  }
}

/** A Storage-shaped map that starts empty and dies with the page. Starting
 * empty is the point: a visitor's real `jwt_token` / preferences are invisible
 * to module code, and a demo write cannot outlive the tab. */
export function createMemoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    key(index: number) {
      return Array.from(entries.keys())[index] ?? null;
    },
    getItem(key: string) {
      return entries.has(key) ? entries.get(key)! : null;
    },
    setItem(key: string, value: string) {
      entries.set(String(key), String(value));
    },
    removeItem(key: string) {
      entries.delete(key);
    },
    clear() {
      entries.clear();
    },
  } as Storage;
}

// Identity-checkable stand-ins, same reasoning as BLOCKED_NETWORK_GLOBALS.
const demoLocalStorage = createMemoryStorage();
const demoSessionStorage = createMemoryStorage();
const blockedCookieGetter = () => "";

function denyDurableStorage(): void {
  replaceGlobal(window, "localStorage", demoLocalStorage);
  replaceGlobal(window, "sessionStorage", demoSessionStorage);
  // IndexedDB has no cheap in-memory stand-in; absent is the honest answer and
  // is what feature-detecting code already handles.
  replaceGlobal(window, "indexedDB", undefined);
  try {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: blockedCookieGetter,
      set: () => {},
    });
  } catch {
    // Reported by verifyRestrictions, which aborts the install.
  }
}

// Service workers are the one durable write the denied `fetch` cannot cover:
// the browser fetches and installs the worker script itself, and a successful
// registration outlives the page (round 1 finding 2). Removing the entry point
// also removes `.controller` / `.ready`, so demo code cannot reach an existing
// controller either.
function denyServiceWorkers(): void {
  replaceGlobal(navigator, "serviceWorker", undefined);
}

// Every postcondition that must observably hold before module bytes may be
// fetched, evaluated, or handed the host SDK. A verifier that throws counts as
// a failure: unreadable is not the same as restricted.
const REQUIRED_RESTRICTIONS: ReadonlyArray<{ name: string; holds: () => boolean }> = [
  ...Object.entries(BLOCKED_NETWORK_GLOBALS).map(([name, sentinel]) => ({
    name,
    holds: () => (globalThis as unknown as Record<string, unknown>)[name] === sentinel,
  })),
  { name: "localStorage", holds: () => window.localStorage === demoLocalStorage },
  { name: "sessionStorage", holds: () => window.sessionStorage === demoSessionStorage },
  { name: "indexedDB", holds: () => window.indexedDB === undefined },
  {
    name: "document.cookie",
    holds: () =>
      Object.getOwnPropertyDescriptor(document, "cookie")?.get === blockedCookieGetter &&
      document.cookie === "",
  },
  { name: "navigator.serviceWorker", holds: () => navigator.serviceWorker === undefined },
];

/** Names of the restrictions that are not observably in place. Empty means the
 * page is safe to run module code in. */
export function verifyRestrictions(): string[] {
  return REQUIRED_RESTRICTIONS.filter((restriction) => {
    try {
      return !restriction.holds();
    } catch {
      return true;
    }
  }).map((restriction) => restriction.name);
}

/** Local navigation allowlist: the four demo routes and the public docs. A
 * real page load (not history.pushState) is deliberate — leaving a demo must
 * rebuild the runtime from scratch and reset every in-memory change. */
export function demoNavigate(path: string): void {
  const target = new URL(path, window.location.href);
  if (
    target.origin === window.location.origin &&
    (demoRouteFor(target.pathname) || /^\/docs(?:\/[^/]+)?$/.test(target.pathname))
  ) {
    window.location.assign(`${target.pathname}${target.search}`);
    return;
  }
  denied(`navigation to ${path}`);
}

// Everything module code may keep from the production `@y/host` surface:
// pure formatting, presentational leaves, in-memory helpers, and hooks whose
// host-side channels are simply never fed on a demo page. Anything absent from
// this list is replaced by a thrower below, so a capability added to hostSdk
// later is denied by default instead of silently published to anonymous
// visitors.
const DEMO_SAFE_KEYS: readonly string[] = [
  "HOST_CONTRACT_VERSION",
  // ListStates.tsx
  "ListLoading",
  "ListError",
  "ListEmpty",
  // theme.ts
  "useThemeColors",
  "readThemeColors",
  // badges.tsx
  "TRACE_BADGE",
  "CHAT_BADGE",
  "topicBadgeClass",
  "statusBadgeClass",
  "priorityColorClass",
  "actionBadgeClass",
  "getTopicColor",
  "getTopicChartColors",
  "stripTracePrefix",
  // intents.ts / panelLocation.ts / detailContext.ts — host channels. The
  // demo shell supplies only in-memory values and resets them on page reload.
  "useArtifactIntent",
  "usePanelLocation",
  "useDetailContext",
  "runHostCommand",
  "openArtifactDetail",
  // optimisticMutate.ts — patches the in-memory SWR cache only.
  "optimisticListMutate",
  // Host-owned presentational leaves.
  "ArtifactView",
  "PatchDiff",
  "ImageLightbox",
  "CodeEditor",
  // Markdown / citation helpers (pure).
  "remarkStripComments",
  "parseLocalFileReference",
  "normalizeLinks",
  "citationDomain",
  "citationHostname",
  // Local PNG capture + its pure helpers (canvas only, no upload).
  "exportElementToPng",
  "deliverPng",
  "buildExportFilename",
  "pickImageDelivery",
  // Message parsing (pure).
  "parseRawChatMessage",
  "parseChatMessages",
  "mergeToolResult",
  "mergeToolArguments",
  "filterTrailingEmptyAssistantMessages",
  "extractContent",
  "toggleSelection",
  "selectMessagesByIndices",
];

/** The `@y/host` object published to module bytes on a demo page. Same key set
 * as production so a missing capability is a clear error rather than an
 * `undefined is not a function`; every unsafe key is a thrower. */
export function buildDemoHostSdk(): Record<string, unknown> {
  const source = hostSdk as unknown as Record<string, unknown>;
  const restricted: Record<string, unknown> = {};
  for (const key of Object.keys(source)) {
    restricted[key] = DEMO_SAFE_KEYS.includes(key) ? source[key] : () => denied(key);
  }
  // Explicit substitutions: identity and network keys remain throwers. The
  // host-command endpoints route only to the demo shell's in-memory registry.
  restricted.API = DEMO_API_BASE;
  restricted.getToken = () => denied("getToken");
  restricted.navigateTo = demoNavigate;
  restricted.runHostCommand = runDemoHostCommand;
  restricted.openArtifactDetail = openDemoArtifactDetail;
  return restricted;
}

let installed = false;

/**
 * Install the restricted runtime, or throw. Idempotent, and safe to call twice:
 * the allowed fetcher is captured only on the first call.
 *
 * Nothing that grants a capability happens before `verifyRestrictions()` comes
 * back empty — not the bundle fetch seam, not the host registry, not the
 * `installed` flag that `DemoMount` and `allowedDemoFetch` gate on. A browser
 * or property change that defeats one of the restrictions therefore ends as an
 * unavailable page, never as module bytes running with a native capability
 * still reachable (round 1 finding 3).
 */
export function installPublicDemoRuntime(): void {
  if (!capturedFetch) {
    const origin = globalThis.fetch;
    capturedFetch = (input, init) => origin.call(globalThis, input as RequestInfo, init);
  }

  denyGlobalNetwork();
  denyDurableStorage();
  denyServiceWorkers();

  const unrestricted = verifyRestrictions();
  if (unrestricted.length) {
    throw new Error(`[y-demo] refusing to run module code: could not restrict ${unrestricted.join(", ")}`);
  }

  // The loader fetches bundle bytes through this seam, so it keeps working
  // after global fetch is denied — and only for public-bundle URLs.
  publicBundleFetcher.fetch = (url: string) => allowedDemoFetch(url);
  installHostRegistry(buildDemoHostSdk());
  installed = true;
}

export function isPublicDemoRuntimeInstalled(): boolean {
  return installed;
}
