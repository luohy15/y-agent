// Full four-region public demo shell (todo 3158 H6,
// pages/plan-3158-full-shell-demo.md, pages/design-3158.html).
//
// Reuses production chrome (DesktopHeaderBar, CentreModeTabs, FileTabStrip,
// MarkdownPreview) and rails (ActivityBar, RightActivityBar) with the H5
// unavailable affordance. Each showcase slot mounts the module's surface-aware
// `demo` export through DemoMount; failures stay per-slot.
//
// In-shell navigation is local React state and resets on full page load.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import ActivityBar, {
  BUILT_IN_PANEL_ITEMS,
  type SidebarPanel,
} from "../components/ActivityBar";
import RightActivityBar from "../components/RightActivityBar";
import { MODULE_ICONS, type PanelItem } from "../components/panelCatalog";
import CentreModeTabs from "../components/shell/CentreModeTabs";
import DesktopHeaderBar from "../components/shell/DesktopHeaderBar";
import FileTabStrip, { FileBreadcrumb } from "../components/shell/FileTabStrip";
import MarkdownPreview from "../components/shell/MarkdownPreview";
import { runDemoHostCommand } from "./commands";
import DemoMount from "./DemoMount";
import { DemoUnavailable } from "./DemoStates";
import { useDemoHostState } from "./channel";
import {
  DEMO_CHROME,
  DEMO_LEFT_UNAVAILABLE,
  DEMO_RIGHT_LIVE,
  DEMO_RIGHT_UNAVAILABLE,
  DEMO_SHOWCASE_ORDER,
  panelFromShowcaseKey,
  showcaseKeyFromPanel,
  type DemoShowcaseKey,
} from "./chrome";
import { fetchPublicDemos, type PublicDemoRef } from "./lookup";
import { DEMO_MODULES } from "./routes";
import { buildDemoModules } from "./syntheticModules";

type LookupState =
  | { status: "loading" }
  | { status: "ready"; demos: Map<string, PublicDemoRef | null> };

type RightPanelKey = "artifact:chat" | "artifact:note" | "artifact:file" | "diff";

const DEFAULT_SIDEBAR_WIDTH = 300;
const DEFAULT_RIGHT_WIDTH = 330;
const MIN_SIDEBAR = 200;
const MAX_SIDEBAR = 480;
const MIN_RIGHT = 240;
const MAX_RIGHT = 520;

function DemoBadge() {
  return (
    <span
      title="Fictional sample data. Nothing here is saved, sent, or connected to a real account."
      className="shrink-0 px-2 py-0.5 rounded border border-sol-yellow/40 bg-sol-yellow/10 text-sol-yellow text-[11px] whitespace-nowrap"
    >
      demo data
    </span>
  );
}

