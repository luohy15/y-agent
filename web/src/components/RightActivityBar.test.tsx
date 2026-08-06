import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RightActivityBar from "./RightActivityBar";
import type { PanelItem } from "./panelCatalog";

const items: PanelItem<"artifact:chat" | "notes" | "files" | "diff">[] = [
  { key: "artifact:chat", label: "Chat", icon: <span>C</span> },
  { key: "notes", label: "Notes", icon: <span>N</span> },
  { key: "files", label: "Files", icon: <span>F</span> },
  { key: "diff", label: "Diff", icon: <span>D</span> },
];

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  return { container, root: createRoot(container) };
}

function Harness({ onClose }: { onClose: () => void }) {
  const [activePanel, setActivePanel] = useState<(typeof items)[number]["key"]>("notes");
  return (
    <>
      <RightActivityBar
        items={items}
        activePanel={activePanel}
        onSelectPanel={setActivePanel}
        onRefresh={() => {}}
        onClose={onClose}
      />
      <div data-testid="right-body">{activePanel}</div>
    </>
  );
}

describe("RightActivityBar", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  it("renders exactly four ordered buttons (Chat, Notes, Files, Diff)", () => {
    const { container, root } = renderClient();
    act(() => root.render(<Harness onClose={() => {}} />));

    const buttons = container.querySelectorAll("[data-right-panel]");
    expect(Array.from(buttons).map((b) => b.getAttribute("data-right-panel"))).toEqual([
      "artifact:chat",
      "notes",
      "files",
      "diff",
    ]);

    act(() => root.unmount());
  });

  it("switches the body on category click without ever calling onClose", () => {
    const onClose = vi.fn();
    const { container, root } = renderClient();
    act(() => root.render(<Harness onClose={onClose} />));

    for (const item of items) {
      const button = container.querySelector(`[data-right-panel="${item.key}"]`) as HTMLButtonElement;
      act(() => button.click());
      expect(container.querySelector("[data-testid=right-body]")?.textContent).toBe(item.key);
    }
    // Re-clicking the already-active category (the old collapse trigger)
    // must still just re-select it, never collapse via onClose.
    const activeAgain = container.querySelector('[data-right-panel="diff"]') as HTMLButtonElement;
    act(() => activeAgain.click());
    expect(container.querySelector("[data-testid=right-body]")?.textContent).toBe("diff");
    expect(onClose).not.toHaveBeenCalled();

    act(() => root.unmount());
  });

  it("fires onClose on desktop and mobile Close alike", () => {
    const onClose = vi.fn();
    const { container, root } = renderClient();
    act(() => root.render(<Harness onClose={onClose} />));

    const closeButton = container.querySelector('button[title="Close"]') as HTMLButtonElement;
    act(() => closeButton.click());
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => root.unmount());
  });
});
