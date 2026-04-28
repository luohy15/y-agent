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
  flush: () => Promise<void>;
}

const DEFAULT_DEBOUNCE_MS = 400;

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
  enabledRef.current = enabled;
  keyRef.current = key;

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const performPut = useCallback(async () => {
    if (!enabledRef.current) return;
    if (inFlightRef.current) return;
    if (!pendingRef.current) return;
    const { value } = pendingRef.current;
    pendingRef.current = null;
    inFlightRef.current = true;
    setStatus("syncing");
    try {
      const res = await authFetch(`${API}/api/user-preference`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: keyRef.current, value }),
      });
      if (!res.ok) {
        // Treat any non-2xx (including 401) as error; 401 won't auto-retry
        // because we leave pendingRef empty unless the user changes value again.
        setStatus("error");
        inFlightRef.current = false;
        return;
      }
      setServerValue(value);
      // If a newer value queued up while we were sending, send it next.
      inFlightRef.current = false;
      if (pendingRef.current) {
        void performPut();
      } else {
        setStatus("synced");
      }
    } catch {
      // Network failure → keep value pending so the next online event flushes.
      pendingRef.current = pendingRef.current ?? { value };
      setStatus("offline");
      inFlightRef.current = false;
    }
  }, []);

  const flush = useCallback(async () => {
    clearTimer();
    await performPut();
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
    if (!enabled) {
      setServerValue(null);
      setLoaded(false);
      setStatus("idle");
      return;
    }
    let cancelled = false;
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

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      clearTimer();
    };
  }, []);

  return { serverValue, loaded, status, setValue, flush };
}
