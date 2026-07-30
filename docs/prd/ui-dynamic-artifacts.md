---
title: Dynamic UI Artifacts
type: prd
project: y-agent
feature: ui-dynamic-artifacts
status: active
---

# Dynamic UI Artifacts

## Problem Statement

Every screen in y-agent is compiled into the web bundle. The sidebar's panel
list is a hardcoded array, the panel identifiers are a hardcoded string union,
and each panel's component is an import resolved at build time. Changing any of
it, even adding one panel that only one person will ever open, means editing the
repo, building, and running a full web deploy.

Two costs follow from that. First, iteration is slow and heavyweight: a UI idea
worth ten minutes of work costs a deploy cycle, so small personal tools do not
get built. Second, and more structurally, the built-in surface accumulates
things that are not universal. Finance is the clearest example: it is a large,
opinionated, personal view of one user's ledger, yet it sits in the shipped
bundle that every user loads, because there is no other place for it to live.
There is no way to express "this screen belongs to this user" short of shipping
it to everyone.

The user wants a UI surface that can be authored, published, switched, and
rolled back as data, in seconds, without deploying the application, while
keeping a trustworthy story for what code is allowed to run.

## Solution

A **dynamic UI artifact** is a user-owned, versioned React component that lives
outside the application bundle and is loaded at runtime.

The authoring loop is a file and a command. The artifact's source is a `.tsx`
file on the user's VM, editable with the tools that already exist: agents write
it with ordinary file tooling, and the web file tree and editor open it with
syntax highlighting. `y ui publish <slug>` builds that source with esbuild,
uploads the built ES module, records an immutable version row, and activates it.
The next page load shows the new UI. Nothing is deployed.

At runtime the web app appends the current user's published artifacts to the
built-in panel list. Selecting one fetches the built bundle through the API,
verifies its content hash, and imports it as a real ES module whose default
export is a React component mounted directly in the host's component tree. It
is not a boxed iframe and not an interpreted JSON document: it is a first-class
React component with the host's own React instance, the host's SWR cache, the
host's authenticated fetch, and the host's theme.

Versions are immutable and publishing is a pointer move, so rollback is
instantaneous and cannot fail: `y ui rollback <slug>` repoints to the previous
version without rebuilding anything. Every artifact mounts inside its own error
boundary, so a bad publish degrades to an error card with a rollback button
rather than a broken application.

This reframes what belongs in the bundle. The built-ins become the universal
core that every user needs; anything optional or personal becomes an artifact.
Finance is the reference case and the first migration target.

## User Stories

### Authoring and publishing

1. As a user, I want an artifact's source to be a plain `.tsx` file on my VM, so
   that I can edit it with any file tool instead of pasting code into a form.
2. As a user, I want to edit artifact source in the web file editor with syntax
   highlighting, so that I can make a quick change without leaving the app.
3. As an agent, I want to author and modify artifact source with ordinary file
   read/write tools, so that building a UI needs no special agent capability.
4. As a user, I want `y ui publish <slug>` to build, upload, version, and
   activate in one command, so that the publish loop is a single step.
5. As a user, I want a publish to take seconds, so that UI iteration feels like
   editing a file rather than shipping a release.
6. As a user, I want a build error to fail the publish with the compiler's
   message and leave the currently active version untouched, so that a typo can
   never take down a working panel.
7. As a user, I want `y ui publish --no-activate` to stage a version without
   promoting it, so that I can inspect a build before making it live.
8. As a user, I want `y ui create <slug>` to scaffold a working starter artifact,
   so that I do not have to remember the module contract from scratch.
9. As a user, I want `y ui list` to show my artifacts with their active version,
   so that I can see what is installed at a glance.
10. As a user, I want `y ui versions <slug>` to list version history with the
    active version marked, so that I can pick a target for rollback.

### Rendering and integration

11. As a user, I want my published artifacts to appear in the sidebar alongside
    built-in panels, so that a personal tool is reachable the same way as
    everything else.
12. As a user, I want each artifact to supply its own label and icon, so that it
    is identifiable in the sidebar without being visually second-class.
