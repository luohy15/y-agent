// Entry point for `/demo` (todo 3158 H3). Loaded lazily by main.tsx, which
// routes on the pathname before rendering anything, so a public demo page
// never mounts the authenticated app tree: no production host registry, no
// persisted SWR provider, no warm-up ping, no auth hook, no ambient identity.
//
// The restricted runtime is installed before the first render — and therefore
// before any module bytes are fetched or evaluated (PRD story 30: demo mode is
// selected explicitly, never inferred from a missing token).
import { createRoot } from "react-dom/client";
import { updateFavicon } from "../utils/favicon";
import DemoPage from "./DemoPage";
import { installPublicDemoRuntime } from "./runtime";

export function mountPublicDemo(container: HTMLElement): void {
  let runtimeReady = true;
  try {
    installPublicDemoRuntime();
  } catch (err) {
    // A restriction that could not be installed is a hard stop: render the
    // ordinary unavailable page and never resolve or mount a module bundle.
    console.error("[y-demo]", err);
    runtimeReady = false;
  }
  // Canvas-drawn, no storage or network: the demo keeps the product's favicon
  // without reaching for anything the runtime just denied.
  updateFavicon();
  createRoot(container).render(<DemoPage runtimeReady={runtimeReady} />);
}
