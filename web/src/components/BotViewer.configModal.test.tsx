import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSWRMock, mutateMock, apiJsonMock } = vi.hoisted(() => ({
  useSWRMock: vi.fn(),
  mutateMock: vi.fn(),
  apiJsonMock: vi.fn(() => Promise.resolve({})),
}));

vi.mock("swr", () => ({
  default: useSWRMock,
  useSWRConfig: () => ({ mutate: mutateMock }),
}));

vi.mock("./BotList", async () => {
  const actual = await vi.importActual<typeof import("./BotList")>("./BotList");
  return {
    ...actual,
    apiJson: apiJsonMock,
  };
});

import BotViewer from "./BotViewer";

const bots = [
  {
    name: "alpha",
    backend: "claude_code",
    model: "claude-sonnet",
    type: "agent",
    tier: "tier1",
    route_weight: 1,
    price_input: 3,
    price_output: 15,
    enabled: true,
  },
  {
    name: "beta",
    backend: "codex",
    model: "gpt-5",
    type: "agent",
    tier: "tier2",
    route_weight: 2,
    price_input: 5,
    price_output: 20,
    enabled: false,
  },
];

function mockSWR() {
  useSWRMock.mockImplementation((key: string | null) => {
    if (typeof key === "string" && key.includes("/api/bot/list")) {
      return { data: bots, isLoading: false, error: undefined, mutate: mutateMock };
    }
    if (typeof key === "string" && key.includes("/api/bot/config")) {
      const name = new URL(key, "http://local").searchParams.get("name") || bots[0].name;
      const bot = bots.find((b) => b.name === name) || bots[0];
      return { data: bot, isLoading: false, error: undefined, mutate: mutateMock };
    }
    if (typeof key === "string" && key.includes("/api/usage/model-daily")) {
      return { data: [], isLoading: false, error: undefined, mutate: mutateMock };
    }
    return { data: undefined, isLoading: false, error: undefined, mutate: mutateMock };
  });
}

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function openAlphaRow(container: HTMLElement) {
  const row = Array.from(container.querySelectorAll("tbody tr")).find((tr) =>
    tr.textContent?.includes("alpha"),
  ) as HTMLTableRowElement | undefined;
  expect(row).toBeTruthy();
  act(() => {
    row!.click();
  });
  return row!;
}

