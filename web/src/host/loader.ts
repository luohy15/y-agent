// Artifact bundle loader (plan sub-task S6, pages/plan-2412-ui-dynamic-artifacts.md):
// fetch the bundle -> crypto.subtle sha256 verify -> Blob -> blob: import()
// -> validate the module's surfaces. See
// pages/decision-2412-runtime-contract.md for the load-bearing findings this
// implements (A3 fail-closed, F5 cache key) and
// pages/decision-2412-module-shape.md for the panel+detail module contract.
//
// Public delivery (todo 3158 H2 / pages/plan-3158-public-module-demos.md):
// loadDemoArtifact uses GET /api/module/public-bundle/{version_id} without an
// Authorization header and requires a component `export const demo`. Production
// loadArtifact still accepts older bundles that omit demo.
import type { ComponentType } from "react";
import { API, authFetch } from "../api";
import { HOST_CONTRACT_VERSION } from "./contract";

export interface ArtifactVersionRef {
  version_id: string;
  version_no: number;
  ui_sha256: string;
  min_host_version: number;
  // Comma list drawn from {panel, detail, shell} (V1, todo 3042); absent on
  // an older host response, so callers should treat undefined as "panel".
  ui_surfaces?: string;
}

// One artifact is one pluggable UI module defining up to three surfaces:
//   export const panel   -> required, the ~280px left sidebar surface
//   export const detail  -> optional, the center / full-width surface
//   export const shell   -> optional, the persistent center-column surface
//                            claimed via module_version.ui_surfaces (V1)
//   export const demo    -> optional in production; required for public demos
// `export default <Component>` is the shorthand for a panel-only artifact.
export interface LoadedArtifact {
  Panel: ComponentType<Record<string, never>>;
  Detail: ComponentType<Record<string, never>> | null;
  Shell: ComponentType<Record<string, never>> | null;
  // Present only when the bundle exports a component `demo`. Production mounts
  // ignore it; public DemoMount requires it and never falls back to panel.
  Demo: ComponentType<Record<string, never>> | null;
  css: string;
}

export type ArtifactLoadErrorKind = "fetch" | "integrity" | "version-skew" | "bundle";

export class ArtifactLoadError extends Error {
  kind: ArtifactLoadErrorKind;
  constructor(kind: ArtifactLoadErrorKind, message: string) {
    super(message);
    this.name = "ArtifactLoadError";
    this.kind = kind;
  }
}

// Public-delivery fetch seam (todo 3158 H3): the demo runtime denies global
// `fetch` before any module bytes are imported, so it captures the origin
// fetch first and pins it here (web/src/demo/runtime.ts). The default keeps a
// plain host — one that never installs a demo runtime — working unchanged.
export const publicBundleFetcher = {
  fetch(url: string): Promise<Response> {
    return fetch(url, { credentials: "omit" });
  },
};

// Indirection so tests can substitute a fake dynamic import: a `blob:` URL
// import() only resolves in a real browser, not under vitest/jsdom.
export const artifactImporter = {
  importBundle(url: string): Promise<ArtifactModule> {
    return import(/* @vite-ignore */ url);
  },
};

interface ArtifactModule {
  panel?: unknown;
  detail?: unknown;
  shell?: unknown;
  demo?: unknown;
  default?: unknown;
  css?: unknown;
}

type BundleDelivery = "authenticated" | "public";

function bundleUrl(versionId: string, delivery: BundleDelivery): string {
  const path =
    delivery === "public"
      ? `/api/module/public-bundle/${encodeURIComponent(versionId)}`
      : `/api/module/bundle/${encodeURIComponent(versionId)}`;
  return `${API}${path}`;
}

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// F5 (decision note): key the cache on url+sha256, not sha256 alone. Keying
// on the hash alone would let a bundle that FAILS verification for one url be
// served the cached module of a different bundle that happens to share a
// hash (or, more concretely, serve a stale passing entry for a url whose
// current bytes no longer verify). Public and authenticated URLs are distinct
// strings, so their caches stay separated even for the same version_id/hash.
const cache = new Map<string, Promise<LoadedArtifact>>();

export function loadArtifact(version: ArtifactVersionRef): Promise<LoadedArtifact> {
  return loadBundle(version, "authenticated");
}

// Public demo path (todo 3158 H2): same integrity/version-floor pipeline, but
// fetches the unauthenticated public-bundle URL and requires `export const demo`.
export function loadDemoArtifact(version: ArtifactVersionRef): Promise<LoadedArtifact> {
  return loadBundle(version, "public");
}

