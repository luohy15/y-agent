// Anonymous lookup of one allowlisted demo (todo 3158 H3).
// `GET /api/module/public-demo/{key}` returns the minimal projection H1
// defines: enough to integrity-check a bundle, and nothing about inventory,
// ownership, storage keys, API metadata, or dispatch scope.
import { API } from "../api";
import type { ArtifactVersionRef } from "../host/loader";
import { allowedDemoFetch } from "./runtime";

export interface PublicDemoRef extends ArtifactVersionRef {
  demo_key: string;
  slug: string;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Resolve the active public version for `key`, or throw. Every failure —
 * ineligible (404), unreachable, or a body that does not match the expected
 * shape — is one generic rejection: the caller renders the same unavailable
 * state either way, so the page never reveals which case it hit. */
export async function fetchPublicDemo(key: string): Promise<PublicDemoRef> {
  const url = `${API}/api/module/public-demo/${encodeURIComponent(key)}`;
  const res = await allowedDemoFetch(url);
  if (!res.ok) throw new Error(`demo lookup failed (HTTP ${res.status})`);
  const body = (await res.json()) as Partial<PublicDemoRef> | null;
  if (
    !body ||
    body.demo_key !== key ||
    !isNonEmptyString(body.slug) ||
    !isNonEmptyString(body.version_id) ||
    !isNonEmptyString(body.ui_sha256) ||
    typeof body.min_host_version !== "number"
  ) {
    throw new Error("demo lookup returned an unexpected payload");
  }
  return {
    demo_key: key,
    slug: body.slug,
    version_id: body.version_id,
    version_no: typeof body.version_no === "number" ? body.version_no : 0,
    ui_sha256: body.ui_sha256,
    min_host_version: body.min_host_version,
  };
}

/** Resolve all showcase slots concurrently. A failed projection is isolated to
 * its own key so the shell can keep every other eligible surface interactive. */
export async function fetchPublicDemos(keys: readonly string[]): Promise<Map<string, PublicDemoRef | null>> {
  const resolved = await Promise.all(
    keys.map(async (key) => {
      try {
        return [key, await fetchPublicDemo(key)] as const;
      } catch (err) {
        console.error("[y-demo] lookup failed", err);
        return [key, null] as const;
      }
    }),
  );
  return new Map(resolved);
}
