import { createContext, createElement, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ACCESS_REVOKED_EVENT, API, clearToken, getStoredEmail, getToken, setToken } from "../api";

const GOOGLE_CLIENT_ID = (import.meta as any).env?.VITE_GOOGLE_CLIENT_ID || "";
const MAIN_DOMAIN = (import.meta as any).env?.VITE_MAIN_DOMAIN || "yovy.app";
const isPreview = window.location.hostname !== MAIN_DOMAIN && window.location.hostname !== "localhost";

export type AccessState = "pending" | "required" | "requested" | "already" | "error" | null;
type Intent = "sign-in" | "request";

let gsiInitialized = false;

function redirectToLocalCallback(target: string, fields: Record<string, string>) {
  try {
    if (/[\s\\\u0000-\u001f\u007f]/.test(target) || /%(?![\da-f]{2})/i.test(target)) return;
    const authority = /^http:\/\/([^/?#]+)(?:[/?#]|$)/i.exec(target)?.[1];
    if (!authority || !/^[a-z\d.-]+(?::\d+)?$/i.test(authority)) return;
    const url = new URL(target);
    if (
      url.protocol !== "http:" ||
      (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") ||
      authority.split(":")[0].toLowerCase() !== url.hostname ||
      url.username || url.password || url.port === "0"
    ) return;
    for (const [key, value] of Object.entries(fields)) url.searchParams.set(key, value);
    window.location.href = url.toString();
  } catch {
    // Invalid callbacks must leave the user on the app without sending tokens.
  }
}

function showManual(title: string, body: string) {
  document.title = title;
  document.body.innerHTML = `<div style="font-family:monospace;max-width:600px;margin:40px auto;padding:20px">${body}</div>`;
}

async function readCode(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.code === "string" ? body.code : "";
  } catch {
    return "";
  }
}

interface AuthValue {
  email: string | null;
  isLoggedIn: boolean;
  gsiReady: boolean;
  isPreview: boolean;
  accessState: AccessState;
  hasCredential: boolean;
  login: (credential: string) => Promise<void>;
  logout: () => void;
  beginSignIn: () => void;
  beginRequestAccess: () => void;
  recheck: () => void;
  promptFor: (intent: Intent, quiet?: boolean) => void;
  bindIntent: (intent: Intent) => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(getStoredEmail());
  const [isLoggedIn, setIsLoggedIn] = useState(!!getToken());
  const [gsiReady, setGsiReady] = useState(false);
  const [accessState, setAccessState] = useState<AccessState>(null);
  const [hasCredential, setHasCredential] = useState(false);
  const intentRef = useRef<Intent>("sign-in");
  const credentialRef = useRef<string | null>(null);
  const handleRef = useRef<(credential: string) => void>(() => {});
  const rememberCredential = useCallback((credential: string | null) => {
    credentialRef.current = credential;
    setHasCredential(Boolean(credential));
  }, []);

  const finishRedirect = useCallback((token: string, address: string) => {
    const params = new URLSearchParams(window.location.search);
    const authRedirect = params.get("auth_redirect");
    if (authRedirect === "manual") {
      showManual(
        "CLI Login Token",
        `<h2>CLI Login Token</h2><p>Copy the token below and paste it into your terminal:</p><pre style="background:#f0f0f0;padding:12px;word-break:break-all;user-select:all">${token}</pre><p>Email: <strong>${address}</strong></p>`,
      );
    } else if (authRedirect) {
      redirectToLocalCallback(authRedirect, { auth_token: token, auth_email: address });
    }
  }, []);

  const refuseRedirect = useCallback((code: string) => {
    const authRedirect = new URLSearchParams(window.location.search).get("auth_redirect");
    if (authRedirect === "manual") {
      showManual("CLI Login Refused", `<h2>Login refused</h2><p>${code || "auth_failed"}</p>`);
      return;
    }
    if (authRedirect) redirectToLocalCallback(authRedirect, { auth_error: code || "auth_failed" });
  }, []);

  const applyRefusal = useCallback((code: string) => {
    if (code === "access_pending") setAccessState("pending");
    else if (code === "access_required") setAccessState("required");
    else setAccessState("error");
    refuseRedirect(code);
  }, [refuseRedirect]);

  const signIn = useCallback(async (credential: string) => {
    rememberCredential(credential);
    try {
      const res = await fetch(`${API}/api/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: credential }),
      });
      if (!res.ok) {
        applyRefusal(await readCode(res));
        return;
      }
      const data = await res.json();
      setToken(data.token);
      localStorage.setItem("user_email", data.email);
      setEmail(data.email);
      setIsLoggedIn(true);
      setAccessState(null);
      finishRedirect(data.token, data.email);
    } catch (err) {
      console.error("Auth error:", err);
      setAccessState("error");
    }
  }, [applyRefusal, finishRedirect, rememberCredential]);

  const requestAccess = useCallback(async (credential: string) => {
    rememberCredential(credential);
    try {
      const res = await fetch(`${API}/api/access/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: credential }),
      });
      if (!res.ok) {
        setAccessState("error");
        refuseRedirect(await readCode(res) || "auth_failed");
        return;
      }
      const data = await res.json();
      if (data.status === "approved") {
        await signIn(credential);
        return;
      }
      setAccessState(data.created ? "requested" : "already");
    } catch (err) {
      console.error("Access request error:", err);
      setAccessState("error");
    }
  }, [refuseRedirect, rememberCredential, signIn]);

  handleRef.current = (credential: string) => {
    if (!credential) return;
    if (intentRef.current === "request") void requestAccess(credential);
    else void signIn(credential);
  };

  const bindIntent = useCallback((intent: Intent) => {
    intentRef.current = intent;
  }, []);

  const promptFor = useCallback((intent: Intent, quiet = false) => {
    intentRef.current = intent;
    const prompt = (window as any).google?.accounts?.id?.prompt;
    if (typeof prompt !== "function") {
      if (!quiet) setAccessState("error");
      return;
    }
    prompt((notification: any) => {
      if (typeof notification?.isDisplayMoment === "function" && notification.isDisplayMoment()) return;
      if (typeof notification?.isDismissedMoment === "function" && notification.isDismissedMoment()) return;
      const notDisplayed = typeof notification?.isNotDisplayed === "function" && notification.isNotDisplayed();
      const skipped = typeof notification?.isSkippedMoment === "function" && notification.isSkippedMoment();
      if ((notDisplayed || skipped) && !quiet) setAccessState("error");
    });
  }, []);

  const beginSignIn = useCallback(() => {
    if (credentialRef.current) {
      void signIn(credentialRef.current);
      return;
    }
    promptFor("sign-in");
  }, [promptFor, signIn]);
  const beginRequestAccess = useCallback(() => {
    if (credentialRef.current) {
      void requestAccess(credentialRef.current);
      return;
    }
    promptFor("request");
  }, [promptFor, requestAccess]);
  const recheck = useCallback(() => {
    if (credentialRef.current) {
      void signIn(credentialRef.current);
      return;
    }
    promptFor("sign-in");
  }, [promptFor, signIn]);

  const logout = useCallback(() => {
    clearToken();
    rememberCredential(null);
    setEmail(null);
    setIsLoggedIn(false);
    setAccessState(null);
    window.location.replace("/");
  }, [rememberCredential]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("auth_token");
    const authEmail = params.get("auth_email");
    if (token && authEmail) {
      setToken(token);
      localStorage.setItem("user_email", authEmail);
      setEmail(authEmail);
      setIsLoggedIn(true);
      params.delete("auth_token");
      params.delete("auth_email");
      const clean = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (clean ? `?${clean}` : ""));
      return;
    }
    const authRedirect = params.get("auth_redirect");
    if (authRedirect && getToken() && getStoredEmail()) {
      if (authRedirect === "manual") {
        showManual(
          "CLI Login Token",
          `<h2>CLI Login Token</h2><p>Copy the token below and paste it into your terminal:</p><pre style="background:#f0f0f0;padding:12px;word-break:break-all;user-select:all">${getToken()}</pre><p>Email: <strong>${getStoredEmail()}</strong></p>`,
        );
      } else {
        redirectToLocalCallback(authRedirect, { auth_token: getToken() || "", auth_email: getStoredEmail() || "" });
      }
    }
  }, []);

  useEffect(() => {
    (window as any).handleGoogleCredential = (response: any) => {
      handleRef.current(response?.credential || "");
    };
    return () => {
      delete (window as any).handleGoogleCredential;
    };
  }, []);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || isPreview) return;
    const interval = setInterval(() => {
      if ((window as any).google?.accounts?.id) {
        clearInterval(interval);
        if (!gsiInitialized) {
          gsiInitialized = true;
          (window as any).google.accounts.id.initialize({
            client_id: GOOGLE_CLIENT_ID,
            callback: (response: any) => handleRef.current(response?.credential || ""),
          });
        }
        setGsiReady(true);
      }
    }, 100);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!gsiReady || isPreview || getToken()) return;
    if (new URLSearchParams(window.location.search).get("access") !== "request") return;
    promptFor("request", true);
  }, [gsiReady, promptFor]);

  useEffect(() => {
    const onRevoked = (event: Event) => {
      const state = (event as CustomEvent).detail?.state;
      rememberCredential(null);
      setEmail(null);
      setIsLoggedIn(false);
      setAccessState(state === "pending" ? "pending" : "required");
    };
    window.addEventListener(ACCESS_REVOKED_EVENT, onRevoked);
    return () => window.removeEventListener(ACCESS_REVOKED_EVENT, onRevoked);
  }, [rememberCredential]);

  const value: AuthValue = {
    email,
    isLoggedIn,
    gsiReady,
    isPreview,
    accessState,
    hasCredential,
    login: signIn,
    logout,
    beginSignIn,
    beginRequestAccess,
    recheck,
    promptFor,
    bindIntent,
  };

  return createElement(AuthContext.Provider, { value }, children);
}

