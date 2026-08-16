// Tag module click-to-navigate dispatch, lifted out of App.tsx so the 10-way
// carrier dispatch can be unit-tested with a mocked `authFetch`.
import { API, authFetch } from "../api";
import type { SidebarPanel } from "../components/ActivityBar";
import { artifactPanelKey } from "../host/artifacts";
import { openCalendarFocusDate } from "./calendarNavigate";
import { openTodoDetail } from "./todoDetailNavigate";

export interface TagResultItem {
  id: string;
  title?: string;
}

export interface OpenTodoDeps {
  setChatListTraceId: (id: string | null) => void;
  setSelectedChatId: (id: string | null) => void;
  setChatHide: (hide: boolean) => void;
  handleOpenFile: (path: string) => void;
}

// Shared by the Todo artifact's host command and tag-module navigation: filter
// the chat list by the todo, then either land on its latest chat or open the
// Todo module's in-place detail (`ui:todo`).
export function openTodo(todoId: string, deps: OpenTodoDeps): void {
  deps.setChatListTraceId(todoId);
  authFetch(`${API}/api/trace/latest_chat?trace_id=${encodeURIComponent(todoId)}`)
    .then((r) => r.json())
    .then((d) => {
      if (d.chat_id) { deps.setSelectedChatId(d.chat_id); deps.setChatHide(false); }
      else openTodoDetail(todoId, deps.handleOpenFile);
    })
    .catch(() => {});
}

export interface TagNavigateDeps extends OpenTodoDeps {
  handlePreviewFile: (path: string) => void;
  defaultWorkDir?: string | null;
  setSelectedEntityId: (id: string | null) => void;
  setSelectedLinkId: (id: string | null) => void;
  setSelectedLinkLinkId: (id: string | null) => void;
  setSelectedLinkContentKey: (key: string | null) => void;
  handleSelectFeed: (feedId: string, label: string) => void;
  setSelectedThreadId: (id: string | null) => void;
  setSelectedThreadAccount: (account: string | null) => void;
  setSidebarPanel: (panel: SidebarPanel) => void;
}

// One type-dispatch callback covering all 10 tag carriers, reusing each
// type's existing viewer/detail path rather than duplicating cards.
// calendar_event/email need a small detail fetch because the tag drill-down
// result omits start time / thread+account metadata; on a failed or
// incomplete fetch they fall back to switching to the owning panel (the same
// fallback the plan explicitly allows for reminder/routine) instead of
// silently doing nothing.
export function navigateTag(entityType: string, item: TagResultItem, deps: TagNavigateDeps): void {
  switch (entityType) {
    case "todo":
      openTodo(item.id, deps);
      break;
    case "note":
      deps.handlePreviewFile(deps.defaultWorkDir ? `${deps.defaultWorkDir}/${item.title || ""}` : (item.title || ""));
      break;
    case "chat":
      deps.setSelectedChatId(item.id);
      deps.setChatHide(false);
      break;
    case "entity":
      deps.setSelectedEntityId(item.id);
      deps.handleOpenFile("entity.md");
      break;
    case "link":
      deps.setSelectedLinkId(item.id);
      deps.setSelectedLinkLinkId(null);
      deps.setSelectedLinkContentKey(null);
      deps.handleOpenFile("link.md");
      break;
    case "rss_feed":
      deps.handleSelectFeed(item.id, item.title || item.id);
      break;
    case "calendar_event":
      authFetch(`${API}/api/calendar/detail?event_id=${encodeURIComponent(item.id)}`)
        .then((r) => r.json())
        .then((d) => {
          if (d.start_time) openCalendarFocusDate(d.start_time, deps.handleOpenFile);
          else deps.setSidebarPanel(artifactPanelKey("calendar"));
        })
        .catch(() => { deps.setSidebarPanel(artifactPanelKey("calendar")); });
      break;
    case "email":
      authFetch(`${API}/api/email/${encodeURIComponent(item.id)}`)
        .then((r) => r.json())
        .then((d) => { deps.setSelectedThreadId(d.thread_id || d.email_id || item.id); deps.setSelectedThreadAccount(d.account || null); deps.handleOpenFile("email.md"); })
        .catch(() => { deps.setSidebarPanel("email"); });
      break;
    case "reminder":
      deps.setSidebarPanel("reminder");
      break;
    case "routine":
      deps.setSidebarPanel("routine");
      break;
    default:
      break;
  }
}
