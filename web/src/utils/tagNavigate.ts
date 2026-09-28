// Tag module click-to-navigate dispatch, lifted out of App.tsx so the 10-way
// carrier dispatch can be unit-tested with a mocked `authFetch`.
import { API, authFetch } from "../api";
import type { SidebarPanel } from "../components/ActivityBar";
import { artifactPanelKey } from "../host/artifacts";
import { openCalendarFocusDate } from "./calendarNavigate";
import { openEmailThread } from "./emailNavigate";
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
  /** Todo row-body re-open (todo 3715): the chat selected when the lookup
   * resolves, and the reload request used when it resolved to that same chat.
   * Both optional; without them a same-chat resolve is a plain no-op select. */
  getSelectedChatId?: () => string | null;
  requestChatRefresh?: () => void;
}

// Only the most recent openTodo lookup may act, so a late answer for todo A
// cannot navigate (or reload) after todo B was opened (todo 3715).
let openTodoSeq = 0;

// Shared by the Todo artifact's host command and tag-module navigation: filter
// the chat list by the todo, then either land on its latest chat or open the
// Todo module's in-place detail (`ui:todo`). When the latest chat is already
// the selected one, a caller-supplied `requestChatRefresh` reloads it instead.
export function openTodo(todoId: string, deps: OpenTodoDeps): void {
  const seq = ++openTodoSeq;
  deps.setChatListTraceId(todoId);
  authFetch(`${API}/api/trace/latest_chat?trace_id=${encodeURIComponent(todoId)}`)
    .then((r) => r.json())
    .then((d) => {
      if (seq !== openTodoSeq) return;
      if (d.chat_id) {
        if (deps.requestChatRefresh && deps.getSelectedChatId?.() === d.chat_id) deps.requestChatRefresh();
        else deps.setSelectedChatId(d.chat_id);
        deps.setChatHide(false);
      }
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
  setSidebarPanel: (panel: SidebarPanel) => void;
}

// One type-dispatch callback covering all 10 tag carriers, reusing each
// type's existing viewer/detail path rather than duplicating cards.
// calendar_event needs a detail fetch because the tag drill-down result omits
// start time metadata. Email result ids are canonical thread keys, so they open
// directly. Invalid payloads or failures fall back to the owning panel.
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
      if (typeof item.id === "string" && item.id) {
        try {
          openEmailThread(item.id, "", deps.handleOpenFile);
        } catch {
          deps.setSidebarPanel(artifactPanelKey("email"));
        }
      } else {
        deps.setSidebarPanel(artifactPanelKey("email"));
      }
      break;
    case "reminder":
      deps.setSidebarPanel(artifactPanelKey("reminder"));
      break;
    case "routine":
      deps.setSidebarPanel(artifactPanelKey("routine"));
      break;
    default:
      break;
  }
}
