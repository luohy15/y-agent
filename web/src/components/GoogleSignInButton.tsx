import { type RefCallback } from "react";
import { isPreview, MAIN_DOMAIN } from "../hooks/useAuth";

interface GoogleSignInButtonProps {
  gsiReady?: boolean;
  className?: string;
}

export default function GoogleSignInButton({ gsiReady, className }: GoogleSignInButtonProps) {
  if (isPreview) {
    const loginUrl = `https://${MAIN_DOMAIN}?auth_redirect=${encodeURIComponent(window.location.origin + window.location.pathname + window.location.search)}`;
    return (
      <a
        href={loginUrl}
        className={className ?? "px-5 py-2.5 bg-sol-base02 border border-sol-base01 text-sol-base1 rounded-md text-sm font-semibold cursor-pointer hover:bg-sol-base01 hover:text-sol-base2"}
      >
        Sign in with Google
      </a>
    );
  }

  const signinRef: RefCallback<HTMLDivElement> = (node) => {
    if (!node || !gsiReady) return;
    (window as any).google.accounts.id.renderButton(node, {
      theme: "filled_black",
      size: "large",
      shape: "pill",
    });
  };

  return (
    <div className="relative inline-flex items-center justify-center">
      <span className={className ?? "px-5 py-2.5 bg-sol-base02 border border-sol-base021 text-sol-base1 rounded-md text-sm font-semibold pointer-events-none"}>
        Sign in with Google
      </span>
      <div ref={signinRef} className="absolute inset-0 opacity-[0.01] overflow-hidden [&_iframe]{min-width:100%!important;min-height:100%!important}" />
    </div>
  );
}
