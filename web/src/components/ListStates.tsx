interface ListStateProps {
  className?: string;
}

function stateClassName(className?: string): string {
  return className ?? "p-2";
}

export function ListLoading({ className }: ListStateProps) {
  return <p className={`text-sol-base01 italic ${stateClassName(className)}`}>Loading...</p>;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function ListError({ error, className }: { error?: unknown; className?: string }) {
  if (isAbortError(error)) return null;
  const message = error instanceof Error ? error.message : "";
  return <p className={`text-sol-red ${stateClassName(className)}`}>Error{message ? `: ${message}` : ""}</p>;
}

export function ListEmpty({ label, className }: { label: string; className?: string }) {
  return <p className={`text-sol-base01 italic ${stateClassName(className)}`}>No {label} found</p>;
}

// Renders above the list (not in place of it) so a background revalidation
// failure never hides last-known-good (persisted-cache) data behind a silent
// stale view.
export function StaleBanner({ error, className }: { error?: unknown; className?: string }) {
  if (!error || isAbortError(error)) return null;
  const message = error instanceof Error ? error.message : "";
  return (
    <p className={`text-sol-yellow bg-sol-yellow/10 border border-sol-yellow/30 rounded px-2 py-1 mb-1 text-[0.65rem] ${className ?? ""}`}>
      Showing cached data, refresh failed{message ? `: ${message}` : ""}
    </p>
  );
}
