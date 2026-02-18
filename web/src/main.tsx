import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router";
import App from "./App";
import ShareView from "./components/ShareView";
import { updateFavicon } from "./utils/favicon";

updateFavicon();
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <Routes>
      <Route path="/s/:shareId" element={<ShareView />} />
      <Route path="/share/:shareId" element={<ShareView />} />
      <Route path="/*" element={<App />} />
    </Routes>
  </BrowserRouter>
);