13. As a user, I want selecting an artifact panel to mount its component in the
    main content area, so that it gets the same space as a built-in panel.
14. As a user, I want artifacts to render with the host's theme tokens, so that
    they look native and follow light/dark switches.
15. As a user, I want an artifact reachable at its own route, so that I can
    bookmark or link a specific panel.
16. As a user, I want a newly published artifact to appear without a rebuild or
    redeploy of the application, so that the core promise of the feature holds.
17. As a user, I want artifact panels to participate in the existing sidebar
    ordering behavior, so that I can arrange them among the built-ins.

### The host contract

18. As an artifact author, I want the host's React instance to be shared rather
    than bundled, so that hooks work at all.
19. As an artifact author, I want the host's SWR cache to be shared, so that my
    artifact and built-in panels requesting the same endpoint dedupe instead of
    double-fetching.
20. As an artifact author, I want authenticated API access through a host-provided
    fetch helper, so that I can read any endpoint my session is entitled to
    without handling tokens myself.
21. As an artifact author, I want shared list state components and badges from the
    host, so that loading, empty, and error states match the rest of the app.
22. As an artifact author, I want charting available as a shared module, so that
    chart-heavy artifacts do not each re-ship a large library on every publish.
23. As an artifact author, I want to use arbitrary Tailwind utility classes and
    have them actually render, so that styling is not silently limited to classes
    the host happens to already use.
24. As a user, I want an artifact's styles scoped so it cannot restyle the host
    chrome, so that a careless artifact cannot break navigation.
25. As an artifact author, I want the host contract to be versioned, so that I
    know what I am building against.
26. As a user, I want an artifact built against a newer host contract than the
    running app to refuse to mount with a clear message, so that a version skew
    surfaces as an explicit error rather than a confusing runtime failure.

### Versioning, selection, rollback

27. As a user, I want every publish to create an immutable version, so that
    history is a real record and not overwritten state.
28. As a user, I want the active version to be a single pointer on the artifact,
    so that what is live is unambiguous.
29. As a user, I want `y ui rollback <slug>` to repoint to the previous version,
    so that recovery is one command.
30. As a user, I want rollback to require no rebuild, so that it still works when
    the source is mid-edit or the build is broken.
31. As a user, I want to activate any historical version by number, so that I can
    move to a known-good build, not only the immediately previous one.
32. As a user, I want to disable an artifact without deleting it, so that I can
    hide a panel while keeping its history.
33. As a user, I want artifacts scoped to their owner, so that my personal panels
    are mine and do not appear for other users.

### Safety and failure handling

34. As a user, I want a throwing artifact to degrade to an error card in its own
    panel while the rest of the app keeps working, so that a bad publish never
    white-screens the application.
35. As a user, I want the error card to name the artifact and the failed version
    and offer one-click rollback, so that recovery does not require the CLI.
36. As a user, I want the loader to verify the bundle's content hash before
    executing it, so that tampered or corrupted bytes never run.
37. As a user, I want a hash mismatch, a fetch failure, and a host-version
    incompatibility to each produce a distinct message, so that I can tell a
    storage problem from a code problem.
38. As a user, I want only my authenticated session to be able to publish, so
    that the publish path is not an open code-execution endpoint.
39. As a user, I want no raw source to be compiled or evaluated in the browser, so
    that the only executable that reaches the page is one the trusted build step
    produced.
40. As a user, I want loaded bundles cached by content hash for the session, so
    that switching panels does not refetch code.

### Finance as the reference migration

41. As a user, I want the Finance sidebar panel to work as a dynamic artifact, so
    that the vertical slice is proven on a real screen instead of a demo.
42. As a user, I want the full Finance viewer to be expressible as an artifact, so
    that the host contract is validated against a large, chart-heavy, genuinely
    demanding screen.
43. As a user, I want Finance to keep working exactly as before after migration,
    so that the change is invisible in daily use.
44. As a user, I want optional and personal screens to live outside the shipped
    bundle, so that the built-in surface stays the universal core.

## Implementation Decisions

