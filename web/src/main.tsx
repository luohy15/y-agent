import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router";
import { SWRConfig } from "swr";
import App from "./App";
import ShareView from "./components/ShareView";
import ShareTraceView from "./components/ShareTraceView";
import { updateFavicon } from "./utils/favicon";
import { abortMiddleware } from "./utils/swrAbort";

updateFavicon();
createRoot(document.getElementById("root")!).render(
  <SWRConfig value={{ use: [abortMiddleware] }}>
    <BrowserRouter>
      <Routes>
        <Route path="/s/:shareId" element={<ShareView />} />
        <Route path="/share/:shareId" element={<ShareView />} />
        <Route path="/t/:shareId" element={<ShareTraceView />} />
        <Route path="/trace/:traceId" element={<App />} />
        <Route path="/*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </SWRConfig>
);
