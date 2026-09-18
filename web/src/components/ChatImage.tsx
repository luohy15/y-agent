import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { API, authFetch, getToken } from "../api";
import ImageLightbox from "./ImageLightbox";

export const CHAT_IMAGE_PENDING_ATTR = "data-chat-image-pending";

export type ChatImageScopeMode = "visible" | "export";

export interface ChatImageProps {
  src?: string;
  alt?: string;
  width?: string | number;
  height?: string | number;
  className?: string;
  title?: string;
}

type Source =
  | { kind: "remote"; url: string }
  | { kind: "cdn"; path: string; url: string }
  | { kind: "local"; path: string }
  | { kind: "unsupported"; path: string };

type EntryStatus = "idle" | "loading" | "ready" | "failed" | "unavailable";

interface Entry {
  key: string;
  source: Source;
  status: EntryStatus;
  displayUrl?: string;
  ownedBlob?: string;
  abort?: AbortController;
}

interface Controller {
  mode: ChatImageScopeMode;
  get: (key: string) => Entry | undefined;
  ensure: (raw: string, kind: "attachment" | "markdown") => Entry | null;
  admit: (key: string) => void;
  registerSlot: (el: Element | null, key: string | null) => void;
}

const ChatImageContext = createContext<Controller | null>(null);
const ChatImageVersionContext = createContext(0);

