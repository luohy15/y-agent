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

const codexProvider = {
  backend: "codex",
  provider: "openai",
  account_id: "codex-account",
  account_name: "Codex subscription",
  observed_at: "2026-07-10T00:00:00Z",
  source: "codex_usage_api",
  availability: "available",
  freshness: "fresh" as const,
  error: null,
  windows: {
    five_hour: { used_percent: 30, remaining_percent: 70, reset_at: "2026-07-10T02:00:00Z" },
    one_week: { used_percent: 12, remaining_percent: 88, reset_at: "2026-07-15T00:00:00Z" },
  },
  extra_windows: {},
};

const grokProvider = {
  backend: "grok",
  provider: "xai",
  account_id: "grok-account",
  account_name: "Grok subscription",
  observed_at: "2026-07-10T00:00:00Z",
  source: "xai_billing_credits",
  availability: "available",
  freshness: "fresh" as const,
  error: null,
  windows: {
    billing_period: { used_percent: 61, remaining_percent: 39, reset_at: "2026-08-01T00:00:00Z", extra: { monthlyLimit: 40 } },
  },
  extra_windows: {},
};

const reauthProvider = {
  backend: "claude_code",
  provider: "anthropic",
  account_id: "claude-account",
  account_name: "Claude subscription",
  observed_at: null,
  source: "claude_tui_usage",
  availability: "reauth_required",
  freshness: "unavailable" as const,
  error: "reauth_required",
  windows: { five_hour: null, one_week: null },
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

  it("wires retry to a one-shot ?refresh=true fetch, never adding refresh to the poll key", async () => {
    useSWRMock.mockReturnValue(response());
    const refreshedBody = {
      providers: [{ ...provider, windows: { ...provider.windows, five_hour: { used_percent: 5, remaining_percent: 95, reset_at: "2026-07-10T01:00:00Z" } } }],
      errors: [],
      timezone: "Asia/Shanghai",
    };
    const fetchMock = vi.fn(async (_input?: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(refreshedBody), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    const realFetch = window.fetch;
    window.fetch = fetchMock as typeof window.fetch;

    try {
      const { container, root } = renderClient();
      await act(async () => { root.render(React.createElement(UsageLimits)); });

      // The 60s-polled SWR key itself must never carry `refresh` (that would respin
      // the Anthropic TUI scrape on every poll instead of only on explicit retry).
      for (const call of useSWRMock.mock.calls) {
        if (typeof call[0] === "string") expect(call[0]).not.toContain("refresh");
      }

      await act(async () => { (container.querySelector('button[title="Retry subscription status"]') as HTMLButtonElement).click(); });

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const requestedUrl = String(fetchMock.mock.calls[0][0]);
      expect(requestedUrl).toMatch(/\/api\/usage\/limits\?refresh=true$/);

      // The result is seeded into the SWR cache without re-triggering the plain key.
      expect(mutateMock).toHaveBeenCalledTimes(1);
      expect(mutateMock).toHaveBeenCalledWith(refreshedBody, { revalidate: false });

      await act(async () => { root.unmount(); });
    } finally {
      window.fetch = realFetch;
    }
  });

  it("renders three provider cards with provider-specific windows (Grok's billing period, not 5h/1w)", () => {
    useSWRMock.mockReturnValue(response({
      data: { providers: [provider, codexProvider, grokProvider], errors: [], timezone: "Asia/Shanghai" },
    }));

    const html = renderToStaticMarkup(React.createElement(UsageLimits));
    expect(html).toContain("Claude");
    expect(html).toContain("GPT / Codex");
    expect(html).toContain("Grok");
    expect(html).toContain("Billing period");

    const grokSection = html.slice(html.indexOf("Grok"));
    expect(grokSection).not.toContain("5 hours");
    expect(grokSection).not.toContain("1 week");
  });

  it("renders reauth_required as an actionable re-login card, not a raw error code or plain unavailable copy", () => {
    useSWRMock.mockReturnValue(response({
      data: { providers: [reauthProvider], errors: [], timezone: "Asia/Shanghai" },
    }));

    const html = renderToStaticMarkup(React.createElement(UsageLimits));
    expect(html).toContain("Re-login needed");
    expect(html).toContain("claude login");
    expect(html).not.toContain("Usage windows unavailable");
    expect(html).not.toContain(">reauth_required<");
  });

  it("falls back to a generic message for an unmapped error code, never dumping the raw code", () => {
    const unmappedProvider = { ...provider, availability: "unavailable", freshness: "unavailable" as const, error: "some_future_code", windows: { five_hour: null, one_week: null } };
    useSWRMock.mockReturnValue(response({
      data: { providers: [unmappedProvider], errors: [], timezone: "Asia/Shanghai" },
    }));

    const html = renderToStaticMarkup(React.createElement(UsageLimits));
    expect(html).toContain("Usage windows unavailable");
    expect(html).toContain("unexpected error");
    expect(html).not.toContain("some_future_code");
  });

  it("renders a dedicated empty-windows message when an available provider reports no populated window", () => {
    const noWindowsProvider = { ...provider, windows: { five_hour: null, one_week: null } };
    useSWRMock.mockReturnValue(response({
      data: { providers: [noWindowsProvider], errors: [], timezone: "Asia/Shanghai" },
    }));

    const html = renderToStaticMarkup(React.createElement(UsageLimits));
    expect(html).toContain("No usage windows were reported.");
  });

  it("maps vm_unreachable to VM-specific copy rather than the generic unavailable fallback", () => {
    const vmUnreachableProvider = { ...provider, availability: "unavailable", freshness: "unavailable" as const, error: "vm_unreachable", windows: { five_hour: null, one_week: null } };
    useSWRMock.mockReturnValue(response({
      data: { providers: [vmUnreachableProvider], errors: [], timezone: "Asia/Shanghai" },
    }));

    const html = renderToStaticMarkup(React.createElement(UsageLimits));
    expect(html).toContain("VM that reads usage is not reachable");
    expect(html).not.toContain("vm_unreachable<");
  });
});
