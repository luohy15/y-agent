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
});
