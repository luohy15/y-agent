import { useRef, useEffect } from "react";
import type { Middleware } from "swr";

export const abortMiddleware: Middleware = (useSWRNext) => (key, fetcher, config) => {
  const ctrlRef = useRef<AbortController | null>(null);

  const wrapped = fetcher
    ? (...args: any[]) => {
        ctrlRef.current?.abort();
        const ac = new AbortController();
        ctrlRef.current = ac;
        return (fetcher as any)(...args, { signal: ac.signal });
      }
    : fetcher;

  useEffect(() => () => ctrlRef.current?.abort(), []);

  return useSWRNext(key, wrapped as any, config);
};
