import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSWRMock } = vi.hoisted(() => ({
  useSWRMock: vi.fn(),
}));

vi.mock("swr", () => ({ default: useSWRMock }));
vi.mock("../api", () => ({
  API: "http://test",
  jsonFetcher: vi.fn(),
}));

import EnglishList from "./EnglishList";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

const SAMPLE = [
  {
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
  },
  {
    correction_id: "corr_b2",
    chat_id: "c1",
    message_id: "m2",
    message_at: "2026-07-26T10:00:00+00:00",
    message_at_unix: Date.now() - 86400_000,
    original_text: "Please check a attached log.",
    corrected_text: "Please check the attached log.",
    error_categories: ["article"],
    explanation: "article",
    dismissed: false,
  },
];

function mockSWR(listData: unknown, routines: unknown = []) {
  useSWRMock.mockImplementation((key: string | null) => {
    if (typeof key === "string" && key.includes("/api/english/list")) {
      return {
        data: listData,
        isLoading: false,
        isValidating: false,
        error: undefined,
        mutate: vi.fn().mockResolvedValue(undefined),
      };
    }
    if (typeof key === "string" && key.includes("/api/routine/list")) {
      return {
        data: routines,
        isLoading: false,
        isValidating: false,
        error: undefined,
        mutate: vi.fn(),
      };
    }
    return { data: undefined, isLoading: false, isValidating: false, error: undefined, mutate: vi.fn() };
  });
}

describe("EnglishList", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useSWRMock.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders rows from a mocked SWR payload", () => {
    mockSWR(SAMPLE);
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(EnglishList, { isLoggedIn: true }));
    });
    expect(container.textContent).toContain("I already finish the draft.");
    expect(container.textContent).toContain("Please check a attached log.");
    expect(container.textContent).toContain("tense");
    expect(container.textContent).toContain("article");
    act(() => root.unmount());
    container.remove();
  });

  it("renders empty state with []", () => {
    mockSWR([]);
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(EnglishList, { isLoggedIn: true }));
    });
    expect(container.textContent).toContain("No corrections yet");
    act(() => root.unmount());
    container.remove();
  });

  it("clicking a row calls onSelectCorrection", () => {
    mockSWR(SAMPLE);
    const onSelect = vi.fn();
    const { container, root } = renderClient();
    act(() => {
      root.render(
        React.createElement(EnglishList, {
          isLoggedIn: true,
          onSelectCorrection: onSelect,
        }),
      );
    });
    const btn = Array.from(container.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("I already finish"),
    );
    expect(btn).toBeTruthy();
    act(() => {
      btn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onSelect).toHaveBeenCalledWith("corr_a1");
    act(() => root.unmount());
    container.remove();
  });
});
