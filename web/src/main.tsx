import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router";
import App from "./App";
import { updateFavicon } from "./utils/favicon";

updateFavicon();
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <Routes>
      <Route path="/:chatId?" element={<App />} />
    </Routes>
  </BrowserRouter>
);