export function GoogleIntentButton({
  intent,
  label,
  compact = false,
  className,
}: {
  intent: Intent;
  label: string;
  compact?: boolean;
  className: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const { gsiReady, bindIntent, promptFor } = useAuth();
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    const node = hostRef.current;
    if (!node) return;
    node.dataset.gisIntent = intent;
  }, [intent]);

  useEffect(() => {
    const node = hostRef.current;
    if (!gsiReady || !node) return;
    const google = (window as any).google?.accounts?.id;
    if (!google?.renderButton || node.dataset.gsiMounted === "1") {
      setRendered(node.childElementCount > 0);
      return;
    }
    node.dataset.gsiMounted = "1";
    try {
      google.renderButton(node, {
        theme: "filled_black",
        size: compact ? "medium" : "large",
        text: intent === "request" ? "continue_with" : "signin_with",
        shape: "rectangular",
        click_listener: () => bindIntent(node.dataset.gisIntent === "request" ? "request" : "sign-in"),
      });
    } catch (err) {
      console.error("GIS button render failed:", err);
      node.dataset.gsiMounted = "";
    }
    setRendered(node.childElementCount > 0);
    const observer = new MutationObserver(() => setRendered(node.childElementCount > 0));
    observer.observe(node, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [bindIntent, compact, gsiReady, intent]);

  return createElement(
    "span",
    { className: "inline-flex flex-col items-start gap-1 align-middle" },
    createElement(
      "span",
      { className: compact ? "text-[10px] leading-none text-sol-base00" : "text-[11px] leading-none text-sol-base00" },
      label,
    ),
    createElement("span", {
      ref: hostRef,
      "data-gis-intent": intent,
      className: gsiReady ? "inline-flex min-h-8 min-w-[200px]" : "inline-flex",
    }),
    rendered
      ? null
      : createElement(
          "button",
          {
            type: "button",
            className,
            disabled: !gsiReady,
            onClick: () => promptFor(intent),
          },
          label,
        ),
  );
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}

export { GOOGLE_CLIENT_ID, MAIN_DOMAIN, isPreview };
