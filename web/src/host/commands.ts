// The artifact -> host command channel (contract v4, plan sub-task S1,
// pages/plan-3006-todo-dynamic-ui.md Part D2 Option A). Mirrors
// `registerArtifactDetailOpener` / `openArtifactDetail` in intents.ts, but for
// a named map of host-side actions rather than a single detail-tab opener.
//
// - `registerHostCommand` is host-internal: only built-in host code (App.tsx)
//   may wire a command name to a handler. It is deliberately NOT exported
//   through `@y/host`, same partition as `setArtifactIntent` /
//   `registerArtifactDetailOpener`.
// - `runHostCommand` is the artifact-facing side, published on hostSdk. An
//   unregistered name is a silent no-op: an artifact typo must not crash the
//   host (plan S1 verify).
//
// Security note (plan D2): any artifact can invoke any registered name, exactly
// like `openArtifactDetail(slug)` is invocable for any slug today. The host
// still decides which commands exist.

type HostCommandHandler = (payload?: unknown) => void;

const commands = new Map<string, HostCommandHandler>();

/** Host-internal registration. App.tsx wires the concrete host gestures
 * (`todo.open`, `todo.openTrace`, `chat.open`, `chat.setTraceFilter`, …).
 * Returns an unregister function that only clears the slot if it still points
 * at the same handler (so a later re-register is not clobbered by an earlier
 * cleanup). */
export function registerHostCommand(name: string, handler: HostCommandHandler): () => void {
  commands.set(name, handler);
  return () => {
    if (commands.get(name) === handler) commands.delete(name);
  };
}

/** Ask the host to run a named command. Silent no-op when no handler is
 * registered for `name`. */
export function runHostCommand(name: string, payload?: unknown): void {
  commands.get(name)?.(payload);
}
