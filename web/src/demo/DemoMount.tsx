// Public demo mount (todo 3158 H3). Deliberately NOT ArtifactMount:
//
//  - it mounts `demo` and only `demo`, never substituting panel/detail/shell,
//    so a bundle without a public entrypoint fails closed instead of exposing
//    an authenticated production surface to an anonymous visitor;
//  - every failure renders one generic state with no version, slug, message,
//    rollback action, management call, or sign-in path;
//  - it refuses to load at all unless the restricted runtime is installed.
import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { loadDemoArtifact, type ArtifactVersionRef, type LoadedArtifact } from "../host/loader";
import { isPublicDemoRuntimeInstalled } from "./runtime";
import { DemoUnavailable } from "./DemoStates";

type MountState =
  | { status: "loading" }
  | { status: "loaded"; artifact: LoadedArtifact }
  | { status: "failed" };

interface RenderBoundaryProps {
  children: ReactNode;
  onError: () => void;
}

// Class component: `componentDidCatch` is the only way to catch a render throw
// from `children`. A throw inside the demo becomes the same generic state as a
// failed load — never a partially rendered module surface.
class RenderBoundary extends Component<RenderBoundaryProps, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[y-demo] render error", error, info);
    this.props.onError();
  }

  render() {
    return this.state.hasError ? null : this.props.children;
  }
}

export default function DemoMount({ slug, version }: { slug: string; version: ArtifactVersionRef }) {
  const [state, setState] = useState<MountState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    if (!isPublicDemoRuntimeInstalled()) {
      // Belt-and-braces: module bytes must never be imported into a page that
      // still has authenticated fetch, durable storage, and the full SDK.
      console.error("[y-demo] refusing to load a bundle without the restricted runtime");
      setState({ status: "failed" });
      return;
    }
    loadDemoArtifact(version)
      .then((artifact) => {
        if (cancelled) return;
        // The loader already requires a component `demo` on the public path;
        // this keeps the fail-closed contract local and total.
        setState(artifact.Demo ? { status: "loaded", artifact } : { status: "failed" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        console.error("[y-demo] load failed", err);
        setState({ status: "failed" });
      });
    return () => {
      cancelled = true;
    };
  }, [version.version_id, version.ui_sha256, version.min_host_version]);

  // Same scoped-style contract as ArtifactMount: the bundle's inlined `css`
  // lives in a <style> tag that is removed when the demo unmounts.
  useEffect(() => {
    if (state.status !== "loaded" || !state.artifact.css) return;
    const styleEl = document.createElement("style");
    styleEl.setAttribute("data-y-artifact-style", slug);
    styleEl.textContent = state.artifact.css;
    document.head.appendChild(styleEl);
    return () => {
      styleEl.remove();
    };
  }, [slug, state.status === "loaded" ? state.artifact.css : null]);

  if (state.status === "loading") {
    return <div className="p-4 text-xs text-sol-base01">Loading demo…</div>;
  }
  if (state.status === "failed") {
    return <DemoUnavailable />;
  }

  const Demo = state.artifact.Demo!;
  return (
    <div data-y-artifact={slug} data-y-artifact-surface="demo" className="h-full">
      <RenderBoundary onError={() => setState({ status: "failed" })}>
        <Demo />
      </RenderBoundary>
    </div>
  );
}
