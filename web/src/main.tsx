import { lazy, Suspense, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router";
import { SWRConfig } from "swr";
import App from "./App";
import Landing from "./components/Landing";
import DocsView from "./components/DocsView";
import ShareView from "./components/ShareView";
import PublicTraceApp from "./components/PublicTraceApp";
import ShareNoteView from "./components/ShareNoteView";
import { useAuth } from "./hooks/useAuth";
import { updateFavicon } from "./utils/favicon";
import { abortMiddleware } from "./utils/swrAbort";
import { localStorageProvider } from "./utils/swrPersistedCache";
import { applyPrefs, loadPrefs } from "./utils/theme";
import { API } from "./api";
import "./host/registry";

// Lazy, unauthenticated route used only by the doc-screenshot pipeline.
const ScreenshotShowcase = lazy(() => import("./components/ScreenshotShowcase"));

// Fire-and-forget warm-up ping to trigger Lambda init while the user reads the
// UI. No auth, ignore the result; swallow errors so it never logs to console.
fetch(`${API}/api/health`).catch(() => {});

function RootGate() {
  const { isLoggedIn } = useAuth();
  return isLoggedIn ? <App /> : <Landing />;
}

// Re-resolve the document theme on client-side navigations. applyPrefs forces
// solarized-dark on public share routes and otherwise restores loaded prefs, so
// entering/leaving /t|/s|/share|/n never leaves a stale data-theme behind.
function ThemeRouteSync() {
  const { pathname } = useLocation();
  useEffect(() => {
    applyPrefs(loadPrefs());
  }, [pathname]);
  return null;
}

updateFavicon();
createRoot(document.getElementById("root")!).render(
  <SWRConfig value={{ use: [abortMiddleware], provider: localStorageProvider }}>
    <BrowserRouter>
      <ThemeRouteSync />
      <Routes>
        <Route path="/" element={<RootGate />} />
        <Route path="/docs" element={<DocsView />} />
        <Route path="/docs/:slug" element={<DocsView />} />
        <Route path="/s/:shareId" element={<ShareView />} />
        <Route path="/share/:shareId" element={<ShareView />} />
        <Route path="/t/:shareId" element={<PublicTraceApp />} />
        <Route path="/n/:shareId" element={<ShareNoteView />} />
        <Route path="/showcase" element={<Suspense fallback={null}><ScreenshotShowcase /></Suspense>} />
        <Route path="/trace/:traceId" element={<App />} />
        <Route path="/ui/*" element={<Navigate to="/" replace />} />
        <Route path="/*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </SWRConfig>
);
