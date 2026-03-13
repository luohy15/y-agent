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
}

export default function ActivityBar({ isLoggedIn, vmList, selectedVM, onSelectVM, sidebarOpen, onToggleSidebar, activePanel, onSelectPanel }: ActivityBarProps) {
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
    </div>
  );
}
