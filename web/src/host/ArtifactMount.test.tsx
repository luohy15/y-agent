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
import { usePanelLocation } from "./panelLocation";

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
  return { version_id: "v1", version_no: 3, ui_sha256: "a".repeat(64), min_host_version: 1, ...overrides };
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

  // V4 (todo 3042): a failed shell claimant must still leave a usable chat
  // surface (ChatFallbackView) under the FailureCard, not an empty column.
  it("renders optional fallback content beneath the FailureCard on load error", async () => {
    loadArtifactMock.mockRejectedValue(
      new ArtifactLoadError("integrity", "Bundle failed integrity check (sha256 mismatch)."),
    );
    const { container, root } = renderClient();

    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, {
          slug: "chat",
          artifactId: "art1",
          version: ref({ version_no: 2 }),
          surface: "shell" as const,
          fallback: React.createElement("div", null, "fallback chat surface"),
        }),
      );
      await flushMicrotasks();
    });

    expect(container.textContent).toContain('"chat" (v2)');
    expect(container.textContent).toContain("Integrity check failed");
    expect(container.textContent).toContain("Roll back to previous version");
    expect(container.textContent).toContain("fallback chat surface");

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
      Promise.resolve({ Panel: version.version_id === "boom" ? Boom : Fine, Detail: null, css: "" }),
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

  // One artifact = one module with up to three surfaces: the same version
  // renders its panel in the sidebar and its detail in the center surface,
  // rather than occupying two sidebar entries.
  it("renders the panel surface by default and the detail surface when asked", async () => {
    loadArtifactMock.mockResolvedValue({
      Panel: () => React.createElement("span", null, "panel surface"),
      Detail: () => React.createElement("span", null, "detail surface"),
      css: "",
    });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(
          "div",
          null,
          React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref() }),
          React.createElement(ArtifactMount, {
            slug: "demo",
            artifactId: "art1",
            version: ref(),
            surface: "detail" as const,
          }),
        ),
      );
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("panel surface");
    expect(container.textContent).toContain("detail surface");
    expect(container.querySelector('[data-y-artifact-surface="panel"]')?.textContent).toBe("panel surface");
    expect(container.querySelector('[data-y-artifact-surface="detail"]')?.textContent).toBe("detail surface");

    act(() => root.unmount());
    container.remove();
  });

  // W3 (todo 3046, contract v6): both sidebar mounts of the same `panel`
  // export must observe their own host-provided location.
  it("threads panelLocation to a probe Panel via usePanelLocation, defaulting left when unspecified", async () => {
    function Probe() {
      return React.createElement("span", null, usePanelLocation());
    }
    loadArtifactMock.mockResolvedValue({ Panel: Probe, Detail: null, css: "" });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(
          "div",
          null,
          React.createElement("div", { "data-testid": "left" },
            React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), panelLocation: "left" }),
          ),
          React.createElement("div", { "data-testid": "right" },
            React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), panelLocation: "right" }),
          ),
          React.createElement("div", { "data-testid": "unspecified" },
            React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref() }),
          ),
        ),
      );
      await flushMicrotasks();
    });

    expect(container.querySelector('[data-testid="left"]')?.textContent).toBe("left");
    expect(container.querySelector('[data-testid="right"]')?.textContent).toBe("right");
    expect(container.querySelector('[data-testid="unspecified"]')?.textContent).toBe("left");

    act(() => root.unmount());
    container.remove();
  });

  // A detail/shell mount must not masquerade as the right panel even if a
  // caller passed panelLocation="right" for it — only the panel surface wires
  // the provider (binding decision 6/10).
  it("ignores panelLocation on detail and shell surfaces", async () => {
    function Probe() {
      return React.createElement("span", null, usePanelLocation());
    }
    loadArtifactMock.mockResolvedValue({ Panel: () => null, Detail: Probe, Shell: Probe, css: "" });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(
          "div",
          null,
          React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), surface: "detail" as const, panelLocation: "right" }),
          React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), surface: "shell" as const, panelLocation: "right" }),
        ),
      );
      await flushMicrotasks();
    });

    expect(container.querySelectorAll("span").length).toBe(2);
    for (const span of container.querySelectorAll("span")) {
      expect(span.textContent).toBe("left");
    }

    act(() => root.unmount());
    container.remove();
  });

  // V1 (todo 3042): the same one-artifact-many-surfaces contract extends to
  // `shell`, the persistent center-column slot.
  it("renders the shell surface when asked", async () => {
    loadArtifactMock.mockResolvedValue({
      Panel: () => React.createElement("span", null, "panel surface"),
      Detail: null,
      Shell: () => React.createElement("span", null, "shell surface"),
      css: "",
    });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), surface: "shell" as const }),
      );
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("shell surface");
    expect(container.querySelector('[data-y-artifact-surface="shell"]')?.textContent).toBe("shell surface");

    act(() => root.unmount());
    container.remove();
  });

  it("falls back to the panel on the shell surface for a module without a shell export", async () => {
    loadArtifactMock.mockResolvedValue({
      Panel: () => React.createElement("span", null, "only surface"),
      Detail: null,
      Shell: null,
      css: "",
    });

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), surface: "shell" as const }),
      );
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("only surface");

    act(() => root.unmount());
    container.remove();
  });

  it("falls back to the panel on the detail surface for a panel-only module, and reports no detail", async () => {
    loadArtifactMock.mockResolvedValue({
      Panel: () => React.createElement("span", null, "only surface"),
      Detail: null,
      css: "",
    });
    const onDetailAvailable = vi.fn();

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, {
          slug: "demo",
          artifactId: "art1",
          version: ref(),
          surface: "detail" as const,
          onDetailAvailable,
        }),
      );
      await flushMicrotasks();
    });

    expect(container.textContent).toContain("only surface");
    expect(onDetailAvailable).toHaveBeenCalledWith(false);

    act(() => root.unmount());
    container.remove();
  });

  it("reports a detail surface to the host once the module loads", async () => {
    loadArtifactMock.mockResolvedValue({
      Panel: () => React.createElement("span", null, "panel"),
      Detail: () => React.createElement("span", null, "detail"),
      css: "",
    });
    const onDetailAvailable = vi.fn();

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, { slug: "demo", artifactId: "art1", version: ref(), onDetailAvailable }),
      );
      await flushMicrotasks();
    });

    expect(onDetailAvailable).toHaveBeenCalledWith(true);

    act(() => root.unmount());
    container.remove();
  });

  // N5 (review round 2): a stale `true` from the previous successful load
  // must not survive a failed reload of a newer version, or "Open full view"
  // would sit next to a FailureCard and open a tab that also fails.
  it("clears a previously-reported detail surface when a subsequent reload fails", async () => {
    loadArtifactMock
      .mockResolvedValueOnce({
        Panel: () => React.createElement("span", null, "panel"),
        Detail: () => React.createElement("span", null, "detail"),
        css: "",
      })
      .mockRejectedValueOnce(new ArtifactLoadError("fetch", "Bundle fetch failed (HTTP 500)."));
    const onDetailAvailable = vi.fn();

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, {
          slug: "demo",
          artifactId: "art1",
          version: ref({ version_id: "v1" }),
          onDetailAvailable,
        }),
      );
      await flushMicrotasks();
    });
    expect(onDetailAvailable).toHaveBeenLastCalledWith(true);

    await act(async () => {
      root.render(
        React.createElement(ArtifactMount, {
          slug: "demo",
          artifactId: "art1",
          version: ref({ version_id: "v2" }),
          onDetailAvailable,
        }),
      );
      await flushMicrotasks();
    });
    expect(onDetailAvailable).toHaveBeenLastCalledWith(false);

    act(() => root.unmount());
    container.remove();
  });

  it("injects the module's css as a scoped <style data-y-artifact-style> on mount and removes it on unmount", async () => {
    loadArtifactMock.mockResolvedValue({
      Panel: () => React.createElement("span", null, "hi"),
      Detail: null,
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

  it("rolls back on click: posts module_id + from_version_id and calls onRolledBack instead of reloading", async () => {
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
      "http://test.local/api/module/rollback",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse((authFetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual({ module_id: "art-xyz", from_version_id: "v-current" });
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
