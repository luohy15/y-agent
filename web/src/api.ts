import { clearUserViewCaches } from "./utils/userViewCache";

export const API = (import.meta as any).env?.VITE_API_URL || window.location.origin;

export function getToken(): string | null {
  return localStorage.getItem("jwt_token");
}

export function setToken(token: string): void {
  localStorage.setItem("jwt_token", token);
}

export function clearToken(): void {
  localStorage.removeItem("jwt_token");
  localStorage.removeItem("user_email");
  // Selection / workspace caches are user-scoped; never leave them for the next
  // account in this browser (todo 4468).
  clearUserViewCaches();
}

export const ACCESS_REVOKED_EVENT = "y-access-revoked";

function observeAccess(res: Response): void {
  if (res.status !== 403) return;
  void res.clone().json().then((body) => {
    if (!body || body.code !== "access_not_approved") return;
    const state = body.state === "pending" ? "pending" : "required";
    clearToken();
    window.dispatchEvent(new CustomEvent(ACCESS_REVOKED_EVENT, { detail: { state } }));
  }).catch(() => undefined);
}

export function getStoredEmail(): string | null {
  return localStorage.getItem("user_email");
}

export function authFetch(url: string, opts: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(opts.headers as Record<string, string> || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return fetch(url, { ...opts, headers }).then((res) => {
    observeAccess(res);
    return res;
  });
}

export async function jsonFetcher(url: string, opts: { signal?: AbortSignal } = {}): Promise<any> {
  const res = await authFetch(url, { signal: opts.signal });
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText || `HTTP ${res.status}`);
  }
  return res.json();
}
