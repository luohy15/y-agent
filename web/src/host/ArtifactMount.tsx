// Per-panel crash containment for artifact panels (plan sub-task S6). Two
// failure surfaces are kept distinct: `loadArtifact` failures (fetch, hash
// mismatch, host-version skew) happen before the artifact component ever
// renders, while a render throw inside the loaded component is caught by the
// nested boundary below. Either way the host never white-screens: the
// fallback names the artifact + version and offers a one-click rollback to
// the previous published version (mirrors ErrorBoundary.tsx's Reload button).
import { Component, useCallback, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { API, authFetch } from "../api";
import {
  ArtifactLoadError,
  loadArtifact,
  type ArtifactLoadErrorKind,
  type ArtifactVersionRef,
  type LoadedArtifact,
} from "./loader";
import { DetailContextProvider } from "./detailContext";
import { PanelLocationProvider } from "./panelLocation";

type FailureKind = ArtifactLoadErrorKind | "render";

type MountState =
  | { status: "loading" }
  | { status: "loaded"; artifact: LoadedArtifact }
  | { status: "error"; kind: FailureKind; message: string };

function failureHeading(kind: FailureKind): string {
  switch (kind) {
    case "integrity":
      return "Integrity check failed";
    case "version-skew":
      return "Incompatible host version";
    case "bundle":
      return "Bundle is broken";
    case "render":
      return "Crashed while rendering";
    case "fetch":
    default:
      return "Failed to load";
  }
}

interface RenderBoundaryProps {
  children: ReactNode;
  onError: (error: Error) => void;
}

// Class component: `componentDidCatch` is the only way to catch a render
// throw from `children`. Renders nothing on error; the parent already knows
// (via `onError`) and renders the shared FailureCard in its place.
class RenderBoundary extends Component<RenderBoundaryProps, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[artifact-mount] render error", error, info);
    this.props.onError(error);
  }

  render() {
    return this.state.hasError ? null : this.props.children;
  }
}

async function detailOf(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : undefined;
  } catch {
    return undefined;
  }
}

