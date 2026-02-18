import { useCallback, useState, useRef, useEffect, type RefCallback } from "react";

interface VmConfigItem {
  name: string;
  vm_name: string;
  work_dir: string;
}

interface HeaderProps {
  email: string | null;
  isLoggedIn: boolean;
  gsiReady: boolean;
  onLogout: () => void;
  onToggleSidebar?: () => void;
  onClickLogo?: () => void;
  vmList?: VmConfigItem[];
  selectedVM?: string | null;
  onSelectVM?: (name: string | null) => void;
}

export default function Header({ email, isLoggedIn, gsiReady, onLogout, onToggleSidebar, onClickLogo, vmList, selectedVM, onSelectVM }: HeaderProps) {
  const signinRef: RefCallback<HTMLDivElement> = useCallback((node) => {
    if (!node || isLoggedIn || !gsiReady) return;
    (window as any).google.accounts.id.renderButton(node, {
      theme: "filled_black",
      size: "large",
      shape: "pill",
    });
  }, [isLoggedIn, gsiReady]);

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

  const showVmSelector = isLoggedIn && vmList && vmList.length > 0 && onSelectVM;
  const currentWorkDir = vmList?.find((vm) => selectedVM ? vm.name === selectedVM : vm.name === "default")?.work_dir;

  return (
    <header className="px-4 md:px-6 py-4 border-b border-sol-base02 shrink-0 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <button onClick={onClickLogo} className="h-8 w-8 rounded-full bg-sol-base02 flex items-center justify-center shadow-sm cursor-pointer hover:bg-sol-base01 transition-colors">
          <span className="text-lg font-bold text-sol-blue">Y</span>
        </button>
        {showVmSelector && (
          <div className="relative" ref={vmDropdownRef}>
            <button
              onClick={() => setVmDropdownOpen((v) => !v)}
              className="flex items-center gap-1 px-2 py-1 text-sm text-sol-base01 hover:text-sol-base1 cursor-pointer rounded hover:bg-sol-base02"
              title="Select VM"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
                <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                <line x1="6" y1="6" x2="6.01" y2="6" />
                <line x1="6" y1="18" x2="6.01" y2="18" />
              </svg>
              <span className="hidden sm:inline">{selectedVM || "default"}</span>
            </button>
            {vmDropdownOpen && (
              <div className="absolute left-0 top-full mt-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[140px]">
                <button
                  onClick={() => { onSelectVM(null); setVmDropdownOpen(false); }}
                  className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${!selectedVM ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                >
                  default
                </button>
                {vmList.filter((vm) => vm.name !== "default").map((vm) => (
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
        {onToggleSidebar && (
          <button onClick={onToggleSidebar} className="flex items-center gap-1 px-2 py-1 text-sm text-sol-base01 hover:text-sol-base1 cursor-pointer rounded hover:bg-sol-base02">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            {currentWorkDir && <span className="hidden sm:inline">{currentWorkDir}</span>}
          </button>
        )}
      </div>
      <div className="flex items-center gap-3">
        <a href="https://github.com/luohy15/y-agent" target="_blank" rel="noopener noreferrer" className="flex items-center text-sol-base01 hover:text-sol-base1">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>
        {isLoggedIn ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-sol-base01 hidden sm:inline">{email}</span>
            <button
              onClick={onLogout}
              className="px-3 py-1.5 sm:px-2.5 sm:py-1 bg-sol-base02 border border-sol-base01 text-sol-base01 rounded-md text-sm sm:text-xs cursor-pointer hover:bg-sol-base01 hover:text-sol-base2"
            >
              Logout
            </button>
          </div>
        ) : (
          <div className="relative inline-flex items-center justify-center">
            <span className="px-5 py-2.5 bg-sol-base02 border border-sol-base021 text-sol-base1 rounded-md text-sm font-semibold pointer-events-none">
              Sign in with Google
            </span>
            <div ref={signinRef} className="absolute inset-0 opacity-[0.01] overflow-hidden [&_iframe]{min-width:100%!important;min-height:100%!important}" />
          </div>
        )}
      </div>
    </header>
  );
}
