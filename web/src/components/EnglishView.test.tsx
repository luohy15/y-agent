import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSWRMock, authFetchMock, globalMutateMock } = vi.hoisted(() => ({
  useSWRMock: vi.fn(),
  authFetchMock: vi.fn(),
  globalMutateMock: vi.fn(),
}));

vi.mock("swr", () => ({
  default: useSWRMock,
  useSWRConfig: () => ({ mutate: globalMutateMock }),
}));
vi.mock("../api", () => ({
  API: "http://test",
  jsonFetcher: vi.fn(),
  authFetch: authFetchMock,
}));

import EnglishView from "./EnglishView";

const SAMPLE = {
  correction_id: "corr_a1",
  chat_id: "c1",
  message_id: "m1",
  message_at: "2026-07-27T03:42:00+00:00",
  message_at_unix: Date.now() - 3600_000,
  original_text: "I already finish the draft.",
  corrected_text: "I have already finished the draft.",
  error_categories: ["tense"],
  explanation: "present perfect",
  dismissed: false,
};

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

describe("EnglishView", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useSWRMock.mockReset();
    authFetchMock.mockReset();
    globalMutateMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("dismisses from the detail pane and revalidates detail and English lists", async () => {
    const detailMutateMock = vi.fn().mockResolvedValue(undefined);
    useSWRMock.mockReturnValue({
      data: SAMPLE,
      isLoading: false,
      error: undefined,
      mutate: detailMutateMock,
    });
    authFetchMock.mockResolvedValue({ ok: true });
    globalMutateMock.mockResolvedValue(undefined);

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(EnglishView, { correctionId: "corr_a1" }));
    });

    const dismissButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Dismiss",
    );
    expect(dismissButton).toBeTruthy();
    await act(async () => {
      dismissButton!.click();
    });

    expect(container.textContent).toContain("Dismiss correction?");
    const dismissButtons = Array.from(container.querySelectorAll("button")).filter(
      (button) => button.textContent === "Dismiss",
    );
    expect(dismissButtons).toHaveLength(2);
    await act(async () => {
      dismissButtons[1].click();
    });

    expect(authFetchMock).toHaveBeenCalledWith(
      "http://test/api/english/dismiss",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ correction_id: "corr_a1" }),
      }),
    );
    expect(detailMutateMock).toHaveBeenCalledTimes(1);
    expect(globalMutateMock).toHaveBeenCalledTimes(1);
    const listKeyPredicate = globalMutateMock.mock.calls[0][0] as (key: unknown) => boolean;
    expect(listKeyPredicate("http://test/api/english/detail?correction_id=corr_a1")).toBe(false);
    expect(listKeyPredicate("http://test/api/english/list?limit=500")).toBe(true);

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
