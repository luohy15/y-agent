// Public demo application root (todo 3158 H3 + H6). Mounted outside the app's
// BrowserRouter (bootstrap.tsx), reads its key from `location.pathname`, and
// switches demos with ordinary full page loads so every navigation rebuilds
// the restricted runtime and resets in-memory demo state.
//
// H6: the body is the four-region DemoShell. Bare `/demo` defaults to chat;
// unknown keys keep the generic unavailable state with no lookup request.
// Deep links seed centre mode on the host-command provider so Todo/Note open
// in files mode without a chat-mode flash (design selectSurface).
import { SWRConfig } from "swr";
import DemoShell from "./DemoShell";
import { DemoUnavailable } from "./DemoStates";
import {
  DemoBlockedToast,
  DemoHostCommandProvider,
  type DemoCentreMode,
} from "./channel";
import { demoRouteFor, type DemoRoute } from "./routes";

/** Resolve the shell route. Bare `/demo` is the documented default (chat). */
export function resolveDemoRoute(pathname: string): DemoRoute | null | "unavailable" {
  if (pathname === "/demo" || pathname === "/demo/") {
    return { key: "chat", title: "Chat" };
  }
  const route = demoRouteFor(pathname);
  if (route) return route;
  if (pathname.startsWith("/demo/")) return "unavailable";
  return null;
}

/** Centre mode + detail tab for a deep-link key (design selectSurface). */
export function initialCentreForRoute(key: string | null | undefined): {
  centreMode: DemoCentreMode;
  detailTab: "todo" | "trace" | null;
} {
  if (key === "todo") return { centreMode: "files", detailTab: "todo" };
  if (key === "note") return { centreMode: "files", detailTab: null };
  return { centreMode: "chat", detailTab: null };
}

export default function DemoPage({ runtimeReady = true }: { runtimeReady?: boolean }) {
  // An unknown key resolves to unavailable and issues no request at all; a
  // runtime that could not be restricted is treated the same way.
  const resolved = runtimeReady ? resolveDemoRoute(window.location.pathname) : "unavailable";
  const route: DemoRoute | null =
    resolved === "unavailable" || resolved === null ? null : resolved;
  const showShell = runtimeReady && resolved !== "unavailable" && resolved !== null;
  const { centreMode, detailTab } = initialCentreForRoute(route?.key);

  return (
    // A fresh in-memory SWR cache per page load: no persisted provider, so a
    // demo's queries and simulated changes cannot outlive the tab or touch the
    // visitor's own cached data (plan D6).
    <SWRConfig value={{ provider: () => new Map() }}>
      <DemoHostCommandProvider
        initialCentreMode={centreMode}
        initialDetailTab={detailTab}
      >
        {showShell ? (
          <DemoShell route={route} />
        ) : (
          <div className="h-dvh flex flex-col bg-sol-base03 text-sol-base0">
            <main className="flex-1 min-h-0 overflow-hidden">
              <DemoUnavailable />
            </main>
          </div>
        )}
        <DemoBlockedToast />
      </DemoHostCommandProvider>
    </SWRConfig>
  );
}
