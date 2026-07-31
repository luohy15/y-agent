import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { openArtifactDetail, registerArtifactDetailOpener, setArtifactIntent, useArtifactIntent } from "./intents";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function IntentProbe({ slug }: { slug: string }) {
  const intent = useArtifactIntent<{ date: string }>(slug);
  return React.createElement("div", null, intent ? intent.date : "none");
}

describe("intents", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  // The failure mode the whole design exists to prevent (plan Part D3): a
  // plain CustomEvent would be dispatched before this component's effect ever
  // subscribes, silently losing the first focus. The retained store must
  // deliver it anyway, on first render.
  it("latches: an intent set before a subscriber mounts is still delivered on first read", () => {
    const slug = `latch-${Math.random()}`;
    setArtifactIntent(slug, { date: "2026-07-31" });

    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(IntentProbe, { slug }));
    });

    expect(container.textContent).toBe("2026-07-31");
    root.unmount();
  });

  it("delivers subsequent updates to an already-mounted subscriber", () => {
    const slug = `latch-update-${Math.random()}`;
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(IntentProbe, { slug }));
    });
    expect(container.textContent).toBe("none");

    act(() => {
      setArtifactIntent(slug, { date: "2026-08-01" });
    });
    expect(container.textContent).toBe("2026-08-01");
    root.unmount();
  });

  it("openArtifactDetail defers to the registered opener and no-ops when none is registered", () => {
    const slug = `open-${Math.random()}`;
    expect(() => openArtifactDetail(slug)).not.toThrow();

    const calls: string[] = [];
    const unregister = registerArtifactDetailOpener((s) => calls.push(s));
    openArtifactDetail(slug);
    expect(calls).toEqual([slug]);

    unregister();
    openArtifactDetail(slug);
    expect(calls).toEqual([slug]);
  });
});
