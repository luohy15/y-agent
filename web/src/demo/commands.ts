// In-memory host-command channel for the public demo shell (todo 3158 H8).
//
// Production modules invoke `runHostCommand` / `openArtifactDetail` through
// @y/host. On a demo page those calls must drive only the shell's ephemeral
// state. This is intentionally a separate registry from host/commands.ts:
// installing the restricted SDK must never expose an authenticated App handler.

type DemoHostCommandHandler = (payload?: unknown) => void;
type DemoDetailOpener = (slug: string) => void;

export const DEMO_HOST_COMMANDS = [
  "chat.open",
  "todo.open",
  "todo.openTrace",
  "file.open",
  "chat.setTraceFilter",
  "demo.blocked",
] as const;

export type DemoHostCommandName = (typeof DEMO_HOST_COMMANDS)[number];

const handlers = new Map<DemoHostCommandName, DemoHostCommandHandler>();
let detailOpener: DemoDetailOpener | null = null;

function isDemoHostCommand(name: string): name is DemoHostCommandName {
  return (DEMO_HOST_COMMANDS as readonly string[]).includes(name);
}

/** Register a shell-local command handler. Unknown command names are rejected
 * at registration time; calls to an unregistered command stay silent no-ops. */
export function registerDemoHostCommand(name: DemoHostCommandName, handler: DemoHostCommandHandler): () => void {
  handlers.set(name, handler);
  return () => {
    if (handlers.get(name) === handler) handlers.delete(name);
  };
}

/** Artifact-facing command endpoint installed into the restricted @y/host SDK. */
export function runDemoHostCommand(name: string, payload?: unknown): void {
  if (isDemoHostCommand(name)) handlers.get(name)?.(payload);
}

/** `file.open` in a demo has no VM or work-dir capability. Fixtures provide
 * their display path and markdown body directly to the shell. */
export function demoFileOpenPayload(payload: unknown): { path: string; content: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const { path, content } = payload as { path?: unknown; content?: unknown };
  return typeof path === "string" && path.length > 0 && typeof content === "string" ? { path, content } : null;
}

/** Host-internal detail-tab registration for the current demo shell. */
export function registerDemoArtifactDetailOpener(opener: DemoDetailOpener): () => void {
  detailOpener = opener;
  return () => {
    if (detailOpener === opener) detailOpener = null;
  };
}

/** Artifact-facing detail opener installed into the restricted @y/host SDK. */
export function openDemoArtifactDetail(slug: string): void {
  detailOpener?.(slug);
}
