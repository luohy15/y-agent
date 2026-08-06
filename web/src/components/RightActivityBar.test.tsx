import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import RightActivityBar from "./RightActivityBar";
import type { PanelItem } from "./panelCatalog";

const items: PanelItem<"notes" | "links" | "files" | "diff" | "artifact:fake">[] = [
  { key: "notes", label: "Notes", icon: <span>N</span> },
  { key: "links", label: "Links", icon: <span>L</span> },
  { key: "files", label: "Files", icon: <span>F</span> },
  { key: "diff", label: "Diff", icon: <span>D</span> },
  { key: "artifact:fake", label: "Fake", icon: <span>A</span> },
];

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  return { container, root: createRoot(container) };
}

function MobileHarness() {
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [activePanel, setActivePanel] = useState<(typeof items)[number]["key"]>("notes");
  return drawerOpen ? (
    <div data-testid="drawer">
      <RightActivityBar mobile items={items} activePanel={activePanel} contentOpen onSelectPanel={setActivePanel} />
      <button onClick={() => setDrawerOpen(false)}>Navigate</button>
    </div>
  ) : null;
}

function DesktopHarness() {
  const [activePanel, setActivePanel] = useState<(typeof items)[number]["key"]>("notes");
  const [contentOpen, setContentOpen] = useState(true);
  return <>
    <RightActivityBar
      items={items}
      activePanel={activePanel}
      contentOpen={contentOpen}
      onSelectPanel={(panel) => {
        if (contentOpen && panel === activePanel) setContentOpen(false);
        else { setActivePanel(panel); setContentOpen(true); }
      }}
    />
    {contentOpen && <div data-testid="right-body">{activePanel}</div>}
  </>;
}

describe("RightActivityBar", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  it("selects each built-in and module body, then collapses without removing the rail", () => {
    const { container, root } = renderClient();
    act(() => root.render(<DesktopHarness />));

    for (const item of items) {
      const button = () => container.querySelector(`[data-right-panel="${item.key}"]`) as HTMLButtonElement;
      act(() => button().click());
      if (!container.querySelector("[data-testid=right-body]")) act(() => button().click());
      expect(container.querySelector("[data-testid=right-body]")?.textContent).toBe(item.key);
      expect(container.querySelectorAll("[data-right-panel]")).toHaveLength(items.length);
    }

    act(() => (container.querySelector('[data-right-panel="artifact:fake"]') as HTMLButtonElement).click());
    expect(container.querySelector("[data-testid=right-body]")).toBeNull();
    expect(container.querySelectorAll("[data-right-panel]")).toHaveLength(items.length);
    act(() => root.unmount());
  });

  it("keeps the mobile drawer open for category switches and closes only on navigation", () => {
    const { container, root } = renderClient();
    act(() => root.render(<MobileHarness />));

    act(() => (container.querySelector('[data-right-panel="artifact:fake"]') as HTMLButtonElement).click());
    expect(container.querySelector("[data-testid=drawer]")).toBeTruthy();
    act(() => (Array.from(container.querySelectorAll("button")).find((button) => button.textContent === "Navigate") as HTMLButtonElement).click());
    expect(container.querySelector("[data-testid=drawer]")).toBeNull();
    act(() => root.unmount());
  });
});
