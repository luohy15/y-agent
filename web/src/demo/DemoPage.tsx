// Public demo application root (todo 3158 H3 + H6). Mounted outside the app's
// BrowserRouter (bootstrap.tsx). `/demo` is the only supported public route;
// visitors switch showcase surfaces through the in-shell activity rail.
import { SWRConfig } from "swr";
import DemoShell from "./DemoShell";
import { DemoUnavailable } from "./DemoStates";
import {
  DemoBlockedToast,
  DemoHostCommandProvider,
} from "./channel";

export default function DemoPage({ runtimeReady = true }: { runtimeReady?: boolean }) {
  return (
    // A fresh in-memory SWR cache per page load: no persisted provider, so a
    // demo's queries and simulated changes cannot outlive the tab or touch the
    // visitor's own cached data (plan D6).
    <SWRConfig value={{ provider: () => new Map() }}>
      <DemoHostCommandProvider>
        {runtimeReady ? (
          <DemoShell />
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