export function parseChatImageSource(path: string, kind: "attachment" | "markdown"): Source | null {
  if (!path) return null;
  if (kind === "markdown") return { kind: "remote", url: path };
  if (/^https?:\/\//i.test(path)) return { kind: "remote", url: path };
  if (path.startsWith("s3://luohy15/")) {
    return { kind: "cdn", path, url: `https://cdn.luohy15.com/${path.slice(13)}` };
  }
  if (path.startsWith("s3://")) return { kind: "unsupported", path };
  return { kind: "local", path };
}

export function chatImageSourceKey(source: Source): string {
  if (source.kind === "remote") return `remote:${source.url}`;
  if (source.kind === "cdn") return `cdn:${source.path}`;
  if (source.kind === "local") return `local:${source.path}`;
  return `unsupported:${source.path}`;
}

export function isPositiveIntersection(
  entry: Pick<IntersectionObserverEntry, "isIntersecting" | "intersectionRect">,
): boolean {
  return entry.isIntersecting && entry.intersectionRect.width > 0 && entry.intersectionRect.height > 0;
}

function placeholderStyle(width?: string | number, height?: string | number): React.CSSProperties {
  return {
    width: width ?? 96,
    height: height ?? 96,
  };
}

function SlotPlaceholder({
  slotRef,
  width,
  height,
  pending,
  className,
}: {
  slotRef: (el: HTMLDivElement | null) => void;
  width?: string | number;
  height?: string | number;
  pending: boolean;
  className?: string;
}) {
  return (
    <div
      ref={slotRef}
      className={className || "h-24 w-24 rounded border border-sol-base02 bg-sol-base02"}
      style={placeholderStyle(width, height)}
      {...(pending ? { [CHAT_IMAGE_PENDING_ATTR]: "" } : {})}
    />
  );
}

function useSlot(controller: Controller | null, key: string | null) {
  const lastEl = useRef<Element | null>(null);
  return useCallback((el: Element | null) => {
    if (lastEl.current && lastEl.current !== el) controller?.registerSlot(lastEl.current, null);
    lastEl.current = el;
    controller?.registerSlot(el, key);
  }, [controller, key]);
}

export function ChatImageScope({
  scopeId,
  root = null,
  rootRef,
  mode = "visible",
  children,
}: {
  scopeId: string;
  root?: HTMLElement | null;
  rootRef?: RefObject<HTMLElement | null>;
  mode?: ChatImageScopeMode;
  children?: ReactNode;
}) {
  const storeRef = useRef(new Map<string, Entry>());
  const slotsRef = useRef(new Map<Element, string>());
  const observerRef = useRef<IntersectionObserver | null>(null);
  const [resolvedRoot, setResolvedRoot] = useState<HTMLElement | null>(root);
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    const node = root ?? rootRef?.current ?? null;
    setResolvedRoot((prev) => (prev === node ? prev : node));
  }, [root, rootRef, scopeId]);

  const teardown = useCallback(() => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    for (const entry of storeRef.current.values()) {
      entry.abort?.abort();
      entry.abort = undefined;
      if (entry.ownedBlob) URL.revokeObjectURL(entry.ownedBlob);
    }
    storeRef.current = new Map();
    slotsRef.current = new Map();
  }, []);

  useEffect(() => () => teardown(), [scopeId, teardown]);

  const admit = useCallback((key: string) => {
    const entry = storeRef.current.get(key);
    if (!entry || entry.status !== "idle") return;
    if (entry.source.kind === "unsupported") {
      entry.status = "unavailable";
      bump();
      return;
    }
    if (entry.source.kind === "remote" || entry.source.kind === "cdn") {
      entry.status = "ready";
      entry.displayUrl = entry.source.url;
      bump();
      return;
    }
    if (!getToken()) {
      entry.status = "unavailable";
      bump();
      return;
    }
    const abort = new AbortController();
    entry.abort = abort;
    entry.status = "loading";
    const path = entry.source.path;
    void (async () => {
      try {
        const response = await authFetch(
          `${API}/api/module/file/raw?path=${encodeURIComponent(path)}`,
          { signal: abort.signal },
        );
        if (!response.ok) throw new Error("failed to load image");
        const blob = await response.blob();
        if (abort.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        if (abort.signal.aborted || storeRef.current.get(key) !== entry) {
          URL.revokeObjectURL(url);
          return;
        }
        entry.displayUrl = url;
        entry.ownedBlob = url;
        entry.status = "ready";
        bump();
      } catch {
        if (abort.signal.aborted || storeRef.current.get(key) !== entry) return;
        entry.status = "failed";
        bump();
      }
    })();
    bump();
  }, [bump]);

  const observeIdle = useCallback(() => {
    const observer = observerRef.current;
    if (!observer) return;
    for (const [el, key] of slotsRef.current) {
      const entry = storeRef.current.get(key);
      if (!entry || entry.status !== "idle") observer.unobserve(el);
      else observer.observe(el);
    }
  }, []);

  useEffect(() => {
    if (mode === "export") {
      observerRef.current?.disconnect();
      observerRef.current = null;
      for (const entry of storeRef.current.values()) {
        if (entry.status === "idle") admit(entry.key);
      }
      return undefined;
    }
    const node = resolvedRoot;
    if (!node) return undefined;
    const syncObserver = () => {
      if (node.clientWidth <= 0 || node.clientHeight <= 0) {
        observerRef.current?.disconnect();
        observerRef.current = null;
        return;
      }
      if (observerRef.current) {
        observeIdle();
        return;
      }
      const observer = new IntersectionObserver(
        (entries) => {
          for (const item of entries) {
            if (!isPositiveIntersection(item)) continue;
            const key = slotsRef.current.get(item.target);
            if (!key) continue;
            admit(key);
            observer.unobserve(item.target);
          }
        },
        { root: node, rootMargin: "0px", threshold: 0 },
      );
      observerRef.current = observer;
      observeIdle();
    };
    syncObserver();
    const resize = typeof ResizeObserver === "function" ? new ResizeObserver(syncObserver) : null;
    resize?.observe(node);
    return () => {
      resize?.disconnect();
      observerRef.current?.disconnect();
      observerRef.current = null;
    };
  }, [admit, mode, observeIdle, resolvedRoot, scopeId]);

  const ensure = useCallback((raw: string, kind: "attachment" | "markdown"): Entry | null => {
    const source = parseChatImageSource(raw, kind);
    if (!source) return null;
    const key = chatImageSourceKey(source);
    const existing = storeRef.current.get(key);
    if (existing) return existing;
    const entry: Entry = { key, source, status: "idle" };
    storeRef.current.set(key, entry);
    return entry;
  }, []);

  const registerSlot = useCallback((el: Element | null, key: string | null) => {
    if (!el) return;
    if (!key) {
      slotsRef.current.delete(el);
      observerRef.current?.unobserve(el);
      return;
    }
    slotsRef.current.set(el, key);
    const entry = storeRef.current.get(key);
    if (!entry || entry.status !== "idle") {
      observerRef.current?.unobserve(el);
      return;
    }
    if (mode === "export") {
      admit(key);
      return;
    }
    observerRef.current?.observe(el);
  }, [admit, mode]);

  const get = useCallback((key: string) => storeRef.current.get(key), []);

  const controller = useMemo<Controller>(
    () => ({ mode, get, ensure, admit, registerSlot }),
    [admit, ensure, get, mode, registerSlot],
  );

  return (
    <ChatImageContext.Provider value={controller}>
      <ChatImageVersionContext.Provider value={version}>{children}</ChatImageVersionContext.Provider>
    </ChatImageContext.Provider>
  );
}

