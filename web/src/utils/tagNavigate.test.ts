import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { authFetchMock, setArtifactIntentMock } = vi.hoisted(() => ({ authFetchMock: vi.fn(), setArtifactIntentMock: vi.fn() }));
vi.mock("../api", () => ({ API: "", authFetch: authFetchMock }));
vi.mock("../host/intents", () => ({ setArtifactIntent: setArtifactIntentMock }));

import { navigateTag, openTodo, type TagNavigateDeps } from "./tagNavigate";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function makeDeps(): TagNavigateDeps {
  return {
    requestSelectTraceId: vi.fn(),
    setChatListTraceId: vi.fn(),
    setSelectedChatId: vi.fn(),
    setChatHide: vi.fn(),
    handleOpenFile: vi.fn(),
    handlePreviewFile: vi.fn(),
    defaultWorkDir: "/workspace/project",
    setSelectedEntityId: vi.fn(),
    setSelectedLinkId: vi.fn(),
    setSelectedLinkLinkId: vi.fn(),
    setSelectedLinkContentKey: vi.fn(),
    handleSelectFeed: vi.fn(),
    setSelectedThreadId: vi.fn(),
    setSelectedThreadAccount: vi.fn(),
    setSidebarPanel: vi.fn(),
  };
}

// Poll until async authFetch callbacks settle. A fixed microtask-tick spin
// (old flush) is enough on a fast local machine but starves on slower/loaded
// CI runners, so assertions fire with "Number of calls: 0". vi.waitFor keeps
// the same contract checks timing-robust rather than tick-count-dependent.
async function waitForCall(fn: { mock: { calls: unknown[][] } }) {
  await vi.waitFor(() => {
    expect(fn.mock.calls.length).toBeGreaterThan(0);
  });
}

