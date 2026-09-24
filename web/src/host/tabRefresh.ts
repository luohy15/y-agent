// Tab-level refresh registration (browser contract v17, todo 3674).
// Host-internal channel: a detail surface registers the one handler the host
// tab chrome should call. The host renders a refresh control only when the
// active tab has a registration, so the button exists exactly when it works.
//
// The handler is held in a ref so an inline arrow does not re-register on every
// render. Registration is cleared on unmount. Calling the hook with no provider
// (a panel surface, a demo mount that did not install the channel) is a no-op.
import { createContext, createElement, useContext, useEffect, useRef, type ReactNode } from "react";

export interface TabRefreshEntry {
  handler: () => void | Promise<void>;
  title?: string;
}

interface TabRefreshApi {
  setEntry: (entry: TabRefreshEntry | null) => void;
}

const TabRefreshContext = createContext<TabRefreshApi | null>(null);

export function TabRefreshProvider({
  onChange,
  children,
}: {
  onChange?: (entry: TabRefreshEntry | null) => void;
  children: ReactNode;
}) {
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const setEntry = useRef((entry: TabRefreshEntry | null) => {
    onChangeRef.current?.(entry);
  }).current;
  // Stable context value. A fresh `{ setEntry }` each render makes `api` change,
  // which re-runs the hook effect, which republishes, which re-renders a host
  // that stores the entry in a map. That loop never settles.
  const apiRef = useRef<TabRefreshApi>({ setEntry });

  useEffect(() => {
    return () => {
      onChangeRef.current?.(null);
    };
  }, []);

  return createElement(TabRefreshContext.Provider, { value: apiRef.current }, children);
}

/** Register this detail surface's refresh handler with the host tab chrome.
 * Pass null to clear the registration (the control disappears) without
 * unmounting. No-op outside a TabRefreshProvider. `title` is the hover text. */
export function useTabRefresh(
  handler: (() => void | PromiseLike<unknown>) | null,
  options?: { title?: string },
): void {
  const api = useContext(TabRefreshContext);
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const title = options?.title;
  const active = handler !== null;
  const published = useRef<{ active: boolean; title?: string } | null>(null);
  // One entry object for the life of this registration. Replacing it on a
  // title-only change would look like unregister-then-register to a map store.
  const entryRef = useRef<TabRefreshEntry | null>(null);
  if (!entryRef.current) {
    entryRef.current = {
      handler: () => {
        const result = handlerRef.current?.();
        if (result && typeof (result as PromiseLike<unknown>).then === "function") {
          return Promise.resolve(result).then(() => undefined);
        }
        return result as void | undefined;
      },
      title,
    };
  }

  useEffect(() => {
    if (!api) return;
    const same = published.current?.active === active && published.current?.title === title;
    if (same) return;
    published.current = { active, title };
    if (!active) {
      api.setEntry(null);
      return;
    }
    entryRef.current!.title = title;
    api.setEntry(entryRef.current);
  }, [api, title, active]);

  useEffect(() => {
    return () => {
      api?.setEntry(null);
    };
  }, [api]);
}
