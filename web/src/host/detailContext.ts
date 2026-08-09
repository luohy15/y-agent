// Per-detail-mount context (browser contract v8, todo 3084 H2).
// Generic host-only channel: ArtifactMount provides a value on surface="detail"
// and modules read it via useDetailContext<T>(). Not file-specific state in
// @y/host — any detail mount can pass its own shape.
import { createContext, useContext, type ReactNode } from "react";
import { createElement } from "react";

const DetailContext = createContext<unknown>(null);

export function DetailContextProvider({
  value,
  children,
}: {
  value: unknown;
  children: ReactNode;
}) {
  return createElement(DetailContext.Provider, { value }, children);
}

/** Host-provided per-detail-mount context. Null outside a detail surface or when
 * the host did not pass detailContext. */
export function useDetailContext<T = unknown>(): T | null {
  return useContext(DetailContext) as T | null;
}
