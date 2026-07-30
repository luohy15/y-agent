import { describe, expect, it } from "vitest";
import { buildActivityPanelItems, BUILT_IN_PANEL_ITEMS } from "./ActivityBar";
import type { UiArtifact } from "../host/artifacts";

function artifact(slug: string, enabled: boolean, active = true): UiArtifact {
  return {
    artifact_id: `artifact-${slug}`,
    slug,
    kind: "panel",
    active_version_id: active ? `version-${slug}` : null,
    enabled,
    active_version: active ? {
      version_id: `version-${slug}`,
      version_no: 1,
      sha256: "a".repeat(64),
      min_host_version: 1,
      label: `${slug} label`,
      icon: "box",
    } : null,
  };
}

describe("buildActivityPanelItems", () => {
  it("appends enabled published artifacts and excludes disabled or unpublished artifacts", () => {
    const items = buildActivityPanelItems([
      artifact("enabled", true),
      artifact("disabled", false),
      artifact("unpublished", true, false),
    ]);

    expect(items.map((item) => item.key)).toEqual([
      ...BUILT_IN_PANEL_ITEMS.map((item) => item.key),
      "artifact:enabled",
    ]);
    expect(items[items.length - 1]?.label).toBe("enabled label");
  });

  // F1 (pages/review-2412-module-shape.md): the built-in Finance panel is
  // withheld only while a mountable `finance` artifact actually replaces it,
  // so the built-in is never fully unreachable (e.g. during the deploy window
  // before the artifact is republished, or if it fails to load).
  it("keeps the built-in finance panel when no finance artifact is present", () => {
    expect(buildActivityPanelItems([]).map((item) => item.key)).toContain("finance");
    expect(buildActivityPanelItems([artifact("other", true)]).map((item) => item.key)).toContain("finance");
  });

  it("keeps the built-in finance panel when the finance artifact is disabled or unpublished", () => {
    expect(buildActivityPanelItems([artifact("finance", false)]).map((item) => item.key)).toContain("finance");
    expect(buildActivityPanelItems([artifact("finance", true, false)]).map((item) => item.key)).toContain("finance");
  });

  it("hides the built-in finance panel only once a mountable finance artifact replaces it", () => {
    const items = buildActivityPanelItems([artifact("finance", true)]);
    expect(items.map((item) => item.key)).not.toContain("finance");
    expect(items.map((item) => item.key)).toContain("artifact:finance");
  });
});
