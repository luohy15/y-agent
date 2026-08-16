// Ambient types for Vite/vitest `?raw` imports used by local-only source gates.
declare module "*?raw" {
  const content: string;
  export default content;
}