function fileTabLabel(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

function SlotMount({
  demos,
  demoKey,
  surface,
  panelLocation,
  detailContext,
}: {
  demos: Map<string, PublicDemoRef | null>;
  demoKey: string;
  surface: "panel" | "detail" | "shell";
  panelLocation?: "left" | "right";
  detailContext?: unknown;
}) {
  const demo = demos.get(demoKey);
  if (!demo) return <DemoUnavailable />;
  return (
    <DemoMount
      slug={demo.slug}
      version={demo}
      surface={surface}
      panelLocation={panelLocation}
      detailContext={detailContext}
    />
  );
}

export default function DemoShell() {
  const host = useDemoHostState();
  const [lookup, setLookup] = useState<LookupState>({ status: "loading" });
  const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>("artifact:chat");
  // `/demo` always starts with Chat selected. Rail clicks switch surfaces in
  // memory so the public route remains stable and reload resets the baseline.
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [bottomOpen, setBottomOpen] = useState(false);
  const [rightPanel, setRightPanel] = useState<RightPanelKey>("artifact:chat");
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);
  const [rightWidth, setRightWidth] = useState(DEFAULT_RIGHT_WIDTH);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobileRightOpen, setMobileRightOpen] = useState(false);
  const leftResizeRef = useRef(false);
  const rightResizeRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setLookup({ status: "loading" });
    fetchPublicDemos(DEMO_MODULES.map(({ key }) => key)).then((demos) => {
      if (!cancelled) setLookup({ status: "ready", demos });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.title = "y-agent demo";
  }, []);

  const demos = lookup.status === "ready" ? lookup.demos : null;
  const modules = useMemo(
    () => (demos ? buildDemoModules(demos) : []),
    [demos],
  );

  const rightItems = useMemo<PanelItem<RightPanelKey>[]>(() => {
    const bySlug = new Map(modules.map((m) => [m.slug, m]));
    const chat = bySlug.get("chat");
    const note = bySlug.get("note");
    return [
      {
        key: "artifact:chat",
        label: chat?.active_version?.label || "Chat",
        icon: MODULE_ICONS.message,
      },
      {
        key: "artifact:note",
        label: note?.active_version?.label || "Notes",
        icon: MODULE_ICONS["file-text"],
      },
      {
        key: "artifact:file",
        label: "Files",
        icon: MODULE_ICONS.file,
      },
      {
        key: "diff",
        label: "Diff",
        icon: (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="18" cy="18" r="3" />
            <circle cx="6" cy="6" r="3" />
            <path d="M13 6h3a2 2 0 0 1 2 2v7" />
            <line x1="6" y1="9" x2="6" y2="21" />
          </svg>
        ),
      },
    ];
  }, [modules]);

  // Extra catalog rows so unavailable keys have icons (ActivityBar filters by panelByKey).
  const railArtifacts = useMemo(() => {
    const base = modules.slice();
    // Synthetic entries for unavailable module-shaped keys that are not showcase.
    const extras: Array<{ slug: string; label: string; icon: string }> = [
      { slug: "module", label: "Modules", icon: "package" },
      { slug: "tag", label: "Tags", icon: "tag" },
      { slug: "file", label: "Files", icon: "file" },
      { slug: "calendar", label: "Calendar", icon: "calendar" },
      { slug: "email", label: "Email", icon: "mail" },
    ];
    for (const extra of extras) {
      if (base.some((m) => m.slug === extra.slug)) continue;
      base.push({
        module_id: `demo-${extra.slug}`,
        slug: extra.slug,
        active_version_id: `demo-${extra.slug}-v0`,
        enabled: true,
        active_version: {
          version_id: `demo-${extra.slug}-v0`,
          version_no: 0,
          ui_sha256: "0".repeat(64),
          min_host_version: 9,
          label: extra.label,
          icon: extra.icon,
        },
      });
    }
    return base;
  }, [modules]);

  const leftUnavailable = useMemo(() => {
    // Include built-in keys that exist in BUILT_IN_PANEL_ITEMS plus artifact:* extras.
    const builtIn = new Set(BUILT_IN_PANEL_ITEMS.map((p) => p.key));
    return DEMO_LEFT_UNAVAILABLE.filter(
      (key) => builtIn.has(key as SidebarPanel) || key.startsWith("artifact:"),
    );
  }, []);

  const onUnavailable = useCallback((key: string) => {
    runDemoHostCommand(
      "demo.blocked",
      `${key.replace(/^artifact:/, "")} is not part of the demo.`,
    );
  }, []);

  // Design selectSurface: chat → centre chat mode; todo/note → centre files mode
  // with the matching detail tab (pages/design-3158.html:805-818). Rail clicks
  // keep the left panel and centre column in lockstep.
  const selectShowcase = useCallback((key: DemoShowcaseKey) => {
    setSidebarPanel(panelFromShowcaseKey(key));
    if (key === "chat") {
      host.setCentreMode("chat");
      host.setDetailTab(null);
    } else if (key === "todo") {
      host.setCentreMode("files");
      host.setDetailTab("todo");
    } else if (key === "note") {
      host.setCentreMode("files");
      // Note opens files mode; a concrete file arrives via file.open. Clear a
      // leftover todo tab so centre shows the empty-file state or active file.
      host.setDetailTab(null);
    }
    if (typeof window !== "undefined" && window.innerWidth < 768) {
      setMobileSidebarOpen(true);
      setMobileNavOpen(false);
    } else {
      setDesktopSidebarOpen(true);
    }
  }, [host]);

  const handleSelectPanel = useCallback(
    (panel: SidebarPanel) => {
      const showcase = showcaseKeyFromPanel(panel);
      if (showcase) {
        selectShowcase(showcase);
        return;
      }
      onUnavailable(panel);
    },
    [onUnavailable, selectShowcase],
  );

  const handleLeftResizeStart = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      leftResizeRef.current = true;
      const startX = e.clientX;
      const startWidth = sidebarWidth;
      const onMove = (ev: PointerEvent) => {
        if (!leftResizeRef.current) return;
        const next = Math.min(MAX_SIDEBAR, Math.max(MIN_SIDEBAR, startWidth + (ev.clientX - startX)));
        setSidebarWidth(next);
      };
      const onUp = () => {
        leftResizeRef.current = false;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [sidebarWidth],
  );

  const handleRightResizeStart = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      rightResizeRef.current = true;
      const startX = e.clientX;
      const startWidth = rightWidth;
      const onMove = (ev: PointerEvent) => {
        if (!rightResizeRef.current) return;
        const next = Math.min(MAX_RIGHT, Math.max(MIN_RIGHT, startWidth - (ev.clientX - startX)));
        setRightWidth(next);
      };
      const onUp = () => {
        rightResizeRef.current = false;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [rightWidth],
  );

  const activeShowcase = showcaseKeyFromPanel(sidebarPanel) ?? "chat";

  const leftBody = (() => {
    if (!demos) {
      return <div className="p-4 text-xs text-sol-base01">Loading demo…</div>;
    }
    if (activeShowcase === "chat") {
      return (
        <SlotMount demos={demos} demoKey="chat" surface="panel" panelLocation="left" />
      );
    }
    if (activeShowcase === "todo") {
      return (
        <SlotMount demos={demos} demoKey="todo" surface="panel" panelLocation="left" />
      );
    }
    if (activeShowcase === "note") {
      return (
        <SlotMount demos={demos} demoKey="note" surface="panel" panelLocation="left" />
      );
    }
    return <DemoUnavailable />;
  })();

  const todoDetailContext = useMemo(() => {
    if (host.detailTab === "trace") {
      return {
        view: "trace" as const,
        todoId: host.selectedTodoId ?? undefined,
        traceId: host.traceFilter ?? host.selectedTodoId ?? undefined,
      };
    }
    if (host.detailTab === "todo" || host.selectedTodoId) {
      return {
        view: "todo" as const,
        todoId: host.selectedTodoId ?? undefined,
      };
    }
    return { view: "todo" as const };
  }, [host.detailTab, host.selectedTodoId, host.traceFilter]);

  const centreFilesBody = (() => {
    if (!demos) {
      return <div className="p-4 text-xs text-sol-base01">Loading demo…</div>;
    }
    // Priority: open markdown file from note → todo/trace detail → empty.
    if (host.activeFile) {
      const tabs = [
        {
          key: host.activeFile.path,
          label: fileTabLabel(host.activeFile.path),
          title: host.activeFile.path,
        },
      ];
      return (
        <div className="flex flex-col h-full min-h-0">
          <FileTabStrip
            className="shrink-0"
            tabs={tabs}
            activeKey={host.activeFile.path}
            onSelect={() => undefined}
            onClose={() => host.clearActiveFile()}
            breadcrumb={<FileBreadcrumb path={host.activeFile.path} />}
          />
          <div className="flex-1 min-h-0 overflow-auto px-5 py-4">
            <MarkdownPreview content={host.activeFile.content} />
          </div>
        </div>
      );
    }
    if (host.detailTab === "todo" || host.detailTab === "trace" || host.selectedTodoId) {
      const tabs = [
        {
          key: "todo",
          label: "todo.md",
          title: "Todo full view",
        },
        {
          key: "trace",
          label: "trace.md",
          title: "Trace full view",
        },
      ];
      const activeKey = host.detailTab === "trace" ? "trace" : "todo";
      const crumb =
        activeKey === "trace"
          ? `trace > ${DEMO_CHROME.traceId}`
          : "todo";
      return (
        <div className="flex flex-col h-full min-h-0">
          <FileTabStrip
            className="shrink-0"
            tabs={tabs}
            activeKey={activeKey}
            onSelect={(key) => host.setDetailTab(key === "trace" ? "trace" : "todo")}
            onClose={() => {
              host.setDetailTab(null);
            }}
            breadcrumb={<FileBreadcrumb path={crumb} />}
          />
          <div className="flex-1 min-h-0 overflow-hidden">
            <SlotMount
              demos={demos}
              demoKey="todo"
              surface="detail"
              detailContext={todoDetailContext}
            />
          </div>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 p-6 text-center">
        <p className="text-sm text-sol-base1">No file open</p>
        <p className="text-xs text-sol-base01 max-w-sm">
          Open a note from the Notes panel, or open Todo full view from the Todo panel.
        </p>
      </div>
    );
  })();

  const centreChatBody = (() => {
    if (!demos) {
      return <div className="p-4 text-xs text-sol-base01">Loading demo…</div>;
    }
    return <SlotMount demos={demos} demoKey="chat" surface="shell" />;
  })();

  const rightBody = (() => {
    if (!demos) {
      return <div className="p-4 text-xs text-sol-base01">Loading demo…</div>;
    }
    if (rightPanel === "artifact:chat") {
      return (
        <SlotMount demos={demos} demoKey="chat" surface="panel" panelLocation="right" />
      );
    }
    if (rightPanel === "artifact:note") {
      return (
        <SlotMount demos={demos} demoKey="note" surface="panel" panelLocation="right" />
      );
    }
    return <DemoUnavailable />;
  })();

  const meta = (
    <>
      <span className="font-mono text-xs">#{DEMO_CHROME.traceId}</span>
      <span className="font-mono text-xs">{DEMO_CHROME.vmName}</span>
      <span className="font-mono text-xs">{DEMO_CHROME.botName}</span>
      <span className="font-mono text-xs">{DEMO_CHROME.workDir}</span>
    </>
  );

  const activityProps = {
    isLoggedIn: true,
    forceSignInFooter: true,
    // Presentation-only: signed-in rail shape, no preference API / localStorage.
    presentationOnly: true,
    artifacts: railArtifacts,
    artifactsLoaded: lookup.status === "ready",
    availableOrder: DEMO_SHOWCASE_ORDER as unknown as readonly string[],
    unavailableKeys: leftUnavailable as unknown as readonly string[],
    onUnavailableSelect: onUnavailable,
    activePanel: sidebarPanel,
    onSelectPanel: handleSelectPanel,
  };

  return (
    <div className="h-dvh flex flex-col overflow-hidden bg-sol-base03 text-sol-base0" data-demo-shell>
      {/* Mobile-only nav bar */}
      <div className="md:hidden flex items-center gap-1 px-2 py-1.5 border-b border-sol-base02 bg-sol-base03 shrink-0">
        <button
          type="button"
          onClick={() => setMobileNavOpen((v) => !v)}
          className={`h-8 flex items-center gap-1.5 px-2 text-sm cursor-pointer rounded hover:bg-sol-base02 ${
            mobileNavOpen ? "text-sol-blue" : "text-sol-base01 hover:text-sol-base1"
          }`}
          title="Menu"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => setMobileSidebarOpen((v) => !v)}
          className={`h-8 flex items-center gap-1.5 px-2 text-sm cursor-pointer rounded hover:bg-sol-base02 ${
            mobileSidebarOpen ? "text-sol-blue" : "text-sol-base01 hover:text-sol-base1"
          }`}
          title="Left panel"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        </button>
        <button
          type="button"
          onClick={() => setMobileRightOpen((v) => !v)}
          className={`h-8 flex items-center gap-1.5 px-2 text-sm cursor-pointer rounded hover:bg-sol-base02 ${
            mobileRightOpen ? "text-sol-blue" : "text-sol-base01 hover:text-sol-base1"
          }`}
          title="Right panel"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </button>
        <div className="flex-1" />
        <DemoBadge />
        <a href="/" className="shrink-0 px-2 py-0.5 rounded text-[11px] text-sol-base01 hover:text-sol-cyan">
          sign in
        </a>
      </div>

      <DesktopHeaderBar
        meta={meta}
        leftOpen={desktopSidebarOpen}
        bottomOpen={bottomOpen}
        rightOpen={rightOpen}
        maximized={!desktopSidebarOpen && !rightOpen}
        onToggleLeft={() => setDesktopSidebarOpen((v) => !v)}
        onToggleBottom={() => setBottomOpen((v) => !v)}
        onToggleRight={() => setRightOpen((v) => !v)}
        onToggleMaximize={() => {
          if (!desktopSidebarOpen && !rightOpen) {
            setDesktopSidebarOpen(true);
            setRightOpen(true);
          } else {
            setDesktopSidebarOpen(false);
            setRightOpen(false);
          }
        }}
      />

      <div className="flex flex-1 min-h-0">
        <ActivityBar
          {...activityProps}
          sidebarOpen={desktopSidebarOpen}
          onToggleSidebar={() => setDesktopSidebarOpen((v) => !v)}
        />

        {(mobileNavOpen || mobileSidebarOpen || mobileRightOpen) && (
          <div
            className="fixed inset-0 bg-black/40 z-20 md:hidden"
            onClick={() => {
              setMobileNavOpen(false);
              setMobileSidebarOpen(false);
              setMobileRightOpen(false);
            }}
          />
        )}

        {/* Mobile activity rail drawer */}
        <div
          className={`
            fixed inset-y-0 left-0 z-30 transform transition-transform duration-200
            md:hidden shrink-0 border-r border-sol-base02 bg-sol-base03 overflow-y-auto
            ${mobileNavOpen ? "translate-x-0" : "-translate-x-full hidden"}
          `}
          style={{ width: 200 }}
        >
          <ActivityBar
            {...activityProps}
            mobile
            sidebarOpen={mobileSidebarOpen}
            onToggleSidebar={() => {
              setMobileNavOpen(false);
              setMobileSidebarOpen((v) => !v);
            }}
          />
        </div>

        {/* Left sidebar */}
        <div
          data-demo-region="left"
          className={`
            fixed inset-y-0 left-0 z-30 transform transition-transform duration-200
            md:relative md:z-auto shrink-0 border-r border-sol-base02 bg-sol-base03
            overflow-hidden max-w-[280px] md:max-w-none
            ${mobileSidebarOpen ? "translate-x-0" : "-translate-x-full hidden"}
            ${desktopSidebarOpen ? "md:translate-x-0 md:block" : "md:-translate-x-full md:hidden"}
          `}
          style={{ width: sidebarWidth }}
        >
          <div className="flex flex-col h-full min-h-0 relative">
            <div className="flex-1 min-h-0 overflow-hidden" data-demo-left-panel={activeShowcase}>
              {leftBody}
            </div>
            <div
              className="hidden sm:block absolute top-0 -right-2 w-4 lg:w-1 lg:right-0 h-full cursor-col-resize z-10 group"
              onPointerDown={handleLeftResizeStart}
            >
              <div className="absolute top-0 right-2 lg:right-0 w-1 h-full hover:bg-sol-blue/40 active:bg-sol-blue/60" />
            </div>
          </div>
        </div>

        {/* Centre + right */}
        <div className="flex-1 flex min-w-0 min-h-0">
          <div className="flex-1 flex flex-col min-w-0 min-h-0" data-demo-region="centre">
            <CentreModeTabs
              mode={host.centreMode}
              onModeChange={host.setCentreMode}
              onNew={() =>
                runDemoHostCommand(
                  "demo.blocked",
                  "Starting a new chat needs an account.",
                )
              }
              newDisabled
              newTitle="New chat — unavailable in the demo"
              trailing={
                <>
                  <div className="flex-1" />
                  <DemoBadge />
                  <a
                    href="/"
                    className="shrink-0 ml-2 px-2 py-0.5 rounded text-[11px] text-sol-base01 hover:text-sol-cyan hidden md:inline"
                  >
                    sign in
                  </a>
                </>
              }
            />
            <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative">
              <div
                className={`absolute inset-0 ${host.centreMode === "files" ? "" : "hidden"}`}
                data-demo-centre="files"
              >
                {centreFilesBody}
              </div>
              <div
                className={`absolute inset-0 flex flex-col ${host.centreMode === "chat" ? "" : "hidden"}`}
                data-demo-centre="chat"
              >
                {centreChatBody}
              </div>
            </div>
            {bottomOpen && (
              <div
                className="hidden md:flex shrink-0 border-t border-sol-base02 bg-sol-base03 items-center justify-center text-xs text-sol-base01"
                style={{ height: 120 }}
                data-demo-region="bottom"
              >
                Terminal is not part of the demo.
              </div>
            )}
          </div>

          {rightOpen && (
            <div
              data-demo-region="right"
              className="hidden sm:flex shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden relative flex-col"
              style={{ width: rightWidth }}
            >
              <div
                className="absolute top-0 -left-2 w-4 lg:w-1 lg:left-0 h-full cursor-col-resize z-10 group"
                onPointerDown={handleRightResizeStart}
              >
                <div className="absolute top-0 left-2 lg:left-0 w-1 h-full hover:bg-sol-blue/40 active:bg-sol-blue/60" />
              </div>
              <RightActivityBar
                items={rightItems}
                activePanel={rightPanel}
                onSelectPanel={(key) => {
                  if ((DEMO_RIGHT_LIVE as readonly string[]).includes(key)) {
                    setRightPanel(key);
                    return;
                  }
                  onUnavailable(key);
                }}
                onRefresh={() => undefined}
                onClose={() => setRightOpen(false)}
                unavailableKeys={DEMO_RIGHT_UNAVAILABLE as unknown as readonly RightPanelKey[]}
                onUnavailableSelect={onUnavailable}
              />
              <div className="flex-1 min-h-0 overflow-hidden" data-demo-right-panel={rightPanel}>
                {rightBody}
              </div>
            </div>
          )}

          {/* Mobile right drawer */}
          <div
            className={`
              fixed inset-y-0 right-0 z-30 transform transition-transform duration-200
              md:hidden shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden flex flex-col
              max-w-[280px] ${mobileRightOpen ? "translate-x-0" : "translate-x-full hidden"}
            `}
            style={{ width: rightWidth }}
          >
            <RightActivityBar
              items={rightItems}
              activePanel={rightPanel}
              onSelectPanel={(key) => {
                if ((DEMO_RIGHT_LIVE as readonly string[]).includes(key)) {
                  setRightPanel(key);
                  return;
                }
                onUnavailable(key);
              }}
              onRefresh={() => undefined}
              onClose={() => setMobileRightOpen(false)}
              unavailableKeys={DEMO_RIGHT_UNAVAILABLE as unknown as readonly RightPanelKey[]}
              onUnavailableSelect={onUnavailable}
            />
            <div className="flex-1 min-h-0 overflow-hidden">{rightBody}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
