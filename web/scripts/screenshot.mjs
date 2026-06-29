// Auto-generate doc panel screenshots.
//
// Serves the web app (Vite dev server), loads the unauthenticated /showcase
// route (which mocks window.fetch and renders the REAL panel components against
// seeded fixtures), then captures one PNG per `[data-screenshot]` element with
// headless Chromium into /Users/roy/luohy15/assets/images/<name>.png.
//
// Usage: node web/scripts/screenshot.mjs
//
// Requires the `playwright` devDependency and a one-time
// `npx playwright install chromium`.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_DIR = path.resolve(__dirname, "..");
const OUT_DIR = "/Users/roy/luohy15/assets/images";
const PORT = Number(process.env.SHOWCASE_PORT || 5191);
const NAMES = ["todo", "trace", "note", "link", "finance", "bot-usage", "chat"];

function startServer() {
  // Run vite directly (skip the `predev` docs build; the showcase needs no docs).
  const proc = spawn(
    "npx",
    ["vite", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: WEB_DIR, stdio: ["ignore", "pipe", "pipe"] },
  );
  proc.stdout.on("data", (d) => process.stdout.write(`[vite] ${d}`));
  proc.stderr.on("data", (d) => process.stderr.write(`[vite] ${d}`));
  return proc;
}

async function waitForServer(url, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status === 404) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Vite server did not become ready at ${url} within ${timeoutMs}ms`);
}

async function main() {
  const server = startServer();
  let browser;
  try {
    const base = `http://127.0.0.1:${PORT}`;
    await waitForServer(base);

    browser = await chromium.launch();
    const page = await browser.newPage({
      viewport: { width: 1600, height: 1200 },
      deviceScaleFactor: 2,
    });

    // Abort external requests (favicons, analytics, Google SDK) so they neither
    // hang network-idle nor leak the real network into the capture.
    await page.route("**/*", (route) => {
      const u = route.request().url();
      if (
        u.startsWith(base) ||
        u.startsWith("data:") ||
        u.startsWith("blob:")
      ) {
        return route.continue();
      }
      return route.abort();
    });

    await page.goto(`${base}/showcase`, { waitUntil: "domcontentloaded" });

    // Wait for every panel to mount, then let SWR + recharts settle.
    for (const name of NAMES) {
      await page.locator(`[data-screenshot="${name}"]`).waitFor({ state: "visible", timeout: 30_000 });
    }
    await page.waitForLoadState("networkidle").catch(() => {});
    // The chat panel renders an inline artifact (mermaid) that lazy-loads its
    // chunk and rasterizes async — wait for the rendered SVG before settling.
    await page
      .locator('[data-screenshot="chat"] .artifact-renderer svg')
      .first()
      .waitFor({ state: "visible", timeout: 15_000 })
      .catch(() => {});
    await page.waitForTimeout(2000);

    for (const name of NAMES) {
      const out = path.join(OUT_DIR, `${name}.png`);
      await page.locator(`[data-screenshot="${name}"]`).screenshot({ path: out });
      console.log(`wrote ${out}`);
    }

    await browser.close();
    browser = undefined;
  } finally {
    if (browser) await browser.close().catch(() => {});
    server.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
