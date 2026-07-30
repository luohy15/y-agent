import { createHash } from "node:crypto";
import path from "node:path";
import { expect, test } from "playwright/test";

const bundle = `
const React = globalThis.__Y_HOST__.modules.react;
export const css = '[data-y-artifact="smoke"] .smoke-card { border: 1px solid #268bd2; border-radius: 8px; padding: 16px; background: #002b36; color: #93a1a1; }';
export default function SmokeArtifact() {
  const [count, setCount] = React.useState(0);
  return React.createElement('section', { className: 'smoke-card' },
    React.createElement('h2', null, 'Blob import mounted'),
    React.createElement('p', null, 'One default export, two host surfaces.'),
    React.createElement('button', { type: 'button', onClick: () => setCount((value) => value + 1) }, 'Count ' + count),
  );
}
`;
const sha256 = createHash("sha256").update(bundle).digest("hex");
const screenshotDir = "/Users/roy/luohy15/assets/screenshots";

test("imports a verified blob bundle into the sidebar and the restored detail tab", async ({ page }) => {
  let bundleFetches = 0;
  await page.addInitScript(() => {
    localStorage.setItem("jwt_token", "playwright-token");
    localStorage.setItem("user_email", "playwright@example.com");
    localStorage.setItem("sidebarPanel", "artifact:smoke");
    localStorage.setItem("desktopSidebarOpen", "true");
    localStorage.setItem("activityBarOrder", JSON.stringify(["todo", "artifact:smoke", "notes"]));
    localStorage.setItem("openFiles", JSON.stringify(["ui:smoke"]));
    localStorage.setItem("activeFile", "ui:smoke");
    localStorage.setItem("chatHide", "true");
  });

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/ui/list") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([{
          artifact_id: "artifact-smoke",
          slug: "smoke",
          kind: "panel",
          active_version_id: "version-smoke",
          enabled: true,
          active_version: {
            version_id: "version-smoke",
            artifact_id: "artifact-smoke",
            version_no: 1,
            sha256,
            storage_key: `ui/artifact-smoke/${sha256}.js`,
            label: "Smoke UI",
            icon: "box",
            min_host_version: 1,
          },
        }]),
      });
      return;
    }
    if (url.pathname === "/api/ui/artifact/version-smoke/bundle") {
      bundleFetches += 1;
      await route.fulfill({ contentType: "text/javascript", body: bundle });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: "[]" });
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });

  const sidebarMount = page.locator('[data-ui-artifact-sidebar="smoke"]');
  const routeMount = page.locator('[data-ui-artifact-route="smoke"]');
  await expect(sidebarMount.getByText("Blob import mounted")).toBeVisible();
  await expect(routeMount.getByText("Blob import mounted")).toBeVisible();
  const visiblePanelOrder = await page.locator("[data-sidebar-panel]:visible").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-sidebar-panel")),
  );
  expect(visiblePanelOrder.indexOf("todo")).toBeLessThan(visiblePanelOrder.indexOf("artifact:smoke"));
  expect(visiblePanelOrder.indexOf("artifact:smoke")).toBeLessThan(visiblePanelOrder.indexOf("notes"));
  await routeMount.getByRole("button", { name: "Count 0" }).click();
  await expect(routeMount.getByRole("button", { name: "Count 1" })).toBeVisible();
  expect(bundleFetches).toBe(1);

  await page.screenshot({
    path: path.join(screenshotDir, "ui-mount-2412-sidebar.png"),
    clip: { x: 0, y: 0, width: 330, height: 900 },
  });
  await routeMount.screenshot({
    path: path.join(screenshotDir, "ui-mount-2412-route.png"),
  });
});
