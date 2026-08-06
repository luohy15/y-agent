// Host-provided panel location (contract v6, plan-3046-right-sidebar.md R6).
// The chat module's `panel` export can be mounted twice at once (left
// activity bar + right drawer), so a module needs a way to tell the two
// copies apart without a props channel (`ArtifactMount` renders `<Artifact
// />` with no props by contract). A React context works here, unlike the
// `intents.ts` latch: both mounts are alive at the same time and need
// different values simultaneously, and React itself is a shared `@y/host`
// external so `createContext`/`useContext` resolve against the same
// instance across the host <-> blob-module boundary.
import { createContext, useContext } from "react";

const PanelLocationContext = createContext<"left" | "right">("left");

export const PanelLocationProvider = PanelLocationContext.Provider;

/** Which sidebar this `panel` surface is mounted in. Defaults to "left" for
 * older/unspecified host call sites (contract-guard §W3). */
export function usePanelLocation(): "left" | "right" {
  return useContext(PanelLocationContext);
}
