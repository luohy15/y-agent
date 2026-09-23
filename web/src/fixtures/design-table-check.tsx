/**
 * Non-routed host entry for the @y/design Table fixture (todo 3657).
 * `web/vite.config.ts` excludes `src/fixtures` from the app build, so this
 * file is not a product page. The host consumption check builds it with
 * the same Vite/Tailwind pipeline:
 *   npx vite build --config vite.design-fixture.config.ts
 */
import { createRoot } from "react-dom/client";
import "../style.css";
import { DesignTableFixture } from "./DesignTableFixture";

createRoot(document.getElementById("root")!).render(<DesignTableFixture />);