function useChatImageController(): Controller | null {
  useContext(ChatImageVersionContext);
  return useContext(ChatImageContext);
}

export function ChatImage({ src, alt, width, height, className, title }: ChatImageProps) {
  const controller = useChatImageController();
  const raw = typeof src === "string" ? src : "";
  const entry = controller?.ensure(raw, "markdown") ?? null;
  const current = entry ? controller?.get(entry.key) : undefined;
  const setSlot = useSlot(controller, entry?.key ?? null);

  if (!raw || !entry) return null;
  if (current?.displayUrl) {
    return (
      <img
        ref={setSlot}
        src={current.displayUrl}
        alt={alt || ""}
        title={title}
        width={width}
        height={height}
        className={className || "max-w-full"}
      />
    );
  }
  return (
    <SlotPlaceholder
      slotRef={setSlot}
      width={width}
      height={height}
      pending={current?.status === "idle" || current?.status === "loading"}
      className={className}
    />
  );
}

export function ChatMessageImages({ images }: { images?: string[] }) {
  const controller = useChatImageController();
  const [lightbox, setLightbox] = useState(-1);
  const paths = images || [];

  useEffect(() => {
    if (!controller || lightbox < 0 || lightbox >= paths.length) return;
    const entry = controller.ensure(paths[lightbox], "attachment");
    if (entry) controller.admit(entry.key);
  }, [controller, lightbox, paths]);

  if (!paths.length) return null;

  const display = paths.map((path) => {
    const entry = controller?.ensure(path, "attachment");
    return entry ? controller?.get(entry.key)?.displayUrl || "" : "";
  });

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {paths.map((path, index) => (
        <ChatMessageImageSlot key={`${path}:${index}`} path={path} onOpen={() => setLightbox(index)} />
      ))}
      <ImageLightbox
        images={display}
        index={lightbox}
        prefetchNeighbors={false}
        onClose={() => setLightbox(-1)}
        onNext={() => setLightbox((index) => (index + 1) % paths.length)}
        onPrev={() => setLightbox((index) => (index - 1 + paths.length) % paths.length)}
      />
    </div>
  );
}

function ChatMessageImageSlot({ path, onOpen }: { path: string; onOpen: () => void }) {
  const controller = useChatImageController();
  const entry = controller?.ensure(path, "attachment") ?? null;
  const current = entry ? controller?.get(entry.key) : undefined;
  const setSlot = useSlot(controller, entry?.key ?? null);
  if (current?.displayUrl) {
    return (
      <button type="button" onClick={onOpen} className="block cursor-zoom-in">
        <img
          ref={setSlot}
          src={current.displayUrl}
          alt={path.split("/").pop() || "attached image"}
          className="max-h-64 max-w-full rounded border border-sol-base02 object-contain"
        />
      </button>
    );
  }
  return (
    <SlotPlaceholder
      slotRef={setSlot}
      pending={current?.status === "idle" || current?.status === "loading"}
    />
  );
}
