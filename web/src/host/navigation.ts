// Artifacts cannot import react-router directly (it is not in the externals
// list), so this is the generic way to change the URL: push history state and
// fire `popstate`, exactly like a real link click, which the host's
// `BrowserRouter` (main.tsx) already listens for.
export function navigateTo(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
