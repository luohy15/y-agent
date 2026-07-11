import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock("swr", () => ({ default: useSWRMock }));

import NoteList from "./NoteList";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

// NoteList fires several useSWR calls (journals/pages/blog/finance/skills tabs
// plus the todo-scoped notes list); only the `/api/note/list` key matters for
// these tests, everything else should behave like an unfetched (null-key) hook.
function mockUseSWRForTodoNotes(todoNotesData: unknown) {
  useSWRMock.mockImplementation((key: string | null) => {
    if (typeof key === "string" && key.includes("/api/note/list")) {
      return { data: todoNotesData, isLoading: false, error: undefined, mutate: vi.fn() };
    }
    return { data: undefined, isLoading: false, error: undefined, mutate: vi.fn() };
  });
}

describe("NoteList todo mode", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useSWRMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Regression test for the incident: GET /api/note/list?todo_id= is always an
  // array server-side, but a stale/malformed localStorage-persisted SWR cache
  // entry can seed `data` with a truthy non-array value on first paint (see
  // pages/plan-2767-notelist-map-crash.md). This mocks that exact shape and
  // reproduces the original crash site (NoteList.tsx, `todoNotes.map`) verbatim
  // before the Array.isArray guard, then confirms the fix renders the empty
  // state instead of throwing.
  it("renders empty state instead of throwing when todoNotes is a non-array truthy value", () => {
    mockUseSWRForTodoNotes({ detail: "some error shape" });

    const { container, root } = renderClient();
    expect(() => {
      act(() => {
        root.render(
          React.createElement(NoteList, {
            isLoggedIn: true,
            todoId: "2767",
            hideFilters: true,
            onOpenFile: () => {},
          }),
        );
      });
    }).not.toThrow();

    expect(container.textContent).toContain("No notes found");

    act(() => root.unmount());
    container.remove();
  });

  it("renders the note list when todoNotes is a well-formed array", () => {
    mockUseSWRForTodoNotes([{ note_id: "n1", content_key: "pages/example.md" }]);

    const { container, root } = renderClient();
    act(() => {
      root.render(
        React.createElement(NoteList, {
          isLoggedIn: true,
          todoId: "2767",
          hideFilters: true,
          onOpenFile: () => {},
        }),
      );
    });

    expect(container.textContent).toContain("example");

    act(() => root.unmount());
    container.remove();
  });
});
