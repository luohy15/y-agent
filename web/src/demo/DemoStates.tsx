// The one public failure state (todo 3158 H3). Every way a demo can fail to
// render — unknown route key, ineligible or unreachable lookup, integrity or
// version failure, missing demo export, render throw, or a runtime that could
// not be restricted — converges here (round 1 finding 4). It carries no
// version, slug, hash, error message, rollback control, management action, or
// sign-in path, so an anonymous visitor learns nothing about the maintainer's
// modules from a failure, and the four cases are indistinguishable.
export function DemoUnavailable() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 h-full p-6 text-center">
      <p className="text-sm text-sol-base1">Demo unavailable</p>
      <p className="text-xs text-sol-base01 max-w-sm">
        This demo can&apos;t be shown right now. Try again later, or read the docs for a written
        walkthrough.
      </p>
      <a href="/docs" className="text-xs text-sol-cyan hover:underline">
        Docs
      </a>
    </div>
  );
}
