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
  login: (credential: string) => Promise<void>;
  logout: () => void;
  beginSignIn: () => void;
  beginRequestAccess: () => void;
  recheck: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(getStoredEmail());
  const [isLoggedIn, setIsLoggedIn] = useState(!!getToken());
  const [gsiReady, setGsiReady] = useState(false);
  const [accessState, setAccessState] = useState<AccessState>(null);
  const intentRef = useRef<Intent>("sign-in");
  const credentialRef = useRef<string | null>(null);
  const hiddenButtonRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<(credential: string) => void>(() => {});

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
    credentialRef.current = credential;
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
  }, [applyRefusal, finishRedirect]);

  const requestAccess = useCallback(async (credential: string) => {
    credentialRef.current = credential;
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
  }, [refuseRedirect, signIn]);

  handleRef.current = (credential: string) => {
    if (!credential) return;
    if (intentRef.current === "request") void requestAccess(credential);
    else void signIn(credential);
  };

  const begin = useCallback((intent: Intent) => {
    intentRef.current = intent;
    const iframe = hiddenButtonRef.current?.querySelector("iframe");
    if (iframe instanceof HTMLElement) {
      iframe.click();
      return;
    }
    const google = (window as any).google;
    google?.accounts?.id?.prompt?.();
  }, []);

  const beginSignIn = useCallback(() => begin("sign-in"), [begin]);
  const beginRequestAccess = useCallback(() => {
    if (credentialRef.current) {
      void requestAccess(credentialRef.current);
      return;
    }
    begin("request");
  }, [begin, requestAccess]);
  const recheck = useCallback(() => {
    if (credentialRef.current) {
      void signIn(credentialRef.current);
      return;
    }
    begin("sign-in");
  }, [begin, signIn]);

  const logout = useCallback(() => {
    clearToken();
    credentialRef.current = null;
    setEmail(null);
    setIsLoggedIn(false);
    setAccessState(null);
    window.location.replace("/");
  }, []);

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
        const node = hiddenButtonRef.current;
        if (node && node.childElementCount === 0) {
          (window as any).google.accounts.id.renderButton(node, {
            theme: "filled_black",
            size: "large",
            type: "standard",
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
    begin("request");
  }, [begin, gsiReady]);

  useEffect(() => {
    const onRevoked = (event: Event) => {
      const state = (event as CustomEvent).detail?.state;
      credentialRef.current = null;
      setEmail(null);
      setIsLoggedIn(false);
      setAccessState(state === "pending" ? "pending" : "required");
    };
    window.addEventListener(ACCESS_REVOKED_EVENT, onRevoked);
    return () => window.removeEventListener(ACCESS_REVOKED_EVENT, onRevoked);
  }, []);

  const value: AuthValue = {
    email,
    isLoggedIn,
    gsiReady,
    isPreview,
    accessState,
    login: signIn,
    logout,
    beginSignIn,
    beginRequestAccess,
    recheck,
  };

  return createElement(
    AuthContext.Provider,
    { value },
    children,
    createElement("div", {
      ref: hiddenButtonRef,
      className: "fixed -left-[9999px] top-0 h-px w-px overflow-hidden",
      "aria-hidden": true,
    }),
  );
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}

export { GOOGLE_CLIENT_ID, MAIN_DOMAIN, isPreview };