### Execution model: code-backed, directly imported

Artifacts are **real code**, not a declarative JSON schema interpreted by a
whitelist of primitives. A declarative model was considered and rejected: it
caps expressiveness at whatever primitives were foreseen, and adding a primitive
puts you back in the deploy cycle the feature exists to escape.

Artifacts are also **not** sandboxed in an origin-null iframe. Iframe isolation
would defeat the integration being paid for: no native theme inheritance, no
real layout participation, and every data access forced through a postMessage
bridge. Artifacts are imported directly and run at the host's origin with full
trust.

The security boundary is therefore **authorship and integrity, not runtime
containment**. The honest framing: the publisher is the owner and their own
agents, who can already ship arbitrary code through the deploy pipeline, so this
is not a new capability but a new path that skips git review. The residual risk
is a misbehaving publisher, and it is mitigated by ownership scoping, hash
verification, and the audit trail of immutable versions, not by the runtime.

### Source of truth and build pipeline

Artifact source lives **on the user's VM**, in a dedicated directory, one `.tsx`
file per artifact slug. It is deliberately **not** in the y-agent repo (that
would couple authoring back to the thing being escaped) and **not** a DB text
column (invisible to the file tree, the editor, and every agent file tool).

`y ui publish` runs the build on the VM with **esbuild**, marking the shared
modules external, then uploads the built ESM to S3 under a content-addressed key
and inserts the version row. Compilation happens only in this trusted build
step; no source crosses the wire and nothing is compiled in the browser.

### Transport: fetch, verify, blob-import

The loader does not `import()` a remote URL directly, for two converging
reasons: a bare dynamic import cannot carry an `Authorization` header, and the
bytes must be read anyway to verify the hash. The sequence is:

```
authFetch(GET /api/ui/artifact/<version_id>/bundle)
  -> verify sha256(bytes) === version.sha256
  -> URL.createObjectURL(new Blob([bytes], {type: "text/javascript"}))
  -> import(blobUrl)
  -> module.default : React component
```

One auth-gated, same-origin code path that also works in local development with
no S3 configured.

### Shared modules (the externals contract)

esbuild marks these external; the host resolves them through an import map
pointing at stable vendor modules it emits:

| Specifier | Rationale |
|---|---|
| `react`, `react-dom`, `react/jsx-runtime` | Mandatory. A second React copy makes hooks throw immediately. |
| `swr` | Shared cache: artifacts and built-ins dedupe identical requests. |
| `recharts` | Large; bundling per artifact re-ships it on every publish of every chart artifact. |
| `@y/host` | The curated host surface. |

`@y/host` exposes the API base, authenticated fetch and JSON fetcher, theme
state, shared list-state and badge components, and navigation helpers. It is a
**public API with a stability obligation**: a published artifact keeps calling it
after the host redeploys. It carries a version, and artifact metadata records a
`min_host_version`; an artifact requiring a newer host than the running app
refuses to mount with an explicit message rather than failing obscurely.

### Styling

Tailwind 4 generates CSS by scanning source files at build time, so the host's
stylesheet contains only classes used inside the y-agent repo. An artifact built
elsewhere that writes an unused utility class would silently render unstyled.

Therefore the **artifact build runs Tailwind itself**, against the host's theme
tokens published to the VM as part of the SDK, with **preflight disabled**. The
build emits a stylesheet alongside the module; the loader injects it on mount
and removes it on unmount. Artifacts are self-contained, on-theme, and scoped so
they cannot restyle host chrome.

### Schema

```
ui_artifact
  artifact_id      public string id
  user_id          owner (FK)
  slug             unique per owner
  kind             "panel" (v1)
  active_version_id FK -> ui_artifact_version, nullable
  enabled          bool

ui_artifact_version
  version_id       public string id
  artifact_id      FK
  version_no       monotonic per artifact
  sha256           content hash of the built bundle
  storage_key      S3 key
  label            sidebar label
  icon             sidebar icon
  min_host_version host contract floor
  source_digest    hash of the source that produced this build
  built_at
```

Versions are immutable; nothing but `active_version_id` and `enabled` ever
changes after a publish.