function RollbackButton({
  artifactId,
  versionId,
  onRolledBack,
}: {
  artifactId: string;
  versionId: string;
  onRolledBack?: () => void;
}) {
  const [status, setStatus] = useState<"idle" | "pending" | "failed" | "conflict">("idle");
  const [detail, setDetail] = useState<string | undefined>(undefined);

  const rollback = useCallback(async () => {
    setStatus("pending");
    setDetail(undefined);
    try {
      const res = await authFetch(`${API}/api/module/rollback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_id: artifactId, from_version_id: versionId }),
      });
      if (res.status === 409) {
        // Someone published a newer version since this card was rendered
        // (e.g. `y module publish` from the VM); rolling back "the version before
        // whatever is active now" would demote that newer version instead of
        // the one this card is about. Refuse and let the host refresh state.
        setStatus("conflict");
        onRolledBack?.();
        return;
      }
      if (!res.ok) {
        throw new Error((await detailOf(res)) ?? `HTTP ${res.status}`);
      }
      if (onRolledBack) {
        onRolledBack();
        setStatus("idle");
        return;
      }
      // No host wiring yet to refresh just this panel's state: falling back
      // to a full reload would silently discard unsaved work elsewhere in the
      // app (open editors, chat drafts), which App.tsx's own dirty-navigation
      // guard treats as something to confirm first, not do unconditionally.
      if (window.confirm("Roll back and reload the app? This discards any unsaved changes elsewhere.")) {
        window.location.reload();
      } else {
        setStatus("idle");
      }
    } catch (err) {
      setStatus("failed");
      setDetail((err as Error).message);
    }
  }, [artifactId, versionId, onRolledBack]);

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        disabled={status === "pending"}
        onClick={rollback}
        className="px-3 py-1 rounded bg-sol-blue/80 text-sol-base03 text-xs hover:bg-sol-blue cursor-pointer disabled:opacity-50"
      >
        {status === "pending" ? "Rolling back…" : "Roll back to previous version"}
      </button>
      {status === "failed" && (
        <p className="text-xs text-sol-red">{detail ?? "Rollback failed; try again."}</p>
      )}
      {status === "conflict" && (
        <p className="text-xs text-sol-yellow">
          {onRolledBack ? "A newer version is already active; refreshing." : "A newer version is already active."}
        </p>
      )}
    </div>
  );
}

function FailureCard({
  slug,
  version,
  artifactId,
  kind,
  message,
  onRolledBack,
}: {
  slug: string;
  version: ArtifactVersionRef;
  artifactId: string;
  kind: FailureKind;
  message: string;
  onRolledBack?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 h-full p-4 text-center">
      <p className="text-sm text-sol-red">
        &quot;{slug}&quot; (v{version.version_no})
      </p>
      <p className="text-xs text-sol-orange font-medium">{failureHeading(kind)}</p>
      <p className="text-xs text-sol-base01 max-w-md break-words">{message}</p>
      <RollbackButton artifactId={artifactId} versionId={version.version_id} onRolledBack={onRolledBack} />
    </div>
  );
}

interface ArtifactMountProps {
  slug: string;
  artifactId: string;
  version: ArtifactVersionRef;
  label?: string;
  // Which of the module's surfaces to render (decision note
  // pages/decision-2412-module-shape.md; "shell" added by V1, todo 3042).
  // "detail"/"shell" fall back to the panel when the module doesn't define
  // that surface, so a persisted `ui:<slug>` tab or a stale shell claimant is
  // never a dead mount.
  surface?: "panel" | "detail" | "shell";
  // Called after a rollback attempt succeeds (or hits a 409 conflict), so the
  // mount surface can refetch the artifact's current active version and
  // remount instead of the loader falling back to a confirmed full reload.
  onRolledBack?: () => void;
  // Reports whether the loaded module actually defines a detail surface, so
  // the host can offer the "open full view" affordance only when there is a
  // distinct view to open. Fires once per successful load.
  onDetailAvailable?: (hasDetail: boolean) => void;
  // Optional host content under a FailureCard (V4 shell-slot: when a shell
  // claimant's bundle fails, keep ChatFallbackView readable/sendable beneath
  // the rollback card instead of an empty center column).
  fallback?: ReactNode;
  // Contract v6: which sidebar this `panel` surface is mounted in, exposed to
  // the loaded module through `usePanelLocation()`. Ignored on "detail"/
  // "shell" surfaces (see panelLocation.ts) and defaults to "left" when unset.
  panelLocation?: "left" | "right";
  // Contract v8: host-only per-detail-mount context, exposed through
  // `useDetailContext()` on surface="detail". Ignored on panel/shell.
  detailContext?: unknown;
}

export default function ArtifactMount({
  slug,
  artifactId,
  version,
  label,
  surface = "panel",
  onRolledBack,
  onDetailAvailable,
  fallback,
  panelLocation,
  detailContext,
}: ArtifactMountProps) {
  const [state, setState] = useState<MountState>({ status: "loading" });

  // Held in a ref so a caller passing an inline arrow does not re-trigger the
  // load effect on every host re-render.
  const onDetailAvailableRef = useRef(onDetailAvailable);
  onDetailAvailableRef.current = onDetailAvailable;

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    loadArtifact(version)
      .then((artifact) => {
        if (cancelled) return;
        setState({ status: "loaded", artifact });
        onDetailAvailableRef.current?.(artifact.Detail !== null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ArtifactLoadError) {
          setState({ status: "error", kind: err.kind, message: err.message });
        } else {
          setState({ status: "error", kind: "fetch", message: (err as Error)?.message ?? String(err) });
        }
        // N5 (review round 2): a stale `true` from a previous successful load
        // must not survive into a failed reload — otherwise "Open full view"
        // stays next to a FailureCard and opens a tab that also fails.
        onDetailAvailableRef.current?.(false);
      });
    return () => {
      cancelled = true;
    };
  }, [version.version_id, version.ui_sha256, version.min_host_version]);

  // D2/D3 (decision note): the module's inlined `css` export is injected as a
  // scoped <style> on mount and removed on unmount so a swapped-out artifact
  // never leaves stale rules behind.
  useEffect(() => {
    if (state.status !== "loaded" || !state.artifact.css) return;
    const styleEl = document.createElement("style");
    // D2 (decision note): named `data-y-artifact-style`, distinct from the
    // wrapping div's `data-y-artifact` scope root below -- the build's
    // `@scope ([data-y-artifact="<slug>"])` selector must have exactly one
    // match per mounted artifact, not two.
    styleEl.setAttribute("data-y-artifact-style", slug);
    styleEl.textContent = state.artifact.css;
    document.head.appendChild(styleEl);
    return () => {
      styleEl.remove();
    };
  }, [slug, state.status === "loaded" ? state.artifact.css : null]);

  const handleRenderError = useCallback((error: Error) => {
    setState({ status: "error", kind: "render", message: error.message });
  }, []);

  if (state.status === "loading") {
    return <div className="p-4 text-xs text-sol-base01">Loading {label ?? slug}…</div>;
  }

  if (state.status === "error") {
    if (fallback) {
      return (
        <div className="h-full flex flex-col min-h-0">
          <div className="shrink-0 border-b border-sol-base02">
            <FailureCard
              slug={slug}
              version={version}
              artifactId={artifactId}
              kind={state.kind}
              message={state.message}
              onRolledBack={onRolledBack}
            />
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">{fallback}</div>
        </div>
      );
    }
    return (
      <FailureCard
        slug={slug}
        version={version}
        artifactId={artifactId}
        kind={state.kind}
        message={state.message}
        onRolledBack={onRolledBack}
      />
    );
  }

  // A panel-only module still renders on the detail/shell surface: the route
  // exists for every artifact (PRD story 15), it just shows the one surface
  // the module defines.
  const Artifact =
    surface === "detail"
      ? (state.artifact.Detail ?? state.artifact.Panel)
      : surface === "shell"
        ? (state.artifact.Shell ?? state.artifact.Panel)
        : state.artifact.Panel;
  const body = (
    <div data-y-artifact={slug} data-y-artifact-surface={surface} className="h-full">
      <RenderBoundary onError={handleRenderError}>
        <Artifact />
      </RenderBoundary>
    </div>
  );
  if (surface === "panel") {
    return <PanelLocationProvider value={panelLocation ?? "left"}>{body}</PanelLocationProvider>;
  }
  if (surface === "detail") {
    return <DetailContextProvider value={detailContext ?? null}>{body}</DetailContextProvider>;
  }
  return body;
}
