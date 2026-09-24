import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { API, authFetch, getToken } from "../api";
import {
  ACTIVITY_BAR_HIDDEN_MODULES_KEY,
  normalizeHiddenSlugs,
  sameHiddenSlugs,
  withSlugVisibility,
  type ActivityBarVisibilityState,
} from "../utils/activityBarVisibility";

export interface ActivityBarVisibilityController extends ActivityBarVisibilityState {
  /** Last value a failed write was trying to persist. Null when the failure was the initial GET. */
  pendingSlugs: string[] | null;
  setSlugVisible: (slug: string, visible: boolean) => void;
  retry: () => void;
}

interface PreferenceResponse {
  key?: string;
  value?: unknown;
}

function preferenceKey(identity: string): string {
  return `activityBarHiddenModules:${identity}`;
}

async function fetchHiddenSlugs(): Promise<string[]> {
  const res = await authFetch(`${API}/api/user-preference?key=${encodeURIComponent(ACTIVITY_BAR_HIDDEN_MODULES_KEY)}`);
  if (!res.ok) {
    throw new Error(`activity bar visibility load failed (${res.status})`);
  }
  const data = (await res.json()) as PreferenceResponse;
  return normalizeHiddenSlugs(data?.value);
}

/**
 * One host-owned source for `activityBarHiddenModules`.
 * Mutations wait for a successful GET. A failed GET is not an empty preference
 * and is never written back. Writes are serialized; failure restores the last
 * confirmed set and keeps the intended target for Retry. Focus/reconnect
 * revalidation is paused while a PUT is in flight so a background GET cannot
 * clobber the optimistic value.
 */
export function useActivityBarVisibility(identity: string | null): ActivityBarVisibilityController {
  const enabled = !!identity && !!getToken();
  const key = enabled && identity ? preferenceKey(identity) : null;
  const { mutate } = useSWRConfig();
  const [optimistic, setOptimistic] = useState<string[] | null>(null);
  const [pendingSlugs, setPendingSlugs] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [writeError, setWriteError] = useState<string | null>(null);
  const inFlightRef = useRef(false);
  const savingRef = useRef(false);
  const pendingRef = useRef<string[] | null>(null);
  const hiddenSlugsRef = useRef<readonly string[]>([]);
  const loadedRef = useRef(false);
  const identityRef = useRef(identity);
  identityRef.current = identity;

  const swr = useSWR<string[]>(key, fetchHiddenSlugs, {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    revalidateIfStale: true,
    isPaused: () => inFlightRef.current || pendingRef.current !== null,
  });

  useEffect(() => {
    setOptimistic(null);
    setPendingSlugs(null);
    setSaving(false);
    setWriteError(null);
    inFlightRef.current = false;
    savingRef.current = false;
    pendingRef.current = null;
  }, [identity]);

  const confirmedRef = useRef<string[]>([]);
  const confirmed = useMemo(() => {
    const next = swr.data ? normalizeHiddenSlugs(swr.data) : [];
    if (sameHiddenSlugs(confirmedRef.current, next)) return confirmedRef.current;
    confirmedRef.current = next;
    return next;
  }, [swr.data]);
  const hiddenSlugs = optimistic && !sameHiddenSlugs(optimistic, confirmed) ? optimistic : confirmed;
  hiddenSlugsRef.current = hiddenSlugs;
  loadedRef.current = enabled && swr.data !== undefined && !swr.isLoading && !swr.error;
  const loaded = loadedRef.current;
  const loadError = swr.error instanceof Error
    ? swr.error.message
    : swr.error
      ? "activity bar visibility load failed"
      : null;

  const write = useCallback(async (target: string[], forIdentity: string) => {
    inFlightRef.current = true;
    savingRef.current = true;
    setSaving(true);
    setWriteError(null);
    try {
      const res = await authFetch(`${API}/api/user-preference`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: ACTIVITY_BAR_HIDDEN_MODULES_KEY, value: target }),
      });
      if (identityRef.current !== forIdentity) return;
      if (!res.ok) throw new Error(`activity bar visibility save failed (${res.status})`);
      const body = (await res.json()) as PreferenceResponse;
      const next = normalizeHiddenSlugs(body?.value ?? target);
      pendingRef.current = null;
      setPendingSlugs(null);
      setOptimistic(next);
      if (key) await mutate(key, next, { revalidate: false });
    } catch (err) {
      if (identityRef.current !== forIdentity) return;
      setOptimistic(null);
      pendingRef.current = target;
      setPendingSlugs(target);
      setWriteError(err instanceof Error ? err.message : "activity bar visibility save failed");
    } finally {
      inFlightRef.current = false;
      savingRef.current = false;
      if (identityRef.current === forIdentity) setSaving(false);
    }
  }, [key, mutate]);

  const setSlugVisible = useCallback((slug: string, visible: boolean) => {
    if (!enabled || !identity || !loadedRef.current || savingRef.current) return;
    const trimmed = slug.trim();
    if (!trimmed) return;
    const base = pendingRef.current ?? hiddenSlugsRef.current;
    const next = withSlugVisibility(base, trimmed, visible);
    setOptimistic(next);
    pendingRef.current = next;
    setPendingSlugs(next);
    savingRef.current = true;
    setSaving(true);
    void write(next, identity);
  }, [enabled, identity, write]);

  const retry = useCallback(() => {
    if (!enabled || !identity || saving || savingRef.current) return;
    if (writeError && pendingRef.current) {
      const target = pendingRef.current;
      setOptimistic(target);
      savingRef.current = true;
      setSaving(true);
      void write(target, identity);
      return;
    }
    void swr.mutate();
  }, [enabled, identity, saving, swr, write, writeError]);

  return {
    hiddenSlugs,
    loaded,
    saving,
    error: writeError ?? (loaded ? null : loadError),
    pendingSlugs,
    setSlugVisible,
    retry,
  };
}
