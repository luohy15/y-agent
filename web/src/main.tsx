import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router";
import App from "./App";
import ShareView from "./components/ShareView";
import { updateFavicon } from "./utils/favicon";

updateFavicon();
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <Routes>
      <Route path="/s/:shareId" element={<div className="h-dvh flex flex-col overflow-hidden"><ShareView /></div>} />
      <Route path="/share/:shareId" element={<div className="h-dvh flex flex-col overflow-hidden"><ShareView /></div>} />
      <Route path="/*" element={<App />} />
    </Routes>
  </BrowserRouter>
);
