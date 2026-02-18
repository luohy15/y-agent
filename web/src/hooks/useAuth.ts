import { useState, useEffect, useCallback } from "react";
import { API, getToken, setToken, clearToken, getStoredEmail } from "../api";

const GOOGLE_CLIENT_ID = (import.meta as any).env?.VITE_GOOGLE_CLIENT_ID || "";
const MAIN_DOMAIN = (import.meta as any).env?.VITE_MAIN_DOMAIN || "yovy.app";
const isPreview = window.location.hostname !== MAIN_DOMAIN && window.location.hostname !== "localhost";

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

      // If we came from a preview auth redirect, send token back
      const params = new URLSearchParams(window.location.search);
      const authRedirect = params.get("auth_redirect");
      if (authRedirect) {
        const url = new URL(authRedirect);
        url.searchParams.set("auth_token", data.token);
        url.searchParams.set("auth_email", data.email);
        window.location.href = url.toString();
      }
    } catch (err) {
      console.error("Auth error:", err);
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setEmail(null);
    setIsLoggedIn(false);
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
      const url = new URL(authRedirect);
      url.searchParams.set("auth_token", getToken()!);
      url.searchParams.set("auth_email", getStoredEmail()!);
      window.location.href = url.toString();
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
