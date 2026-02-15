import { useCallback, type RefCallback } from "react";

interface HeaderProps {
  email: string | null;
  isLoggedIn: boolean;
  gsiReady: boolean;
  onLogout: () => void;
  onToggleSidebar?: () => void;
  onClickLogo?: () => void;
}

export default function Header({ email, isLoggedIn, gsiReady, onLogout, onToggleSidebar, onClickLogo }: HeaderProps) {
  const signinRef: RefCallback<HTMLDivElement> = useCallback((node) => {
    if (!node || isLoggedIn || !gsiReady) return;
    (window as any).google.accounts.id.renderButton(node, {
      theme: "filled_black",
      size: "large",
      shape: "pill",
    });
  }, [isLoggedIn, gsiReady]);

  return (
    <header className="px-4 md:px-6 py-4 border-b border-sol-base02 shrink-0 flex items-center justify-between">
      <div className="flex items-center gap-2">
        {onToggleSidebar && (
          <button onClick={onToggleSidebar} className="md:hidden p-1 text-sol-base1 hover:text-sol-blue cursor-pointer">
            <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
        )}
        <button onClick={onClickLogo} className="h-8 w-8 rounded-full bg-sol-base02 flex items-center justify-center shadow-sm cursor-pointer hover:bg-sol-base01 transition-colors">
          <span className="text-lg font-bold text-sol-blue">Y</span>
        </button>
      </div>
      <div className="flex items-center gap-3">
        <a href="https://github.com/luohy15/y-agent" target="_blank" rel="noopener noreferrer" className="flex items-center text-sol-base01 hover:text-sol-base1">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>
        {isLoggedIn ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-sol-base01">{email}</span>
            <button
              onClick={onLogout}
              className="px-2.5 py-1 bg-sol-base02 border border-sol-base01 text-sol-base01 rounded-md text-xs cursor-pointer hover:bg-sol-base01 hover:text-sol-base2"
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
