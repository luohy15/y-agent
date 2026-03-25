export type SidebarPanel = "files" | "git" | "todo";

interface ActivityBarProps {
  isLoggedIn: boolean;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  activePanel: SidebarPanel;
  onSelectPanel: (panel: SidebarPanel) => void;
  onOpenFile?: (path: string) => void;
  activeFile?: string | null;
  mobile?: boolean;
  hideGroup1?: boolean;
  chatHide?: boolean;
  onToggleChatHide?: () => void;
}

const viewerShortcuts = [
  { key: "todo.md", label: "Todo", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  )},
  { key: "calendar.md", label: "Calendar", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )},
  { key: "finance.bean", label: "Finance", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  )},
  { key: "links.md", label: "Links", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )},
  { key: "emails.md", label: "Email", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" />
    </svg>
  )},
  { key: "dev.md", label: "Dev", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="6" y1="3" x2="6" y2="15" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  )},
];

export default function ActivityBar({ isLoggedIn, sidebarOpen, onToggleSidebar, activePanel, onSelectPanel, onOpenFile, activeFile, mobile, hideGroup1, chatHide, onToggleChatHide }: ActivityBarProps) {
  if (!isLoggedIn) return null;

  const handlePanelClick = (panel: SidebarPanel) => {
    if (mobile) {
      onSelectPanel(panel);
      return;
    }
    if (sidebarOpen && activePanel === panel) {
      onToggleSidebar(); // close sidebar
    } else if (!sidebarOpen) {
      onSelectPanel(panel);
      onToggleSidebar(); // open sidebar
    } else {
      onSelectPanel(panel); // just switch panel
    }
  };

  const btnClass = (active: boolean) => mobile
    ? `w-full h-9 flex items-center gap-3 px-3 rounded cursor-pointer text-sm ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`
    : `w-8 h-8 flex items-center justify-center rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`;

  return (
    <div className={mobile ? "flex shrink-0 bg-sol-base03 flex-col items-start p-3 gap-1 w-full" : "hidden md:flex shrink-0 w-10 bg-sol-base03 border-r border-sol-base02 flex-col items-center pt-2 gap-1"}>
      {/* Group 1: Todo + Terminal toggle */}
      {!hideGroup1 && (
        <>
          <button
            onClick={() => handlePanelClick("todo")}
            className={btnClass(sidebarOpen && activePanel === "todo")}
            title="Todo"
          >
            <span className="text-base font-bold leading-none">#</span>
            {mobile && <span>Todo</span>}
          </button>
          {onToggleChatHide && (
            <button
              onClick={onToggleChatHide}
              className={btnClass(!chatHide)}
              title={chatHide ? "Open terminal (Ctrl+`)" : "Close terminal (Ctrl+`)"}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <polyline points="2,4 6,7 2,10" />
                <line x1="7" y1="11" x2="12" y2="11" />
              </svg>
              {mobile && <span>Terminal</span>}
            </button>
          )}
          <div className={mobile ? "w-full border-t border-sol-base02 my-1" : "w-6 border-t border-sol-base02 my-1"} />
        </>
      )}
      {/* Group 2: Files, Git */}
      <button
        onClick={() => handlePanelClick("files")}
        className={btnClass(sidebarOpen && activePanel === "files")}
        title="Files"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
        {mobile && <span>Files</span>}
      </button>
      <button
        onClick={() => handlePanelClick("git")}
        className={btnClass(sidebarOpen && activePanel === "git")}
        title="Source Control"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="18" cy="18" r="3" />
          <circle cx="6" cy="6" r="3" />
          <path d="M13 6h3a2 2 0 0 1 2 2v7" />
          <line x1="6" y1="9" x2="6" y2="21" />
        </svg>
        {mobile && <span>Source Control</span>}
      </button>
      {/* Group 3: Apps */}
      <div className={mobile ? "w-full border-t border-sol-base02 my-1" : "w-6 border-t border-sol-base02 my-1"} />
      {viewerShortcuts.map((v) => (
        <button
          key={v.key}
          onClick={() => onOpenFile?.(v.key)}
          className={btnClass(!!chatHide && activeFile === v.key)}
          title={v.label}
        >
          {v.icon}
          {mobile && <span>{v.label}</span>}
        </button>
      ))}
    </div>
  );
}
