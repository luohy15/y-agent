import { createRoot } from "react-dom/client";
import App from "./App";
import { updateFavicon } from "./utils/favicon";

updateFavicon();
createRoot(document.getElementById("root")!).render(<App />);
