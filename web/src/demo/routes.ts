// The four showcase module keys (todo 3158 H3,
// docs/prd/public-module-demos.md). They are an explicit allowlist for the
// shell's public bundle lookups, not browser routes: `/demo` is the sole
// supported public demo route. The keys must stay in lockstep with
// `PUBLIC_DEMO_SLUGS` in storage/src/storage/service/module.py, which is the
// authority the API gate and the auth middleware share.
export interface DemoModule {
  key: string;
}

export const DEMO_MODULES: readonly DemoModule[] = [
  { key: "chat" },
  { key: "todo" },
  { key: "note" },
  { key: "link" },
];

/** The public demo application has one canonical browser route. */
export function isDemoPath(pathname: string): boolean {
  return pathname === "/demo";
}
