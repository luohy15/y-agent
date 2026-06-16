// Unauthenticated /showcase route used only by the doc-screenshot pipeline
// (web/scripts/screenshot.mjs). It installs a window.fetch mock and then renders
// the REAL panel components against seeded fixtures, so the captured PNGs match
// production styling exactly (no reimplementation). Each panel sits in a
// fixed-size wrapper tagged `data-screenshot=<name>` for Playwright to target.
import { installFetchMock, CHAT_MESSAGES_FIXTURE } from "../showcase/fixtures";
import TodoList from "./TodoList";
import TraceView from "./TraceView";
import NoteList from "./NoteList";
import LinkList from "./LinkList";
import FinanceViewer from "./FinanceViewer";
import ChatView from "./ChatView";

// Install the fetch mock + force deterministic panel state before any panel
// mounts and fires its SWR fetch. Runs once when this lazy chunk is imported.
installFetchMock();
try {
  // Show all todo statuses (the fixture mixes pending/active/completed).
  localStorage.setItem("todoListStatusFilter", "all");
  // Finance: land on the visually rich Holdings tab (pie chart + table).
  localStorage.setItem("finance-tab", "holdings");
  localStorage.setItem("finance-mode", "live");
  localStorage.setItem("holdings-risky-only", "0");
} catch {
  // localStorage may be unavailable in some headless contexts; harmless.
}

const noop = () => {};

interface PanelFrameProps {
  name: string;
  title: string;
  width: number;
  height: number;
  children: React.ReactNode;
}

function PanelFrame({ name, title, width, height, children }: PanelFrameProps) {
  return (
    <div className="flex flex-col items-start gap-2">
      <span className="text-sol-base01 text-xs font-mono">{title}</span>
      <div
        data-screenshot={name}
        className="bg-sol-base03 border border-sol-base02 rounded-lg overflow-hidden"
        style={{ width, height }}
      >
        {children}
      </div>
    </div>
  );
}

export default function ScreenshotShowcase() {
  return (
    <div className="min-h-dvh bg-sol-base03 text-sol-base0 font-mono p-8">
      <h1 className="text-sol-base1 text-lg mb-6">y-agent panel showcase (mock data)</h1>
      <div className="flex flex-wrap gap-10">
        <PanelFrame name="todo" title="todo & trace · TodoList" width={420} height={620}>
          <TodoList isLoggedIn onSelectTodo={noop} onSelectTrace={noop} onChatListRefresh={noop} />
        </PanelFrame>

        <PanelFrame name="trace" title="todo & trace · TraceView" width={560} height={1000}>
          <TraceView
            isLoggedIn
            selectedTraceId="2541"
            onSelectChat={noop}
            onPreviewLink={noop}
            onOpenFile={noop}
          />
        </PanelFrame>

        <PanelFrame name="note" title="note · NoteList" width={420} height={240}>
          <NoteList isLoggedIn todoId="2541" onOpenFile={noop} />
        </PanelFrame>

        <PanelFrame name="link" title="link · LinkList" width={420} height={540}>
          <LinkList isLoggedIn onPreview={noop} />
        </PanelFrame>

        <PanelFrame name="finance" title="finance · FinanceViewer" width={900} height={760}>
          <FinanceViewer />
        </PanelFrame>

        <PanelFrame name="chat" title="chat · ChatView (snapshot)" width={560} height={680}>
          {/* ChatView's root is `flex-1 flex flex-col`, so it needs a flex-column
              parent of known height to fill the fixed panel frame. */}
          <div className="flex flex-col h-full w-full">
            <ChatView
              mode="snapshot"
              isLoggedIn={false}
              chatId="showcase-chat"
              snapshotMessages={CHAT_MESSAGES_FIXTURE}
            />
          </div>
        </PanelFrame>
      </div>
    </div>
  );
}