### Selection

Selection **is ownership** in v1: an artifact belongs to a user and its
`active_version_id` is that user's live version. A separate
`(user, artifact, version)` selection table is deliberately not built, because
there is no sharing in v1 and it would be speculative structure. The `user_id`
on the artifact keeps the door open.

### Failure isolation

Once UI ships outside the deploy pipeline there is no CI between a mistake and
the running app, so failure handling is a requirement rather than polish. Every
artifact mounts inside a **per-panel error boundary**. Render throws, fetch
failure, hash mismatch, and host-version incompatibility each degrade to an
error card naming the slug and failed version and offering one-click rollback,
each with a distinct message. **A broken artifact must never white-screen the
host.** This is the safety net that makes publish-without-review acceptable.

### Caching

Bundles are cached by `sha256` for the session. Versions are immutable, so a
cached bundle is never revalidated.

## Testing Decisions

Test the observable contract, not the loader's internals.

- **Publish and rollback semantics** are the highest-value target: publishing
  creates a new immutable version and moves the pointer; a failed build leaves
  the active version untouched; rollback repoints without rebuilding; activating
  a historical version by number works. These are service-level tests with no
  browser involved.
- **Integrity enforcement** must be tested as a negative: a bundle whose bytes do
  not match the recorded hash is refused and never imported. This is the control
  standing in for runtime containment, so it deserves an explicit test rather
  than trust.
- **Host-version gating**: an artifact declaring a `min_host_version` above the
  running host refuses to mount and reports why.
- **Failure isolation** is a component test: an artifact whose component throws
  renders the error card with a rollback affordance while sibling panels keep
  rendering. The existing error boundary component tests are the prior art to
  extend.
- **Panel composition**: the sidebar lists built-ins plus the current user's
  enabled artifacts, and a disabled artifact does not appear.
- **Finance migration** is verified by behavioral equivalence: the migrated panel
  renders the same figures from the same endpoints as the built-in version.
- Prior art for component-level tests already exists in the web package
  (error boundary, file tree, note list, bot viewer), and repository/service
  tests are the established pattern on the Python side. Extend those rather than
  introducing a new harness.
- Not worth testing: esbuild's own correctness, and the exact bytes of a build.

## Out of Scope

- **Dynamically loaded CLI commands.** The todo names "CLI/GUI", but importing
  remote Python into the `y` process is a materially harsher security and
  packaging problem than a browser ES module. `y ui` is the *management* surface
  (create, publish, list, versions, rollback, activate); it does not itself
  become dynamic.
- **Adding new shared modules without a deploy.** The externals set is fixed at
  host build time; extending `@y/host` or adding a shared library is a normal
  application release.
- **Sharing artifacts between users**, an artifact marketplace, and any
  `(user, artifact, version)` selection mapping distinct from ownership.
- **Sandboxed execution for untrusted third-party artifacts.** If artifacts ever
  come from authors other than the owner, the isolation model must be revisited;
  v1 assumes owner-authored code.
- **Chat-inline dynamic widgets.** The existing artifact fence system already
  covers Mermaid, Vega-Lite, and sanitized SVG in messages.
- **Replacing built-in panels wholesale.** The universal core stays compiled;
  only optional and personal screens migrate.
- **Server-side or headless rendering of artifacts.**
- **A visual/no-code artifact builder.** Authoring is writing TSX.
- **Automatic rollback on error.** Failure surfaces an explicit rollback
  affordance; it does not silently change what is live.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2412 | Dynamic UI artifact foundation; Finance as reference migration | - | `pages/plan-2412-ui-dynamic-artifacts.md` | `pages/decision-2412-runtime-contract.md`, `pages/decision-2412-s5-web-host-sdk.md` | `pages/review-2412-storage-schema.md`, `pages/review-2412-ui-api-round2.md`, `pages/review-2412-ui-sdk-cli.md`, `pages/review-2412-web-host-sdk.md`, `pages/review-2412-ui-loader-round2.md`, `pages/review-2412-ui-mount.md` | shipped |
