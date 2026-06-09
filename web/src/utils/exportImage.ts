import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { domToPng } from "modern-screenshot";
import MessageExportView from "../components/MessageExportView";
import type { Message } from "../components/MessageList";
import { buildExportFilename, pickImageDelivery } from "./messageExport";

const SOL_BASE03 = "#002b36";

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Wait until every <img> in the subtree has finished loading (or errored — a broken
// cross-origin image must not block export). Bounded by `timeoutMs`.
async function waitForImages(root: HTMLElement, timeoutMs = 5000): Promise<void> {
  const imgs = Array.from(root.querySelectorAll("img"));
  if (imgs.length === 0) return;
  await Promise.race([
    Promise.all(
      imgs.map((img) =>
        img.complete
          ? Promise.resolve()
          : new Promise<void>((resolve) => {
              img.addEventListener("load", () => resolve(), { once: true });
              img.addEventListener("error", () => resolve(), { once: true });
            }),
      ),
    ),
    delay(timeoutMs),
  ]);
}

// Wait until lazily-rendered artifacts (mermaid SVG, vega-lite chart) have painted.
// ArtifactRenderer fills `.artifact-renderer` with an SVG once ready; an unsettled
// artifact is still empty. Bounded by `timeoutMs` so a failed render degrades gracefully.
async function waitForArtifacts(root: HTMLElement, timeoutMs = 4000): Promise<void> {
  const containers = Array.from(root.querySelectorAll<HTMLElement>(".artifact-renderer"));
  if (containers.length === 0) return;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const allSettled = containers.every((c) => c.childElementCount > 0);
    if (allSettled) break;
    await delay(100);
  }
}

// Render the selected messages into an offscreen container and capture them as a PNG.
// Returns both a blob (for download / clipboard / share) and the data URL.
export async function exportMessagesToPng(
  messages: Message[],
  opts: { title?: string } = {},
): Promise<{ blob: Blob; dataUrl: string }> {
  const host = document.createElement("div");
  host.style.position = "fixed";
  host.style.left = "-99999px";
  host.style.top = "0";
  host.style.zIndex = "-1";
  host.style.pointerEvents = "none";
  document.body.appendChild(host);

  const root = createRoot(host);
  try {
    root.render(createElement(MessageExportView, { messages, title: opts.title }));

    // Let React commit, then settle async content before capture.
    await nextFrame();
    await nextFrame();
    await waitForImages(host);
    if (document.fonts?.ready) await document.fonts.ready;
    await waitForArtifacts(host);
    await nextFrame();

    const target = host.firstElementChild as HTMLElement;
    const dataUrl = await domToPng(target, { scale: 2, backgroundColor: SOL_BASE03 });
    const blob = await (await fetch(dataUrl)).blob();
    return { blob, dataUrl };
  } finally {
    root.unmount();
    host.remove();
  }
}

// Trigger a browser download of the PNG. This is the guaranteed delivery path.
export function downloadPng(dataUrl: string, filename = buildExportFilename()): void {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Best-effort clipboard copy of the image. No-ops (returns false) where unsupported.
export async function copyPngToClipboard(blob: Blob): Promise<boolean> {
  try {
    if (!navigator.clipboard || typeof ClipboardItem === "undefined") return false;
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch {
    return false;
  }
}

// Best-effort native share sheet (mobile). Returns false when unavailable / cancelled.
export async function sharePng(blob: Blob, filename = buildExportFilename()): Promise<boolean> {
  try {
    const file = new File([blob], filename, { type: "image/png" });
    const nav = navigator as Navigator & { canShare?: (data: ShareData) => boolean };
    if (!nav.share || (nav.canShare && !nav.canShare({ files: [file] }))) return false;
    await nav.share({ files: [file] });
    return true;
  } catch {
    return false;
  }
}

// Resolve current platform signals for the delivery picker. Touch = coarse pointer or a
// non-zero touch-point count; file-share support requires navigator.share plus a canShare
// that accepts a PNG file.
function resolveDeliverySignals(): { canShareFiles: boolean; isTouch: boolean } {
  const nav = navigator as Navigator & { canShare?: (data: ShareData) => boolean };
  const isTouch =
    nav.maxTouchPoints > 0 ||
    (typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches);
  const probe = new File([], "probe.png", { type: "image/png" });
  const canShareFiles =
    typeof nav.share === "function" && typeof nav.canShare === "function" && nav.canShare({ files: [probe] });
  return { canShareFiles, isTouch };
}

// Deliver the exported PNG through exactly ONE channel so a desktop never gets both a
// download dialog and the macOS share sheet. Touch devices that can share files use the
// share sheet only; desktop downloads only (plus a silent, prompt-free clipboard copy).
export async function deliverPng(blob: Blob, dataUrl: string, filename = buildExportFilename()): Promise<void> {
  if (pickImageDelivery(resolveDeliverySignals()) === "share") {
    await sharePng(blob, filename);
    return;
  }
  downloadPng(dataUrl, filename);
  await copyPngToClipboard(blob);
}