describe("BotViewer Config detail modal", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useSWRMock.mockReset();
    mutateMock.mockReset();
    apiJsonMock.mockReset();
    apiJsonMock.mockResolvedValue({});
    localStorage.clear();
    mockSWR();
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  it("opens one dialog from a config row and keeps one table row per bot", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });

    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    openAlphaRow(container);

    const dialogs = container.querySelectorAll('[role="dialog"]');
    expect(dialogs).toHaveLength(1);
    expect(dialogs[0].getAttribute("aria-modal")).toBe("true");
    expect(dialogs[0].getAttribute("aria-labelledby")).toBe("bot-detail-title");
    expect(container.querySelector("#bot-detail-title")?.textContent).toBe("alpha");
    // Table stays one row per bot (no expanded detail <tr>).
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);

    await act(async () => {
      root.unmount();
    });
  });

  it("does not dismiss when clicking inside the dialog", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });
    openAlphaRow(container);

    const dialog = container.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog).toBeTruthy();
    await act(async () => {
      dialog.click();
    });
    expect(container.querySelector('[role="dialog"]')).toBeTruthy();

    await act(async () => {
      root.unmount();
    });
  });

  it("closes via the close button", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });
    openAlphaRow(container);

    const closeBtn = container.querySelector('[role="dialog"] button[title="Close"]') as HTMLButtonElement;
    expect(closeBtn).toBeTruthy();
    await act(async () => {
      closeBtn.click();
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    await act(async () => {
      root.unmount();
    });
  });

  it("closes via backdrop click", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });
    openAlphaRow(container);

    const dialog = container.querySelector('[role="dialog"]') as HTMLElement;
    const backdrop = dialog.parentElement as HTMLElement;
    expect(backdrop.className).toContain("fixed");
    await act(async () => {
      backdrop.click();
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    await act(async () => {
      root.unmount();
    });
  });

  it("closes via Escape", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });
    openAlphaRow(container);
    expect(container.querySelector('[role="dialog"]')).toBeTruthy();

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    await act(async () => {
      root.unmount();
    });
  });

  it("status-dot toggle does not open the dialog", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });

    const betaRow = Array.from(container.querySelectorAll("tbody tr")).find((tr) =>
      tr.textContent?.includes("beta"),
    ) as HTMLTableRowElement;
    const dot = betaRow.querySelector("button") as HTMLButtonElement;
    expect(dot).toBeTruthy();
    expect(dot.title.toLowerCase()).toContain("disabled");

    await act(async () => {
      dot.click();
    });

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(apiJsonMock).toHaveBeenCalledWith("/api/bot/enable", { name: "beta" });
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);

    await act(async () => {
      root.unmount();
    });
  });

  it("cold-open seeds detail-only fields from the config endpoint, not the list", async () => {
    // List row omits detail-only fields (mirrors /api/bot/list's payload shape).
    const listBot = { name: "alpha", backend: "claude_code", model: "claude-sonnet", type: "agent", tier: "tier1", price_input: 3, price_output: 15, enabled: true };
    const configBot = { ...listBot, max_tokens: 4096, custom_api_path: "/v1/custom", route_weight: 3 };
    const configMutateMock = vi.fn();
    let configLoaded = false;
    useSWRMock.mockImplementation((key: string | null) => {
      if (typeof key === "string" && key.includes("/api/bot/list")) {
        return { data: [listBot], isLoading: false, error: undefined, mutate: mutateMock };
      }
      if (typeof key === "string" && key.includes("/api/bot/config")) {
        return { data: configLoaded ? configBot : undefined, isLoading: !configLoaded, error: undefined, mutate: configMutateMock };
      }
      return { data: undefined, isLoading: false, error: undefined, mutate: mutateMock };
    });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });
    openAlphaRow(container);

    // Cold: config fetch not yet resolved, form must not seed from the list fallback.
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("Loading");
    expect(container.querySelector('[role="dialog"] input[type="number"][step="any"]')).toBeNull();

    // Config resolves; force a re-render so the SWR mock's new return value is picked up.
    configLoaded = true;
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });

    const dialog = container.querySelector('[role="dialog"]') as HTMLElement;
    const maxTokensInput = Array.from(dialog.querySelectorAll("input")).find(
      (i) => i.getAttribute("type") === "number" && i.getAttribute("min") === "1",
    ) as HTMLInputElement;
    const weightInput = dialog.querySelector('input[step="any"]') as HTMLInputElement;
    const apiPathInput = Array.from(dialog.querySelectorAll("input")).find(
      (i) => i.getAttribute("placeholder") === "/chat/completions",
    ) as HTMLInputElement;
    expect(maxTokensInput.value).toBe("4096");
    expect(apiPathInput.value).toBe("/v1/custom");
    expect(weightInput.value).toBe("3");

    await act(async () => {
      root.unmount();
    });
  });

  it("invalidates the config detail cache on save so a reopen would show the new weight", async () => {
    const configMutateMock = vi.fn();
    useSWRMock.mockImplementation((key: string | null) => {
      if (typeof key === "string" && key.includes("/api/bot/list")) {
        return { data: bots, isLoading: false, error: undefined, mutate: mutateMock };
      }
      if (typeof key === "string" && key.includes("/api/bot/config")) {
        const name = new URL(key, "http://local").searchParams.get("name") || bots[0].name;
        const bot = bots.find((b) => b.name === name) || bots[0];
        return { data: bot, isLoading: false, error: undefined, mutate: configMutateMock };
      }
      if (typeof key === "string" && key.includes("/api/usage/model-daily")) {
        return { data: [], isLoading: false, error: undefined, mutate: mutateMock };
      }
      return { data: undefined, isLoading: false, error: undefined, mutate: mutateMock };
    });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(BotViewer));
    });
    openAlphaRow(container);

    const dialog = container.querySelector('[role="dialog"]') as HTMLElement;
    const weightInput = dialog.querySelector('input[step="any"]') as HTMLInputElement;
    expect(weightInput.value).toBe("1");

    await act(async () => {
      weightInput.dispatchEvent(new Event("focusin", { bubbles: true }));
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
      setter.call(weightInput, "5");
      weightInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const saveBtn = Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "Save") as HTMLButtonElement;
    expect(saveBtn).toBeTruthy();
    await act(async () => {
      saveBtn.click();
      await Promise.resolve();
    });

    expect(apiJsonMock).toHaveBeenCalledWith("/api/bot/update", expect.objectContaining({ name: "alpha", route_weight: 5 }));
    // Defect 2 regression guard: the config detail SWR key must be invalidated on save,
    // not just the list key, or a warm reopen would keep serving the pre-save weight.
    expect(configMutateMock).toHaveBeenCalled();

    await act(async () => {
      root.unmount();
    });
  });
});
