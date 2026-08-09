import { describe, expect, it } from "vitest";
import {
  hasSurface,
  isContextualFileModule,
  isPersistableTab,
  modulesFromPayload,
  mountableUiArtifacts,
  resolveShellSlot,
  shellClaimant,
} from "./artifacts";
import type { MountableModule } from "./artifacts";

describe("module payload handling", () => {
  it("returns no modules or mountable artifacts for a non-array API payload", () => {
    const payload = { detail: "Service Unavailable" };
    expect(modulesFromPayload(payload)).toEqual([]);
    expect(mountableUiArtifacts(payload)).toEqual([]);
  });

  it("keeps enabled modules with an active UI bundle", () => {
    const module = {
      module_id: "mod_1",
      slug: "todo",
      active_version_id: "ver_1",
      enabled: true,
      active_version: { ui_sha256: "abc" },
    };
    expect(mountableUiArtifacts([module])).toEqual([module]);
  });
});

function mountable(slug: string, ui_surfaces?: string): MountableModule {
  return {
    module_id: `mod_${slug}`,
    slug,
    active_version_id: `ver_${slug}`,
    enabled: true,
    active_version: {
      version_id: `ver_${slug}`,
      version_no: 1,
      ui_sha256: "abc",
      min_host_version: 1,
      ...(ui_surfaces !== undefined ? { ui_surfaces } : {}),
    },
  };
}

describe("hasSurface", () => {
  it("treats an absent ui_surfaces as panel-only", () => {
    expect(hasSurface(mountable("finance"), "panel")).toBe(true);
    expect(hasSurface(mountable("finance"), "shell")).toBe(false);
  });

  it("matches a comma-list entry", () => {
    expect(hasSurface(mountable("chat", "panel,detail,shell"), "shell")).toBe(true);
    expect(hasSurface(mountable("chat", "panel,detail,shell"), "detail")).toBe(true);
  });
});

describe("shellClaimant", () => {
  it("returns null when no module claims shell", () => {
    expect(shellClaimant([mountable("finance"), mountable("chat", "panel,detail")])).toBeNull();
  });

  it("picks the lowest-slug enabled shell claimant", () => {
    const b = mountable("bbb-shell", "panel,shell");
    const a = mountable("aaa-shell", "panel,shell");
    expect(shellClaimant([b, a])).toBe(a);
  });
});

// V4 shell-slot precedence (plan-3042-chatview.md + review F2 cold-boot guard).
// Full 2×2×2 boolean input space so logged-out+claimant cannot slip through.
describe("resolveShellSlot", () => {
  const cases: Array<{
    isLoggedIn: boolean;
    uiArtifactsLoading: boolean;
    hasShellClaimant: boolean;
    expected: "loading" | "module" | "host";
  }> = [
    // logged out: always host, regardless of loading/claimant
    { isLoggedIn: false, uiArtifactsLoading: false, hasShellClaimant: false, expected: "host" },
    { isLoggedIn: false, uiArtifactsLoading: false, hasShellClaimant: true, expected: "host" },
    { isLoggedIn: false, uiArtifactsLoading: true, hasShellClaimant: false, expected: "host" },
    { isLoggedIn: false, uiArtifactsLoading: true, hasShellClaimant: true, expected: "host" },
    // logged in + loading: wait (even with a stale claimant present)
    { isLoggedIn: true, uiArtifactsLoading: true, hasShellClaimant: false, expected: "loading" },
    { isLoggedIn: true, uiArtifactsLoading: true, hasShellClaimant: true, expected: "loading" },
    // logged in + loaded: claimant → module, else host
    { isLoggedIn: true, uiArtifactsLoading: false, hasShellClaimant: true, expected: "module" },
    { isLoggedIn: true, uiArtifactsLoading: false, hasShellClaimant: false, expected: "host" },
  ];

  it.each(cases)(
    "isLoggedIn=$isLoggedIn loading=$uiArtifactsLoading claimant=$hasShellClaimant → $expected",
    ({ isLoggedIn, uiArtifactsLoading, hasShellClaimant, expected }) => {
      expect(resolveShellSlot({ isLoggedIn, uiArtifactsLoading, hasShellClaimant })).toBe(expected);
    },
  );
});

describe("isPersistableTab", () => {
  it("persists ui: artifact tabs", () => {
    expect(isPersistableTab("ui:finance")).toBe(true);
  });

  it("persists ordinary file tabs", () => {
    expect(isPersistableTab("notes/x.md")).toBe(true);
  });

  it("excludes artifact: inline chart tabs", () => {
    expect(isPersistableTab("artifact:ab12.mermaid")).toBe(false);
  });
});

describe("isContextualFileModule", () => {
  it("is false for aggregate file modules (min_host_version < 8) and missing modules", () => {
    expect(isContextualFileModule(null)).toBe(false);
    expect(isContextualFileModule({
      module_id: "m",
      slug: "file",
      active_version_id: "v",
      enabled: true,
      active_version: { version_id: "v", version_no: 10, ui_sha256: "a".repeat(64), min_host_version: 7 },
    } as MountableModule)).toBe(false);
  });

  it("is true when the active file UI requires host contract v8+", () => {
    expect(isContextualFileModule({
      module_id: "m",
      slug: "file",
      active_version_id: "v",
      enabled: true,
      active_version: { version_id: "v", version_no: 11, ui_sha256: "a".repeat(64), min_host_version: 8 },
    } as MountableModule)).toBe(true);
  });
});
