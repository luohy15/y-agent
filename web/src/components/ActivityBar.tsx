import { useState, useRef, useEffect } from "react";

interface VmConfigItem {
  name: string;
  vm_name: string;
  work_dir: string;
}

export type SidebarPanel = "files" | "git";

interface ActivityBarProps {
  isLoggedIn: boolean;
  vmList?: VmConfigItem[];
  selectedVM?: string | null;
  onSelectVM?: (name: string | null) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  activePanel: SidebarPanel;
  onSelectPanel: (panel: SidebarPanel) => void;
  onOpenFile?: (path: string) => void;
  activeFile?: string | null;
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
];

export default function ActivityBar({ isLoggedIn, vmList, selectedVM, onSelectVM, sidebarOpen, onToggleSidebar, activePanel, onSelectPanel, onOpenFile, activeFile }: ActivityBarProps) {
  const [vmDropdownOpen, setVmDropdownOpen] = useState(false);
  const vmDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!vmDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (vmDropdownRef.current && !vmDropdownRef.current.contains(e.target as Node)) {
        setVmDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [vmDropdownOpen]);

  if (!isLoggedIn) return null;

  const handlePanelClick = (panel: SidebarPanel) => {
    if (sidebarOpen && activePanel === panel) {
      onToggleSidebar(); // close sidebar
    } else if (!sidebarOpen) {
      onSelectPanel(panel);
      onToggleSidebar(); // open sidebar
    } else {
      onSelectPanel(panel); // just switch panel
    }
  };

  return (
    <div className="hidden md:flex shrink-0 w-10 bg-sol-base03 border-r border-sol-base02 flex-col items-center pt-2 gap-1">
      {/* VM selector */}
      {onSelectVM && (
      <div className="relative" ref={vmDropdownRef}>
        <button
          onClick={() => setVmDropdownOpen((v) => !v)}
          className={`w-8 h-8 flex items-center justify-center rounded cursor-pointer ${vmDropdownOpen ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`}
          title={`VM: ${selectedVM || "default"}`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
            <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
            <line x1="6" y1="6" x2="6.01" y2="6" />
            <line x1="6" y1="18" x2="6.01" y2="18" />
          </svg>
        </button>
        {vmDropdownOpen && onSelectVM && (
          <div className="absolute left-full top-0 ml-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[140px]">
            <button
              onClick={() => { onSelectVM(null); setVmDropdownOpen(false); }}
              className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${!selectedVM ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
            >
              default
            </button>
            {(vmList || []).filter((vm) => vm.name !== "default").map((vm) => (
              <button
                key={vm.name}
                onClick={() => { onSelectVM(vm.name); setVmDropdownOpen(false); }}
                className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${selectedVM === vm.name ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
              >
                {vm.name}
              </button>
            ))}
          </div>
        )}
      </div>
      )}
      {/* File tree toggle */}
      <button
        onClick={() => handlePanelClick("files")}
        className={`w-8 h-8 flex items-center justify-center rounded cursor-pointer ${sidebarOpen && activePanel === "files" ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`}
        title={sidebarOpen && activePanel === "files" ? "Hide file tree" : "Show file tree"}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
      {/* Git panel toggle */}
      <button
        onClick={() => handlePanelClick("git")}
        className={`w-8 h-8 flex items-center justify-center rounded cursor-pointer ${sidebarOpen && activePanel === "git" ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`}
        title={sidebarOpen && activePanel === "git" ? "Hide source control" : "Show source control"}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="18" cy="18" r="3" />
          <circle cx="6" cy="6" r="3" />
          <path d="M13 6h3a2 2 0 0 1 2 2v7" />
          <line x1="6" y1="9" x2="6" y2="21" />
        </svg>
      </button>
      {/* Viewer shortcuts */}
      <div className="w-6 border-t border-sol-base02 my-1" />
      {viewerShortcuts.map((v) => (
        <button
          key={v.key}
          onClick={() => onOpenFile?.(v.key)}
          className={`w-8 h-8 flex items-center justify-center rounded cursor-pointer ${activeFile === v.key ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`}
          title={v.label}
        >
          {v.icon}
        </button>
      ))}
    </div>
  );
}
