import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSWRMock, mutateMock } = vi.hoisted(() => ({
  useSWRMock: vi.fn(),
  mutateMock: vi.fn(),
}));

vi.mock("swr", () => ({
  default: useSWRMock,
  useSWRConfig: () => ({ mutate: vi.fn() }),
}));

import { UsageLimits, formatResetTime } from "./BotViewer";

const provider = {
  backend: "claude_code",
  provider: "anthropic",
  account_id: "claude-account",
  account_name: "Claude subscription",
  observed_at: "2026-07-10T00:00:00Z",
  source: "anthropic_oauth_usage",
  availability: "available",
  freshness: "fresh" as const,
  error: null,
  windows: {
    five_hour: { used_percent: 42, remaining_percent: 58, reset_at: "2026-07-10T00:00:00Z" },
    one_week: { used_percent: 18, remaining_percent: 82, reset_at: "2026-07-14T00:00:00Z" },
  },
  extra_windows: {},
};

function response(overrides: Record<string, unknown> = {}) {
  return {
    data: { providers: [provider], errors: [], timezone: "Asia/Shanghai" },
    error: undefined,
    isLoading: false,
    mutate: mutateMock,
    ...overrides,
  };
}

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

describe("UsageLimits", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useSWRMock.mockReset();
    mutateMock.mockReset();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  });

  afterEach(() => {
    document.body.replaceChildren();
  });

  it("formats absolute reset timestamps in the configured timezone", () => {
    const formatted = formatResetTime("2026-07-10T00:00:00Z", "Asia/Shanghai");
    expect(formatted).toMatch(/08:00/);
  });

  it("retains provider data while a refetch error marks it stale and partial", () => {
    useSWRMock.mockReturnValue(response({
      data: { providers: [provider], errors: [{ origin: "https://relay.example", error: "timeout" }], timezone: "Asia/Shanghai" },
      error: new Error("network failed"),
    }));

    const html = renderToStaticMarkup(React.createElement(UsageLimits));
    expect(html).toContain("Claude");
    expect(html).toContain("partial read");
    expect(html).toContain("last read failed");
    expect(html).toContain(">stale<");
  });

  it("suspends the SWR key while hidden and resumes it when visible", async () => {
    useSWRMock.mockReturnValue(response());
    const { root } = renderClient();
    await act(async () => { root.render(React.createElement(UsageLimits)); });
    expect(useSWRMock.mock.calls.at(-1)?.[0]).toMatch(/\/api\/usage\/limits$/);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(useSWRMock.mock.calls.at(-1)?.[0]).toBeNull();

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(useSWRMock.mock.calls.at(-1)?.[0]).toMatch(/\/api\/usage\/limits$/);
    await act(async () => { root.unmount(); });
  });

  it("retries only the limit-status SWR request", async () => {
    useSWRMock.mockReturnValue(response());
    const { container, root } = renderClient();
    await act(async () => { root.render(React.createElement(UsageLimits)); });
    await act(async () => { (container.querySelector('button[title="Retry subscription status"]') as HTMLButtonElement).click(); });
    expect(mutateMock).toHaveBeenCalledTimes(1);
    await act(async () => { root.unmount(); });
  });
});
