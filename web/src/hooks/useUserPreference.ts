import { useCallback, useEffect, useRef, useState } from "react";
import { API, authFetch } from "../api";

export type SyncStatus =
  | "idle"
  | "loading"
  | "syncing"
  | "synced"
  | "error"
  | "offline";

export interface UseUserPreferenceOptions {
  enabled: boolean;
  debounceMs?: number;
}

export interface UseUserPreferenceResult<T> {
  serverValue: T | null;
  loaded: boolean;
  status: SyncStatus;
  setValue: (value: T | null) => void;
  /** Force a pending write now. Resolves true when the value reached the server. */
  flush: () => Promise<boolean>;
}

const DEFAULT_DEBOUNCE_MS = 400;
const MAX_CONFLICT_RETRIES = 3;

/** Server revision (`updated_at_unix`), or null when the response has none. */
function revisionFrom(raw: unknown): number | null {
  if (!raw || typeof raw !== "object") return null;
  const value = (raw as { updated_at_unix?: unknown }).updated_at_unix;
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function conflictRevision(body: unknown): number | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  return revisionFrom(detail ?? body);
}

export function useUserPreference<T>(
  key: string,
  options: UseUserPreferenceOptions,
): UseUserPreferenceResult<T> {
  const { enabled, debounceMs = DEFAULT_DEBOUNCE_MS } = options;

  const [serverValue, setServerValue] = useState<T | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState<SyncStatus>("idle");

  const pendingRef = useRef<{ value: T | null } | null>(null);
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef<boolean>(false);
  const enabledRef = useRef(enabled);
  const keyRef = useRef(key);
  /** Last known server revision; null means no conditional write yet. */
  const revisionRef = useRef<number | null>(null);
  /**
   * Bumped whenever `enabled`/`key` changes. An in-flight request from a
   * previous generation (e.g. Account A's write completing after an in-place
   * sign-out/sign-in) must not update this hook's state or re-send its value.
   */
  const generationRef = useRef(0);
  enabledRef.current = enabled;
  keyRef.current = key;

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const performPut = useCallback(async (): Promise<boolean> => {
    if (!enabledRef.current) return false;
    if (inFlightRef.current) return false;
    if (!pendingRef.current) return false;
    const { value } = pendingRef.current;
    pendingRef.current = null;
    inFlightRef.current = true;
    setStatus("syncing");
    const generation = generationRef.current;
    const stale = () => generationRef.current !== generation;
    for (let attempt = 0; attempt <= MAX_CONFLICT_RETRIES; attempt += 1) {
      if (stale()) {
        inFlightRef.current = false;
        return false;
      }
      const revision = revisionRef.current;
      const payload =
        revision == null
          ? { key: keyRef.current, value }
          : { key: keyRef.current, value, base_revision: revision };
      let res: Response;
      try {
        res = await authFetch(`${API}/api/user-preference`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } catch {
        if (stale()) {
          inFlightRef.current = false;
          return false;
        }
        // Network failure → keep value pending so the next online / page-hide
        // flush retries it.
        pendingRef.current = pendingRef.current ?? { value };
        setStatus("offline");
        inFlightRef.current = false;
        return false;
      }
      if (stale()) {
        inFlightRef.current = false;
        return false;
      }
      if (res.ok) {
        const body = await res.json().catch(() => null);
        if (stale()) {
          inFlightRef.current = false;
          return false;
        }
        revisionRef.current = revisionFrom(body) ?? revision;
        setServerValue(value);
        inFlightRef.current = false;
        // If a newer value queued up while we were sending, send it next.
        if (pendingRef.current) {
          void performPut();
        } else {
          setStatus("synced");
        }
        return true;
      }
      if (res.status === 409) {
        // Last write wins for this key: adopt the revision the server reported
        // and retry our own value on top of it.
        const body = await res.json().catch(() => null);
        if (stale()) {
          inFlightRef.current = false;
          return false;
        }
        revisionRef.current = conflictRevision(body) ?? revisionRef.current;
        continue;
      }
      // Other non-2xx (including 401) stays an error; a later selection change
      // or page-hide flush sends it again rather than hammering the endpoint.
      // A newer value queued while this PUT was in flight must not be dropped.
      pendingRef.current = pendingRef.current ?? { value };
      setStatus("error");
      inFlightRef.current = false;
      return false;
    }
    // Conflict retries exhausted: stay pending for the next explicit flush.
    pendingRef.current = pendingRef.current ?? { value };
    setStatus("error");
    inFlightRef.current = false;
    return false;
  }, []);

  const flush = useCallback(async (): Promise<boolean> => {
    clearTimer();
    if (inFlightRef.current) {
      // Wait for the in-flight write; it re-sends anything queued behind it.
      return false;
    }
    return performPut();
  }, [performPut]);

  const setValue = useCallback(
    (value: T | null) => {
      if (!enabledRef.current) return;
      pendingRef.current = { value };
      clearTimer();
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        void performPut();
      }, debounceMs);
    },
    [debounceMs, performPut],
  );

  // Initial GET + react to enabled / key changes.
  useEffect(() => {
    // A disabled hook or a new key belongs to a different preference (or a
    // signed-out session): drop any queued write and invalidate an in-flight
    // one so it can never flush into another account's row (todo 4468 review).
    generationRef.current += 1;
    clearTimer();
    pendingRef.current = null;
    if (!enabled) {
      revisionRef.current = null;
      setServerValue(null);
      setLoaded(false);
      setStatus("idle");
      return;
    }
    let cancelled = false;
    revisionRef.current = null;
    setStatus("loading");
    setLoaded(false);
    (async () => {
      try {
        const res = await authFetch(
          `${API}/api/user-preference?key=${encodeURIComponent(key)}`,
        );
        if (cancelled) return;
        if (!res.ok) {
          setStatus("error");
          setLoaded(true);
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        // A missing row reports no `updated_at_unix`; revision 0 means "no row".
        revisionRef.current = revisionFrom(data) ?? 0;
        const next = (data && data.value !== undefined ? data.value : null) as
          | T
          | null;
        setServerValue(next);
        setStatus("idle");
        setLoaded(true);
      } catch {
        if (cancelled) return;
        setStatus("offline");
        setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, key]);

  // Flush pending value when the browser regains connectivity.
  useEffect(() => {
    const onOnline = () => {
      if (pendingRef.current && enabledRef.current) {
        void performPut();
      }
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [performPut]);

  // Flush a pending write when the page is hidden or closed, and on unmount.
  useEffect(() => {
    const flushPending = () => {
      clearTimer();
      if (pendingRef.current && enabledRef.current) void performPut();
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flushPending();
    };
    window.addEventListener("pagehide", flushPending);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", flushPending);
      document.removeEventListener("visibilitychange", onVisibility);
      flushPending();
    };
  }, [performPut]);

  return { serverValue, loaded, status, setValue, flush };
}
