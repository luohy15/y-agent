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
  return fetch(url, { ...opts, headers });
}

export async function jsonFetcher(url: string, opts: { signal?: AbortSignal } = {}): Promise<any> {
  const res = await authFetch(url, { signal: opts.signal });
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
}
