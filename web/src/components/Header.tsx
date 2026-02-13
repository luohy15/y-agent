import { useEffect, useRef } from "react";

interface HeaderProps {
  email: string | null;
  isLoggedIn: boolean;
  gsiReady: boolean;
  onLogout: () => void;
}

export default function Header({ email, isLoggedIn, gsiReady, onLogout }: HeaderProps) {
  const signinRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isLoggedIn || !gsiReady || !signinRef.current) return;
    (window as any).google.accounts.id.renderButton(signinRef.current, {
      theme: "filled_black",
      size: "medium",
      shape: "pill",
    });
  }, [isLoggedIn, gsiReady]);

  return (
    <header className="px-6 py-4 border-b border-sol-base02 shrink-0 flex items-center justify-between">
      <div className="h-8 w-8 rounded-full bg-sol-base02 flex items-center justify-center shadow-sm">
        <span className="text-lg font-bold text-sol-blue">Y</span>
      </div>
      <div className="flex items-center gap-3">
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
          <div ref={signinRef} />
        )}
      </div>
    </header>
  );
}
