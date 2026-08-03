import { afterEach, describe, expect, it, vi } from "vitest";
import { registerHostCommand, runHostCommand } from "./commands";

describe("host commands", () => {
  // Each test registers under a unique name and unregisters in afterEach so
  // the module-level map stays clean across the suite.
  const cleanups: Array<() => void> = [];

  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
  });

  it("invokes a registered command with its payload", () => {
    const name = `todo.open-${Math.random()}`;
    const handler = vi.fn();
    cleanups.push(registerHostCommand(name, handler));

    const payload = { todoId: "3006" };
    runHostCommand(name, payload);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(payload);
  });

  it("runHostCommand on an unregistered name is a silent no-op (does not throw)", () => {
    expect(() => runHostCommand(`missing-${Math.random()}`, { x: 1 })).not.toThrow();
  });

  it("unregister stops further invocations; a later re-register is not clobbered by an earlier cleanup", () => {
    const name = `chat.refreshList-${Math.random()}`;
    const first = vi.fn();
    const second = vi.fn();

    const unregisterFirst = registerHostCommand(name, first);
    // Re-register before the first cleanup runs (the pattern App.tsx's effect
    // cleanup uses when deps change).
    cleanups.push(registerHostCommand(name, second));
    unregisterFirst();

    runHostCommand(name, { n: 1 });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledWith({ n: 1 });
  });
});
