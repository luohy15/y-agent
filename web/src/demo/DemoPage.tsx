// The public demo page (todo 3158 H3). One responsive shell around one module
// demo mount: a header with the route allowlist, the quiet persistent "Demo
// data" disclosure (PRD story 6: no large blocking banner), and the demo
// itself filling the rest of the viewport.
//
// Deliberately router-free. The page is mounted outside the app's
// BrowserRouter (see bootstrap.tsx), reads its key from `location.pathname`,
// and switches demos with ordinary links, so every navigation is a full page
// load that rebuilds the restricted runtime and resets in-memory demo state.
import { useEffect, useState } from "react";
import { SWRConfig } from "swr";
import DemoMount from "./DemoMount";
import { DemoUnavailable } from "./DemoStates";
import { fetchPublicDemos, type PublicDemoRef } from "./lookup";
import { DemoBlockedToast, DemoHostCommandProvider } from "./channel";
import { DEMO_ROUTES, demoPath, demoRouteFor, type DemoRoute } from "./routes";

type LookupState =
  | { status: "loading" }
  | { status: "ready"; demos: Map<string, PublicDemoRef | null> };

// Always rendered, with or without a resolved route: the four routes are a
// documented public contract, and identical chrome is what keeps an unknown
// key indistinguishable from an unavailable known demo (round 1 finding 4).
function DemoNav({ current }: { current: DemoRoute | null }) {
  return (
    <nav className="flex items-center gap-1 overflow-x-auto">
      {DEMO_ROUTES.map((route) => {
        const active = route.key === current?.key;
        return (
          <a
            key={route.key}
            href={demoPath(route.key)}
            aria-current={active ? "page" : undefined}
            className={`shrink-0 px-2 py-1 rounded text-xs whitespace-nowrap ${
              active
                ? "bg-sol-base02 text-sol-base1"
                : "text-sol-base01 hover:text-sol-cyan"
            }`}
          >
            {route.title}
          </a>
        );
      })}
    </nav>
  );
}

function DemoBadge() {
  return (
    <span
      title="Fictional sample data. Nothing here is saved, sent, or connected to a real account."
      className="shrink-0 px-2 py-0.5 rounded border border-sol-yellow/40 bg-sol-yellow/10 text-sol-yellow text-[0.65rem] whitespace-nowrap"
    >
      Demo data
    </span>
  );
}

// H6 takes the resolved slot map and composes the actual four-region shell.
// Keep this surface mount narrow until then: resolving every key here makes the
// public lookup contract independently testable and keeps slot failures local.
function DemoBody({ route }: { route: DemoRoute }) {
  const [state, setState] = useState<LookupState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchPublicDemos(DEMO_ROUTES.map(({ key }) => key)).then((demos) => {
      if (!cancelled) setState({ status: "ready", demos });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return <div className="p-4 text-xs text-sol-base01">Loading demo…</div>;
  }
  const demo = state.demos.get(route.key);
  return demo ? <DemoMount slug={demo.slug} version={demo} surface="shell" /> : <DemoUnavailable />;
}

export default function DemoPage({ runtimeReady = true }: { runtimeReady?: boolean }) {
  // An unknown key resolves to null and issues no request at all; a runtime
  // that could not be restricted is treated the same way. Both land on the
  // same unavailable state as any other failure.
  const route = runtimeReady ? demoRouteFor(window.location.pathname) : null;

  useEffect(() => {
    document.title = route ? `${route.title} demo — y-agent` : "Demos — y-agent";
  }, [route]);

  return (
    // A fresh in-memory SWR cache per page load: no persisted provider, so a
    // demo's queries and simulated changes cannot outlive the tab or touch the
    // visitor's own cached data (plan D6).
    <SWRConfig value={{ provider: () => new Map() }}>
      <DemoHostCommandProvider>
      <div className="h-dvh flex flex-col bg-sol-base03 text-sol-base0">
        <header className="shrink-0 flex items-center gap-2 sm:gap-4 px-3 py-2 border-b border-sol-base02">
          <a href="/" className="shrink-0 text-sm font-semibold text-sol-base1 hover:text-sol-cyan">
            y-agent
          </a>
          <DemoNav current={route} />
          <div className="flex-1" />
          <DemoBadge />
          <a href="/docs" className="shrink-0 text-xs text-sol-base01 hover:text-sol-cyan">
            Docs
          </a>
        </header>
        <main className="flex-1 min-h-0 overflow-hidden">
          {route ? <DemoBody route={route} /> : <DemoUnavailable />}
        </main>
        <DemoBlockedToast />
      </div>
      </DemoHostCommandProvider>
    </SWRConfig>
  );
}
