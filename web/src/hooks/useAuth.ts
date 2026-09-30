import { useState, useEffect, useCallback } from "react";
import { API, getToken, setToken, clearToken, getStoredEmail } from "../api";

const GOOGLE_CLIENT_ID = (import.meta as any).env?.VITE_GOOGLE_CLIENT_ID || "";
const MAIN_DOMAIN = (import.meta as any).env?.VITE_MAIN_DOMAIN || "yovy.app";
const isPreview = window.location.hostname !== MAIN_DOMAIN && window.location.hostname !== "localhost";

function redirectToLocalCallback(target: string, token: string, email: string) {
  try {
    // Reject forms URL would silently repair or normalize into a local host.
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
    url.searchParams.set("auth_token", token);
    url.searchParams.set("auth_email", email);
    window.location.href = url.toString();
  } catch {
    // Invalid callbacks must leave the user on the app without sending tokens.
  }
}

export function useAuth() {
  const [email, setEmail] = useState<string | null>(getStoredEmail());
  const [isLoggedIn, setIsLoggedIn] = useState(!!getToken());
  const [gsiReady, setGsiReady] = useState(false);

  const login = useCallback(async (credential: string) => {
    try {
      const res = await fetch(`${API}/api/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: credential }),
      });
      if (!res.ok) {
        console.error("Auth failed:", await res.text());
        return;
      }
      const data = await res.json();
      setToken(data.token);
      localStorage.setItem("user_email", data.email);
      setEmail(data.email);
      setIsLoggedIn(true);

      // Only local login callbacks may receive a token.
      const params = new URLSearchParams(window.location.search);
      const authRedirect = params.get("auth_redirect");
      if (authRedirect === "manual") {
        // CLI manual mode: display token for user to copy
        document.title = "CLI Login Token";
        document.body.innerHTML = `<div style="font-family:monospace;max-width:600px;margin:40px auto;padding:20px">
          <h2>CLI Login Token</h2>
          <p>Copy the token below and paste it into your terminal:</p>
          <pre style="background:#f0f0f0;padding:12px;word-break:break-all;user-select:all">${data.token}</pre>
          <p>Email: <strong>${data.email}</strong></p>
        </div>`;
      } else if (authRedirect) {
        redirectToLocalCallback(authRedirect, data.token, data.email);
      }
    } catch (err) {
      console.error("Auth error:", err);
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setEmail(null);
    setIsLoggedIn(false);
    // Hard-redirect to landing so RootGate re-decides and any in-memory state
    // (open chats, file viewers, SWR caches) is wiped.
    window.location.replace("/");
  }, []);

  // On mount: handle auth redirects
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    // Preview: pick up token from URL (returning from main domain login)
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

    // Main domain: if already logged in and auth_redirect is present, redirect back immediately
    const authRedirect = params.get("auth_redirect");
    if (authRedirect && getToken() && getStoredEmail()) {
      if (authRedirect === "manual") {
        // CLI manual mode: display token for user to copy
        document.title = "CLI Login Token";
        document.body.innerHTML = `<div style="font-family:monospace;max-width:600px;margin:40px auto;padding:20px">
          <h2>CLI Login Token</h2>
          <p>Copy the token below and paste it into your terminal:</p>
          <pre style="background:#f0f0f0;padding:12px;word-break:break-all;user-select:all">${getToken()}</pre>
          <p>Email: <strong>${getStoredEmail()}</strong></p>
        </div>`;
      } else {
        redirectToLocalCallback(authRedirect, getToken()!, getStoredEmail()!);
      }
    }
  }, []);

  // Expose handleGoogleCredential globally for GIS callback
  useEffect(() => {
    (window as any).handleGoogleCredential = (response: any) => {
      login(response.credential);
    };
    return () => {
      delete (window as any).handleGoogleCredential;
    };
  }, [login]);

  // Initialize Google Sign-In (only on main domain)
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || isPreview) return;
    const interval = setInterval(() => {
      if ((window as any).google?.accounts?.id) {
        clearInterval(interval);
        (window as any).google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (window as any).handleGoogleCredential,
        });
        setGsiReady(true);
      }
    }, 100);
    return () => clearInterval(interval);
  }, []);

  return { email, isLoggedIn, gsiReady, isPreview, login, logout };
}

export { GOOGLE_CLIENT_ID, MAIN_DOMAIN, isPreview };