function loadBundle(
  version: ArtifactVersionRef,
  delivery: BundleDelivery,
): Promise<LoadedArtifact> {
  // Default an absent/null field to 1 (the lowest real contract version)
  // rather than letting `undefined > N` silently evaluate to false and pass
  // the gate open.
  const minHostVersion = version.min_host_version ?? 1;
  if (minHostVersion > HOST_CONTRACT_VERSION) {
    return Promise.reject(
      new ArtifactLoadError(
        "version-skew",
        `This artifact requires host contract v${minHostVersion}; the running host is v${HOST_CONTRACT_VERSION}.`,
      ),
    );
  }

  const url = bundleUrl(version.version_id, delivery);
  const key = `${url}::${version.ui_sha256}`;
  const cached = cache.get(key);
  if (cached) return cached;

  const promise = fetchAndVerify(url, version.ui_sha256, delivery).catch((err) => {
    // Don't pin a failed load in the cache: a retry (e.g. after the user fixes
    // a plain-HTTP origin, or a transient network blip) should refetch rather
    // than replay the same rejection forever.
    cache.delete(key);
    throw err;
  });
  cache.set(key, promise);
  return promise;
}

async function fetchBundle(url: string, delivery: BundleDelivery): Promise<Response> {
  if (delivery === "public") {
    // Never attach Authorization: public demos must not leak ambient identity
    // into the origin request, even if a JWT happens to sit in localStorage.
    return publicBundleFetcher.fetch(url);
  }
  return authFetch(url);
}

async function fetchAndVerify(
  url: string,
  expectedSha256: string,
  delivery: BundleDelivery,
): Promise<LoadedArtifact> {
  let res: Response;
  try {
    res = await fetchBundle(url, delivery);
  } catch (err) {
    throw new ArtifactLoadError("fetch", `Could not reach the bundle: ${(err as Error).message ?? err}`);
  }
  if (!res.ok) {
    throw new ArtifactLoadError("fetch", `Bundle fetch failed (HTTP ${res.status}).`);
  }
  const bytes = await res.arrayBuffer();

  // A3 (decision note, confirmed empirically): crypto.subtle is undefined on
  // an insecure origin (plain-HTTP LAN IP, non-localhost). Fail closed rather
  // than mount a bundle whose integrity cannot be checked.
  if (!globalThis.crypto?.subtle) {
    throw new ArtifactLoadError(
      "integrity",
      "Bundle integrity cannot be verified in this context (crypto.subtle is unavailable; requires HTTPS or localhost).",
    );
  }
  const digest = toHex(await globalThis.crypto.subtle.digest("SHA-256", bytes));
  if (digest !== (expectedSha256 ?? "").trim().toLowerCase()) {
    throw new ArtifactLoadError("integrity", "Bundle failed integrity check (sha256 mismatch).");
  }

  const blob = new Blob([bytes], { type: "text/javascript" });
  const blobUrl = URL.createObjectURL(blob);
  let mod: ArtifactModule;
  try {
    mod = await artifactImporter.importBundle(blobUrl);
  } catch (err) {
    // A module that throws at top level is an artifact bug, not a network
    // problem -- kept out of "fetch" so the failure card blames the bundle.
    throw new ArtifactLoadError("bundle", `Bundle failed to evaluate: ${(err as Error).message ?? err}`);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }

  // `panel` is the canonical name; a bare default export is the panel-only
  // shorthand the starter template documents.
  const panel = typeof mod.panel === "function" ? mod.panel : mod.default;
  if (typeof panel !== "function") {
    throw new ArtifactLoadError(
      "bundle",
      "Bundle did not export a panel component (expected `export const panel` or a default export).",
    );
  }
  // N1 (review round 2): `null` is accepted alongside `undefined` — an author
  // computing the export (`export const detail = FLAG ? Wide : null`) should
  // get a panel-only artifact, not a bundle failure, for a value that means
  // exactly the same thing as omitting the export.
  if (mod.detail !== undefined && mod.detail !== null && typeof mod.detail !== "function") {
    throw new ArtifactLoadError("bundle", "Bundle exported a `detail` that is not a component.");
  }
  // Same null-tolerant shape as `detail` above (V1, todo 3042).
  if (mod.shell !== undefined && mod.shell !== null && typeof mod.shell !== "function") {
    throw new ArtifactLoadError("bundle", "Bundle exported a `shell` that is not a component.");
  }
  // Public demos require a real component. Authenticated production loading
  // ignores a non-function `demo` (the name was unreserved before H2) so a
  // previously active bundle that happens to export a helper/fixture under
  // that name still mounts panel/detail/shell unchanged.
  if (delivery === "public" && typeof mod.demo !== "function") {
    throw new ArtifactLoadError(
      "bundle",
      "Bundle did not export a demo component (expected `export const demo`).",
    );
  }

  return {
    Panel: panel as LoadedArtifact["Panel"],
    Detail: (typeof mod.detail === "function" ? mod.detail : null) as LoadedArtifact["Detail"],
    Shell: (typeof mod.shell === "function" ? mod.shell : null) as LoadedArtifact["Shell"],
    Demo: (typeof mod.demo === "function" ? mod.demo : null) as LoadedArtifact["Demo"],
    css: typeof mod.css === "string" ? mod.css : "",
  };
}