describe("navigateTag / openTodo (Tags panel 10-way dispatch)", () => {
  beforeEach(() => {
    authFetchMock.mockReset();
    setArtifactIntentMock.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("todo: selects the trace and lands on the latest chat when one exists", async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ chat_id: "chat-abc" }));
    const deps = makeDeps();
    navigateTag("todo", { id: "2854", title: "Frontend tag management" }, deps);

    expect(deps.requestSelectTraceId).toHaveBeenCalledWith("2854");
    expect(deps.setChatListTraceId).toHaveBeenCalledWith("2854");
    expect(authFetchMock).toHaveBeenCalledWith("/api/trace/latest_chat?trace_id=2854");
    await waitForCall(deps.setSelectedChatId as ReturnType<typeof vi.fn>);
    expect(deps.setSelectedChatId).toHaveBeenCalledWith("chat-abc");
    expect(deps.setChatHide).toHaveBeenCalledWith(false);
    expect(deps.handleOpenFile).not.toHaveBeenCalled();
  });

  it("todo: falls back to trace.md when the todo has no chat yet", async () => {
    authFetchMock.mockResolvedValue(jsonResponse({}));
    const deps = makeDeps();
    openTodo("2838", deps);
    await waitForCall(deps.handleOpenFile as ReturnType<typeof vi.fn>);

    expect(deps.handleOpenFile).toHaveBeenCalledWith("trace.md");
    expect(deps.setSelectedChatId).not.toHaveBeenCalled();
  });

  it("note: previews the file at workDir + content_key (title)", () => {
    const deps = makeDeps();
    navigateTag("note", { id: "n1", title: "pages/plan-2854-tag-management-ui.md" }, deps);
    expect(deps.handlePreviewFile).toHaveBeenCalledWith("/workspace/project/pages/plan-2854-tag-management-ui.md");
  });

  it("chat: selects the chat and shows the chat view", () => {
    const deps = makeDeps();
    navigateTag("chat", { id: "b92b8112", title: "design tag panel" }, deps);
    expect(deps.setSelectedChatId).toHaveBeenCalledWith("b92b8112");
    expect(deps.setChatHide).toHaveBeenCalledWith(false);
  });

  it("entity: selects the entity and opens entity.md", () => {
    const deps = makeDeps();
    navigateTag("entity", { id: "e-y-agent", title: "y-agent" }, deps);
    expect(deps.setSelectedEntityId).toHaveBeenCalledWith("e-y-agent");
    expect(deps.handleOpenFile).toHaveBeenCalledWith("entity.md");
  });

  it("link: selects the link by activity_id, clears the legacy link_id/content_key, opens link.md", () => {
    const deps = makeDeps();
    navigateTag("link", { id: "activity-1", title: "TailwindCSS v4 docs" }, deps);
    expect(deps.setSelectedLinkId).toHaveBeenCalledWith("activity-1");
    expect(deps.setSelectedLinkLinkId).toHaveBeenCalledWith(null);
    expect(deps.setSelectedLinkContentKey).toHaveBeenCalledWith(null);
    expect(deps.handleOpenFile).toHaveBeenCalledWith("link.md");
  });

  it("rss_feed: opens the existing feed-links view with id + title", () => {
    const deps = makeDeps();
    navigateTag("rss_feed", { id: "rf-1", title: "y-agent releases" }, deps);
    expect(deps.handleSelectFeed).toHaveBeenCalledWith("rf-1", "y-agent releases");
  });

  it("rss_feed: falls back to the id as the label when title is missing", () => {
    const deps = makeDeps();
    navigateTag("rss_feed", { id: "rf-2" }, deps);
    expect(deps.handleSelectFeed).toHaveBeenCalledWith("rf-2", "rf-2");
  });

  it("calendar_event: fetches start_time and focuses the calendar artifact", async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ event_id: "ev-1", start_time: "2026-07-27T10:00:00Z" }));
    const deps = makeDeps();
    navigateTag("calendar_event", { id: "ev-1", title: "y-agent tag review" }, deps);

    expect(authFetchMock).toHaveBeenCalledWith("/api/calendar/detail?event_id=ev-1");
    await waitForCall(deps.handleOpenFile as ReturnType<typeof vi.fn>);
    expect(setArtifactIntentMock).toHaveBeenCalledWith("calendar", expect.objectContaining({ kind: "focus-date", date: "2026-07-27T10:00:00Z" }));
    expect(deps.handleOpenFile).toHaveBeenCalledWith("ui:calendar");
    expect(deps.setSidebarPanel).not.toHaveBeenCalled();
  });

  it("calendar_event: falls back to the Calendar panel when start_time is missing", async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ event_id: "ev-2" }));
    const deps = makeDeps();
    navigateTag("calendar_event", { id: "ev-2" }, deps);
    await waitForCall(deps.setSidebarPanel as ReturnType<typeof vi.fn>);

    expect(setArtifactIntentMock).not.toHaveBeenCalled();
    expect(deps.setSidebarPanel).toHaveBeenCalledWith("artifact:calendar");
  });

  it("calendar_event: falls back to the Calendar panel on a failed detail fetch (e.g. 404)", async () => {
    authFetchMock.mockRejectedValue(new Error("Event not found"));
    const deps = makeDeps();
    navigateTag("calendar_event", { id: "ev-deleted" }, deps);
    await waitForCall(deps.setSidebarPanel as ReturnType<typeof vi.fn>);

    expect(deps.setSidebarPanel).toHaveBeenCalledWith("artifact:calendar");
    expect(deps.handleOpenFile).not.toHaveBeenCalled();
  });

  it("email: fetches thread_id + account and opens email.md", async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ email_id: "em-1", thread_id: "th-1", account: "roy@example.com" }));
    const deps = makeDeps();
    navigateTag("email", { id: "em-1", title: "Re: tag system design review" }, deps);

    expect(authFetchMock).toHaveBeenCalledWith("/api/email/em-1");
    await waitForCall(deps.setSelectedThreadId as ReturnType<typeof vi.fn>);
    expect(deps.setSelectedThreadId).toHaveBeenCalledWith("th-1");
    expect(deps.setSelectedThreadAccount).toHaveBeenCalledWith("roy@example.com");
    expect(deps.handleOpenFile).toHaveBeenCalledWith("email.md");
  });

  it("email: falls back to email_id when thread_id is absent", async () => {
    authFetchMock.mockResolvedValue(jsonResponse({ email_id: "em-2", account: null }));
    const deps = makeDeps();
    navigateTag("email", { id: "em-2" }, deps);
    await waitForCall(deps.setSelectedThreadId as ReturnType<typeof vi.fn>);

    expect(deps.setSelectedThreadId).toHaveBeenCalledWith("em-2");
    expect(deps.setSelectedThreadAccount).toHaveBeenCalledWith(null);
  });

  it("email: falls back to the Email panel on a failed detail fetch", async () => {
    authFetchMock.mockRejectedValue(new Error("network error"));
    const deps = makeDeps();
    navigateTag("email", { id: "em-3" }, deps);
    await waitForCall(deps.setSidebarPanel as ReturnType<typeof vi.fn>);

    expect(deps.setSidebarPanel).toHaveBeenCalledWith("email");
    expect(deps.handleOpenFile).not.toHaveBeenCalled();
  });

  it("reminder: switches to the owning Reminders panel (no selected-row support yet)", () => {
    const deps = makeDeps();
    navigateTag("reminder", { id: "rem-1", title: "Follow up on tag merge UX" }, deps);
    expect(deps.setSidebarPanel).toHaveBeenCalledWith("reminder");
  });

  it("routine: switches to the owning Routines panel (no selected-row support yet)", () => {
    const deps = makeDeps();
    navigateTag("routine", { id: "rt-1", title: "Weekly y-agent changelog" }, deps);
    expect(deps.setSidebarPanel).toHaveBeenCalledWith("routine");
  });

  it("unknown entity_type: no-ops without throwing", () => {
    const deps = makeDeps();
    expect(() => navigateTag("unknown_future_type", { id: "x" }, deps)).not.toThrow();
    expect(deps.handleOpenFile).not.toHaveBeenCalled();
    expect(deps.setSidebarPanel).not.toHaveBeenCalled();
  });
});
