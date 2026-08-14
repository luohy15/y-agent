// The four canonical public demo routes (todo 3158 H3,
// docs/prd/public-module-demos.md). This list is an explicit allowlist, not a
// module browser: a visitor may not point the demo shell at an arbitrary
// installed module. The keys must stay in lockstep with
// `PUBLIC_DEMO_SLUGS` in storage/src/storage/service/module.py, which is the
// authority the API gate and the auth middleware share; this copy is only
// what the browser is willing to mount.
export interface DemoRoute {
  key: string;
  // Shown in the demo shell header / document title. Host-side on purpose:
  // the public projection deliberately returns no label.
  title: string;
}

export const DEMO_ROUTES: readonly DemoRoute[] = [
  { key: "chat", title: "Chat" },
  { key: "todo", title: "Todo & Trace" },
  { key: "note", title: "Note" },
  { key: "link", title: "Link" },
];

export const DEMO_PATH_PREFIX = "/demo/";

/** True for every `/demo` path, including unknown keys: main.tsx must hand
 * those to the demo shell's generic not-found state rather than let them fall
 * through to the authenticated app. */
export function isDemoPath(pathname: string): boolean {
  return pathname === "/demo" || pathname.startsWith(DEMO_PATH_PREFIX);
}

/** The allowlisted route for a path, or null. Exact match only — no prefix
 * matching, no trailing-segment tolerance (a trailing slash is rejected). Bare
 * `/demo` is handled by the page shell (defaults to chat) and is not a named
 * route here. */
export function demoRouteFor(pathname: string): DemoRoute | null {
  if (!pathname.startsWith(DEMO_PATH_PREFIX)) return null;
  const key = pathname.slice(DEMO_PATH_PREFIX.length);
  // Exact key only: reject empty (bare prefix) and any slash segment.
  if (!key || key.includes("/")) return null;
  return DEMO_ROUTES.find((route) => route.key === key) ?? null;
}

export function demoPath(key: string): string {
  return `${DEMO_PATH_PREFIX}${key}`;
}
