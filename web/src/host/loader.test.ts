import { beforeEach, describe, expect, it, vi } from "vitest";

// loader.ts pulls authFetch from api.ts; stub it so tests control the bundle
// bytes/HTTP status without a real network call.
const { authFetchMock } = vi.hoisted(() => ({ authFetchMock: vi.fn() }));
vi.mock("../api", () => ({ API: "http://test.local", authFetch: authFetchMock }));

import { artifactImporter, loadArtifact, type ArtifactVersionRef } from "./loader";

function fakeResponse(bytes: Uint8Array, ok = true, status = 200): Response {
  return { ok, status, arrayBuffer: async () => bytes.buffer } as unknown as Response;
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes.buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function ref(overrides: Partial<ArtifactVersionRef> = {}): ArtifactVersionRef {
  return {
    version_id: "v1",
    version_no: 1,
    ui_sha256: "0".repeat(64),
    min_host_version: 1,
    ...overrides,
  };
}

describe("loadArtifact", () => {
  beforeEach(() => {
    authFetchMock.mockReset();
    vi.restoreAllMocks();
  });

  it("fails closed with version-skew before ever fetching, when min_host_version exceeds the running host contract", async () => {
    await expect(loadArtifact(ref({ version_id: "skew-version", min_host_version: 999999 }))).rejects.toMatchObject({
      kind: "version-skew",
    });
    expect(authFetchMock).not.toHaveBeenCalled();
  });

  it("rejects tampered bytes with a hash-mismatch error and never calls import()", async () => {
    const bytes = new TextEncoder().encode("export default function X(){}; export const css = '';");
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    const importSpy = vi.spyOn(artifactImporter, "importBundle");

    await expect(
      loadArtifact(ref({ version_id: "tampered-version", ui_sha256: "f".repeat(64) })),
    ).rejects.toMatchObject({ kind: "integrity" });
    expect(importSpy).not.toHaveBeenCalled();
  });

  it("surfaces a plain fetch failure distinctly from a hash mismatch", async () => {
    authFetchMock.mockResolvedValue(fakeResponse(new Uint8Array(), false, 500));
    await expect(loadArtifact(ref({ version_id: "fetch-fail-version" }))).rejects.toMatchObject({ kind: "fetch" });
  });

  it("loads a verified bundle and exposes both surfaces + inlined css", async () => {
    const bytes = new TextEncoder().encode("export const panel = 1; export const detail = 2;");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    const FakePanel = () => null;
    const FakeDetail = () => null;
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({
      panel: FakePanel,
      detail: FakeDetail,
      css: ".x{}",
    });

    const artifact = await loadArtifact(ref({ version_id: "ok-version", ui_sha256: sha256 }));
    expect(artifact.Panel).toBe(FakePanel);
    expect(artifact.Detail).toBe(FakeDetail);
    expect(artifact.css).toBe(".x{}");
  });

  // A panel-only artifact is the common case; the default export stays a
  // supported shorthand so a one-surface module needs no ceremony.
  it("accepts a bare default export as the panel, and reports no detail surface", async () => {
    const bytes = new TextEncoder().encode("export default function X(){};");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    const FakePanel = () => null;
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({ default: FakePanel, css: "" });

    const artifact = await loadArtifact(ref({ version_id: "default-only-version", ui_sha256: sha256 }));
    expect(artifact.Panel).toBe(FakePanel);
    expect(artifact.Detail).toBeNull();
  });

  it("prefers the named panel export over a default export", async () => {
    const bytes = new TextEncoder().encode("export const panel = 1; export default 2;");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    const NamedPanel = () => null;
    const DefaultExport = () => null;
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({
      panel: NamedPanel,
      default: DefaultExport,
      css: "",
    });

    const artifact = await loadArtifact(ref({ version_id: "both-version", ui_sha256: sha256 }));
    expect(artifact.Panel).toBe(NamedPanel);
  });

  // N1 (review round 2): `export const detail = null` (e.g. a computed,
  // sometimes-absent detail) means the same thing as omitting the export —
  // panel-only — not a bundle failure.
  it("accepts a null detail export as panel-only, same as an absent one", async () => {
    const bytes = new TextEncoder().encode("export const panel = 1; export const detail = null;");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({ panel: () => null, detail: null, css: "" });

    const artifact = await loadArtifact(ref({ version_id: "null-detail-version", ui_sha256: sha256 }));
    expect(artifact.Detail).toBeNull();
  });

  it("rejects a module whose detail export is not a component", async () => {
    const bytes = new TextEncoder().encode("export const panel = 1; export const detail = 'oops';");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({
      panel: () => null,
      detail: "oops",
      css: "",
    });

    await expect(loadArtifact(ref({ version_id: "bad-detail-version", ui_sha256: sha256 }))).rejects.toMatchObject({
      kind: "bundle",
    });
  });

  it("dedupes two concurrent loads of the same url+sha256 into a single fetch", async () => {
    const bytes = new TextEncoder().encode("export default function X(){};");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({ default: () => null, css: "" });

    const v = ref({ version_id: "dedup-version", ui_sha256: sha256 });
    const [a, b] = await Promise.all([loadArtifact(v), loadArtifact(v)]);
    expect(a.Panel).toBe(b.Panel);
    expect(authFetchMock).toHaveBeenCalledTimes(1);
  });

  // F5 regression (decision note): the spike's tamper test once passed for the
  // wrong reason because the cache was keyed on sha256 alone. Loading a good
  // bundle at one url, then a *different* url that merely declares the same
  // sha256, must still be independently fetched and verified, not served the
  // first url's cached (passing) module. Keying `cache` on `version.sha256`
  // alone would make this test pass identically -- it must fail if that
  // simplification is reintroduced.
  it("does not serve a cached module to a different url that declares the same sha256", async () => {
    const good = new TextEncoder().encode("export default function A(){};");
    const evil = new TextEncoder().encode("export default function B(){}; /* different bytes */");
    const sha256 = await sha256Hex(good);
    authFetchMock.mockResolvedValueOnce(fakeResponse(good)).mockResolvedValueOnce(fakeResponse(evil));
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({ default: () => null, css: "" });

    await loadArtifact(ref({ version_id: "good-version", ui_sha256: sha256 }));
    await expect(loadArtifact(ref({ version_id: "evil-version", ui_sha256: sha256 }))).rejects.toMatchObject({
      kind: "integrity",
    });
    expect(authFetchMock).toHaveBeenCalledTimes(2);
  });

  // A3 regression (decision note, confirmed empirically in the spike):
  // crypto.subtle is undefined on an insecure origin. Deleting the guard at
  // loader.ts's fail-closed check must break this test.
  it("refuses to load, rather than degrading open, when crypto.subtle is unavailable", async () => {
    const bytes = new TextEncoder().encode("export default function X(){};");
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    const importSpy = vi.spyOn(artifactImporter, "importBundle");
    vi.spyOn(globalThis, "crypto", "get").mockReturnValue({} as Crypto);

    await expect(loadArtifact(ref({ version_id: "insecure-origin-version" }))).rejects.toMatchObject({
      kind: "integrity",
    });
    expect(importSpy).not.toHaveBeenCalled();
  });

  it("reports a module that throws at top level as a bundle failure, not a fetch failure", async () => {
    const bytes = new TextEncoder().encode("throw new Error('boom');");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    vi.spyOn(artifactImporter, "importBundle").mockRejectedValue(new Error("boom"));

    await expect(loadArtifact(ref({ version_id: "eval-throw-version", ui_sha256: sha256 }))).rejects.toMatchObject({
      kind: "bundle",
    });
  });

  it("reports a module with neither a panel nor a default export as a bundle failure, not a fetch failure", async () => {
    const bytes = new TextEncoder().encode("export const notDefault = 1;");
    const sha256 = await sha256Hex(bytes);
    authFetchMock.mockResolvedValue(fakeResponse(bytes));
    vi.spyOn(artifactImporter, "importBundle").mockResolvedValue({ css: "" });

    await expect(loadArtifact(ref({ version_id: "no-default-version", ui_sha256: sha256 }))).rejects.toMatchObject({
      kind: "bundle",
    });
  });
});
