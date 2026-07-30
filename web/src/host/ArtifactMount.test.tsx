import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { authFetchMock } = vi.hoisted(() => ({ authFetchMock: vi.fn() }));
vi.mock("../api", () => ({ API: "http://test.local", authFetch: authFetchMock }));

const { loadArtifactMock } = vi.hoisted(() => ({ loadArtifactMock: vi.fn() }));
vi.mock("./loader", async () => {
  const actual = await vi.importActual<typeof import("./loader")>("./loader");
  return { ...actual, loadArtifact: loadArtifactMock };
});

import { ArtifactLoadError, type ArtifactVersionRef } from "./loader";
import ArtifactMount from "./ArtifactMount";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

async function flushMicrotasks() {
  for (let i = 0; i < 6; i++) await Promise.resolve();
}

function ref(overrides: Partial<ArtifactVersionRef> = {}): ArtifactVersionRef {
  return { version_id: "v1", version_no: 3, sha256: "a".repeat(64), min_host_version: 1, ...overrides };
}

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
}

describe("ArtifactMount", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    authFetchMock.mockReset();
    loadArtifactMock.mockReset();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.querySelectorAll("[data-y-artifact-style]").forEach((el) => el.remove());
  });

  it("renders a hash-mismatch card naming the slug + version, with a rollback action", async () => {
    loadArtifactMock.mockRejectedValue(
      new ArtifactLoadError("integrity", "Bundle failed integrity check (sha256 mismatch)."),
    );
    const { container, root } = renderClient();

    await act(async () => {
      root.render(React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref({ version_no: 5 }) }));
      await flushMicrotasks();
    });

    expect(container.textContent).toContain('"demo" (v5)');
    expect(container.textContent).toContain("Integrity check failed");
    expect(container.textContent).toContain("Bundle failed integrity check (sha256 mismatch).");
    expect(container.textContent).toContain("Roll back to previous version");

    act(() => root.unmount());
    container.remove();
  });

  it("renders a distinct version-skew card for a host-version-incompatible artifact", async () => {
    loadArtifactMock.mockRejectedValue(new ArtifactLoadError("version-skew", "Requires a newer host."));
    const { container, root } = renderClient();

    await act(async () => {
      root.render(React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref() }));
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("Incompatible host version");

    act(() => root.unmount());
    container.remove();
  });

  it("renders a distinct bundle-broken card for a module that fails to evaluate, not a network heading", async () => {
    loadArtifactMock.mockRejectedValue(new ArtifactLoadError("bundle", "Bundle failed to evaluate: boom"));
    const { container, root } = renderClient();

    await act(async () => {
      root.render(React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref() }));
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("Bundle is broken");
    expect(container.textContent).not.toContain("Failed to load");

    act(() => root.unmount());
    container.remove();
  });

  it("contains a render throw in one artifact while a sibling panel keeps rendering", async () => {
    function Boom(): React.ReactElement {
      throw new Error("artifact bug");
    }
    function Fine(): React.ReactElement {
      return React.createElement("span", null, "sibling still here");
    }
    loadArtifactMock.mockImplementation((version: ArtifactVersionRef) =>
      Promise.resolve({ Component: version.version_id === "boom" ? Boom : Fine, css: "" }),
    );

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(
          "div",
          null,
          React.createElement(ArtifactMount, { slug: "broken", artifactId: "art1", version: ref({ version_id: "boom" }) }),
          React.createElement(ArtifactMount, { slug: "ok", artifactId: "art2", version: ref({ version_id: "fine" }) }),
        ),
      );
      await flushMicrotasks();
    });

    expect(container.textContent).toContain('"broken" (v3)');
    expect(container.textContent).toContain("Crashed while rendering");
    expect(container.textContent).toContain("sibling still here");

    act(() => root.unmount());
    container.remove();
  });

  it("injects the module's css as a scoped <style data-y-artifact-style> on mount and removes it on unmount", async () => {
    loadArtifactMock.mockResolvedValue({
      Component: () => React.createElement("span", null, "hi"),
      css: ".demo{color:red}",
    });
    const { container, root } = renderClient();

    await act(async () => {
      root.render(React.createElement(ArtifactMount, { slug: "styled", artifactId: "art1", version: ref() }));
      await flushMicrotasks();
    });

    const styleEl = document.querySelector('style[data-y-artifact-style="styled"]');
    expect(styleEl?.textContent).toBe(".demo{color:red}");
    // The wrapping mount div is a separate scope root; the two attributes
    // must not collide (decision note D2 names them distinctly).
    expect(container.querySelector('[data-y-artifact="styled"]')).not.toBeNull();

    act(() => root.unmount());
    expect(document.querySelector('style[data-y-artifact-style="styled"]')).toBeNull();
    container.remove();
  });

  it("rolls back on click: posts artifact_id + from_version_id and calls onRolledBack instead of reloading", async () => {
    loadArtifactMock.mockRejectedValue(new ArtifactLoadError("fetch", "Bundle fetch failed (HTTP 500)."));
    authFetchMock.mockResolvedValue(jsonResponse(200, { version_id: "v-prev" }));
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload: reloadSpy }, writable: true });
    const onRolledBack = vi.fn();

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, {
          slug: "demo",
          artifactId: "art-xyz",
          version: ref({ version_id: "v-current" }),
          onRolledBack,
        }),
      );
      await flushMicrotasks();
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    expect(authFetchMock).toHaveBeenCalledWith(
      "http://test.local/api/ui/rollback",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse((authFetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual({ artifact_id: "art-xyz", from_version_id: "v-current" });
    expect(onRolledBack).toHaveBeenCalledTimes(1);
    expect(reloadSpy).not.toHaveBeenCalled();

    act(() => root.unmount());
    container.remove();
  });

  it("falls back to a confirmed reload (never unconditional) when no onRolledBack is wired", async () => {
    loadArtifactMock.mockRejectedValue(new ArtifactLoadError("fetch", "Bundle fetch failed (HTTP 500)."));
    authFetchMock.mockResolvedValue(jsonResponse(200, { version_id: "v-prev" }));
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload: reloadSpy }, writable: true });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(ArtifactMount, { slug: "demo", artifactId: "art-xyz", version: ref() }));
      await flushMicrotasks();
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    expect(confirmSpy).toHaveBeenCalled();
    expect(reloadSpy).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });
    expect(reloadSpy).toHaveBeenCalled();

    act(() => root.unmount());
    container.remove();
  });

  it("treats a 409 as a conflict, not a demotion: does not reload and calls onRolledBack to refresh state", async () => {
    loadArtifactMock.mockRejectedValue(new ArtifactLoadError("fetch", "Bundle fetch failed (HTTP 500)."));
    authFetchMock.mockResolvedValue(jsonResponse(409, { detail: { reason: "stale_version", active_version_id: "v-newer" } }));
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload: reloadSpy }, writable: true });
    const onRolledBack = vi.fn();

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, {
          slug: "demo",
          artifactId: "art-xyz",
          version: ref({ version_id: "v-stale" }),
          onRolledBack,
        }),
      );
      await flushMicrotasks();
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("A newer version is already active");
    expect(reloadSpy).not.toHaveBeenCalled();
    expect(onRolledBack).toHaveBeenCalledTimes(1);

    act(() => root.unmount());
    container.remove();
  });

  it("surfaces the server's error detail instead of a generic message on rollback failure", async () => {
    loadArtifactMock.mockRejectedValue(new ArtifactLoadError("fetch", "Bundle fetch failed (HTTP 500)."));
    authFetchMock.mockResolvedValue(jsonResponse(404, { detail: "Nothing to roll back to" }));

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(ArtifactMount, { slug: "demo", artifactId: "art-xyz", version: ref() }));
      await flushMicrotasks();
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("Nothing to roll back to");
    expect((container.querySelector("button") as HTMLButtonElement).disabled).toBe(false);

    act(() => root.unmount());
    container.remove();
  });
});
