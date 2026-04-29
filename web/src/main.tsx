import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router";
import { SWRConfig } from "swr";
import App from "./App";
import Landing from "./components/Landing";
import DocsView from "./components/DocsView";
import ShareView from "./components/ShareView";
import ShareTraceView from "./components/ShareTraceView";
import { useAuth } from "./hooks/useAuth";
import { updateFavicon } from "./utils/favicon";
import { abortMiddleware } from "./utils/swrAbort";

function RootGate() {
  const { isLoggedIn } = useAuth();
  return isLoggedIn ? <App /> : <Landing />;
}

updateFavicon();
createRoot(document.getElementById("root")!).render(
  <SWRConfig value={{ use: [abortMiddleware] }}>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootGate />} />
        <Route path="/docs" element={<DocsView />} />
        <Route path="/docs/:slug" element={<DocsView />} />
        <Route path="/s/:shareId" element={<ShareView />} />
        <Route path="/share/:shareId" element={<ShareView />} />
        <Route path="/t/:shareId" element={<ShareTraceView />} />
        <Route path="/trace/:traceId" element={<App />} />
        <Route path="/*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </SWRConfig>
);
