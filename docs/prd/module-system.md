---
title: Module System
type: prd
project: y-agent
feature: module-system
status: draft
---

# Module System

## Problem Statement

A domain feature in y-agent is not a thing. It is a spray of files across five
packages that happen to share a name prefix: derived logic in `storage`, a
controller in `api`, a command group in `cli`, a scheduled writer in `worker`,
and a `.tsx` on the VM. Nothing in the system knows those files belong together,
so "finance" exists only as a convention in the reader's head.

That is the structural problem. The immediate one is speed, and it has a sharp
edge that is easy to miss: **three of those five surfaces are already hot, and
one is not.**

The VM's `y` is an editable install pointing straight at the working checkout,
so editing derived logic or a CLI command takes effect on the next invocation
with no deploy at all. The UI has been publishable as data since the dynamic
artifact system shipped, so a panel change is `y ui publish` and a page reload.
The API Lambda is the holdout. It is the one surface that requires
`sam build && sam deploy`, minutes per iteration, redeploying the entire
application to change one function.

Todo 3018 is the case in point. Adding a `realized_trades` array to the
investment-returns response made it visible in `y finance investment-returns`
immediately, and invisible in the finance artifact until the whole backend was
redeployed. The artifact and the CLI read the same logic; only one of them had
to wait for AWS.

So the user is paying a full-application deploy cycle for changes that are
scoped to one domain, touch no infrastructure, add no dependencies, and are
already running locally. And because the deploy is all-or-nothing, there is no
per-domain version history, no rollback narrower than the whole backend, and no
answer to "what changed in finance last week" other than reading the git log.

## Solution

A **module** is a user-owned, versioned unit that contains everything for one
domain: its API routes, its CLI commands, its business logic, and its UI. It
lives in one directory on the user's VM, publishes as data, and loads at runtime
without deploying the application.

The authoring loop is a directory and a command. Module source lives at
`$Y_AGENT_HOME/modules/<slug>/`. The CLI picks up the module's commands directly
from that directory, so `y finance investment-returns` reflects an edit the
instant it is saved, with no publish step at all. When the change is good,
`y module publish finance` builds the Python and the TSX, uploads both as
content-hashed bundles, records one immutable version spanning both, and moves
one pointer. The next API request loads the new code and the next page load
renders the new UI. Nothing is deployed.

On the API side, the module is loaded in-process. The host declares a single
catch-all route, `/api/module/{slug}/{path:path}`; a request to it resolves the
module's active version, fetches the bundle, verifies its sha256, imports it,
and forwards the request into a per-version sub-application built from an
ordinary FastAPI `APIRouter` that the module supplies. The module reads
PostgreSQL directly through host repositories, exactly as the built-in
controller does today, so nothing about the data path changes: no SSH hop, no
proxy, no latency regression.

Backend and frontend advance and roll back **together**. One `module_version`
row records both bundles, so publish skew, shipping a UI that expects a field
the API does not serve yet, is structurally impossible rather than a rule
someone remembers. `y module rollback finance` restores a known-good pair.

This absorbs the dynamic UI artifact system rather than sitting beside it.
`y ui` becomes `y module`; an artifact with no backend is simply a module with
only a UI part. One concept, one command, one version line.

## User Stories

### Module identity and layout

1. As a user, I want everything for one domain in one directory on my VM, so
   that "the finance code" is a place rather than a naming convention.
2. As a user, I want a module to declare which parts it has (API, CLI, UI), so
   that a UI-only module and a full-stack module are the same kind of thing with
   different parts filled in.
3. As a user, I want module source to be plain files editable with ordinary
   tools, so that agents write it with normal file tooling and the web editor
   opens it with syntax highlighting.
4. As a user, I want `y module create <slug>` to scaffold a working module, so
   that I do not have to remember the contract from scratch.
5. As a user, I want a module owned by a user, so that my personal domains are
   mine and do not appear for other users.

### The fast loop

6. As a user, I want a saved edit to a module's CLI or logic to take effect on
   the next `y` invocation with no publish, so that development stays at
   filesystem speed.
7. As a user, I want `y module publish <slug>` to build, upload, version, and
   activate in one command, so that promoting a change is a single step.
8. As a user, I want a publish to take seconds rather than a deploy cycle, so
   that the core promise of the feature holds.
9. As a user, I want a build or import error to fail the publish and leave the
   active version untouched, so that a typo can never take down a working module.
10. As a user, I want to iterate against the CLI and then publish the exact
    source I tested, so that the fast loop and the deployed artifact cannot
    diverge.

### API routes

11. As a module author, I want to declare routes with an ordinary FastAPI
    `APIRouter`, so that authoring a module handler is the same work as writing a
    built-in controller.
12. As a module author, I want `Query` validation, path parameters, and
    `HTTPException` to work normally, so that migrating an existing controller is
    close to a file move.
13. As a module author, I want the authenticated user resolved by the host before
    my handler runs, so that I never handle tokens.
14. As a user, I want module routes reachable at a predictable path derived from
    the slug, so that the UI knows where to call without extra configuration.
15. As a user, I want module code loaded only when one of its routes is actually
    requested, so that a module I never call costs nothing.
16. As a user, I want a loaded version cached for the life of the container, so
    that repeated requests do not refetch and re-import code.
17. As a user, I want a version switch to take effect without restarting
    anything, so that publishing is the only step.

### CLI commands

18. As a user, I want a module's commands to appear under `y <slug>`, so that a
    module-owned command is invoked exactly like a built-in one.
19. As a user, I want module commands discovered from the modules directory
    automatically, so that adding a module does not mean editing the CLI's
    command registry.
20. As a user, I want a module's code imported only when one of its commands is
    actually invoked, so that module discovery does not slow down every `y`
    invocation on the agent hot path.
21. As a user, I want a module whose CLI fails to import to break only its own
    command group, so that one bad module does not make `y` unusable.
22. As a user, I want the CLI to read local source rather than the published
    bundle, so that I can test a change before promoting it.

### The host surface

23. As a module author, I want to import host repositories, the DB session, and
    shared services, so that a module composes existing data access instead of
    reimplementing it.
24. As a module author, I want the host surface versioned with a stated stability
    obligation, so that a published module keeps working after the host
    redeploys.
25. As a user, I want a module built against a newer host surface than the running
    API to refuse to load with a clear message, so that version skew surfaces as
    an explicit error rather than a confusing runtime failure.
26. As a module author, I want the browser-side contract to stay exactly as it is
    today, so that migrating an existing artifact into a module changes its
    address, not its code.

### Atomic versioning and rollback

27. As a user, I want one version to span a module's API and UI, so that "the
    version of finance" is a single unambiguous thing.
28. As a user, I want backend and frontend to activate together, so that a UI can
    never go live expecting a response field the API does not serve yet.
29. As a user, I want every publish to create an immutable version, so that
    history is a real record and not overwritten state.
30. As a user, I want the active version to be a single pointer, so that what is
    live is unambiguous.
31. As a user, I want `y module rollback <slug>` to restore the previous version
    of both halves, so that recovery is one command and cannot leave a mismatched
    pair.
32. As a user, I want rollback to require no rebuild, so that it still works when
    the source is mid-edit or the build is broken.
33. As a user, I want to activate any historical version by number, so that I can
    move to a known-good build, not only the immediately previous one.
34. As a user, I want `y module list` to show my modules, their parts, and their
    active version, so that I can see what is installed at a glance.
35. As a user, I want `y module versions <slug>` to show history with the active
    version marked and each version's description, so that I can correlate a
    version with the change that produced it.
36. As a user, I want to disable a module without deleting it, so that I can turn
    a domain off while keeping its history.
37. As a user, I want `y module delete <slug>` to remove the module and its
    versions while leaving my authoring source alone, so that deleting deployed
    state never destroys my working files.

### Safety and failure isolation

38. As a user, I want a module that fails to load to return an error only on its
    own routes, so that a bad publish never takes down unrelated endpoints.
39. As a user, I want fetch failure, hash mismatch, import error, and host-version
    incompatibility to produce distinct messages, so that I can tell a storage
    problem from a code problem.
40. As a user, I want the API to verify a bundle's content hash before importing
    it, so that tampered or corrupted bytes never execute.
41. As a user, I want a module handler that raises to produce an ordinary error
    response confined to that request, so that one bad endpoint does not affect
    the rest of the module.
42. As a user, I want only my authenticated session to be able to publish, so that
    the publish path is not an open code-execution endpoint.
43. As a user, I want module routes to require authentication like every other
    non-public route, so that publishing a module cannot widen the API's public
    surface.
44. As a user, I want a module load failure never to crash a cold start, so that
    an unrelated request is never punished for a broken module.

### Unifying `y ui` into `y module`

45. As a user, I want one command for publishable units, so that I never have to
    ask whether something is a "UI artifact" or a "module".
46. As a user, I want existing UI-only artifacts to keep working as UI-only
    modules, so that the unification is a rename rather than a rewrite.
47. As a user, I want the browser loader, hash verification, error boundaries, and
    `@y/host` contract to carry over untouched, so that the unification does not
    put five shipped panels at risk.
48. As a user, I want existing artifact sources relocated into module directories,
    so that "everything for a domain in one place" is true rather than aspirational.
49. As a user, I want the rename to be a hard cut with no `y ui` alias, so that
    there is one name for one concept.

### Finance as the reference module

50. As a user, I want finance's derived logic, API routes, CLI commands, and UI to
    live in one module, so that the concept is proven on the domain that motivated
    it.
51. As a user, I want a change like todo 3018's realized-trade list to reach the
    web UI without a backend deploy, so that the problem that started this is
    actually solved.
52. As a user, I want finance to behave exactly as before after migration, so that
    the change is invisible in daily use.
53. As a user, I want the built-in finance controller, CLI group, and derived
    services deleted rather than kept as a fallback, so that there is one
    implementation and no ambiguity about which one is live.
54. As a user, I want the scheduled finance sync to keep working unchanged, so
    that migrating the read path does not disturb the write path.

## Implementation Decisions

### Execution model: in-process dynamic import in the API

Module Python is fetched, verified, and imported **inside the API process**. It
reads PostgreSQL directly through host repositories, the same way the built-in
controller does today.

Two alternatives were considered and rejected:

- **Proxy module endpoints to the VM over SSH**, running `y <slug> ... --json`
  and returning the output. Instantly hot, since the VM is an editable checkout,
  and there is precedent in the existing finance refresh path. Rejected because
  it reverts a settled decision: plan-2184 deliberately moved finance *off*
  per-request SSH onto normalized DB tables read directly from the API, and this
  would reintroduce EC2 wake latency and a hard availability dependency on the
  instance for every read.
- **Skip hot-loading and make deploys fast**, replacing `sam build && sam deploy`
  with a prebuilt-zip `update-function-code`. Roughly ten seconds instead of
  minutes, with almost no new architecture. Rejected because it addresses only
  the latency symptom: no module boundary, no per-domain version history, no
  rollback narrower than the entire backend, and a finance one-liner still
  redeploys the whole API.

The security framing is inherited from the dynamic UI artifact system and is the
same framing, not a weaker one: **the boundary is authorship and integrity, not
runtime containment.** The publisher is the owner and their own agents, who can
already ship arbitrary code through the deploy pipeline; this is a new path, not
a new capability. Controls are ownership scoping, authenticated publish, content
hash verification before import, and an immutable version audit trail.

### Route surface: per-version sub-app behind one catch-all

The host declares exactly one route for all modules:

```
/api/module/{slug}/{path:path}
```

The handler resolves the slug's active version, obtains the loaded module
(cached by bundle sha256), and forwards the request into a **per-version
sub-application** constructed from the `APIRouter` the module exports, with the
`/api/module/<slug>` prefix stripped.

Two alternatives were rejected:

- **A generic action-dispatch endpoint** (`{action: handler}` dict, hand-parsed
  params). Simple, but it discards `Query` validation, path parameters, and
  response typing, making module handlers materially worse to write than the
  built-in controllers they replace.
- **Mounting the module's router into the live app.** This would preserve
  `/api/finance/*` URLs, but FastAPI has no supported way to *remove* routes, so
  a version switch inside a warm container leaves stale routes behind and the
  route table becomes per-container mutable state. This is the standard failure
  mode of dynamic backend loading and is avoided entirely.

Constructing a new sub-app per version is cheap and disposable: switching
versions means building a new object and dropping the old one, which is ordinary
garbage collection rather than surgery on a running router.

**URLs move**, with no compatibility shim: `/api/finance/investment-returns`
becomes `/api/module/finance/investment-returns`. This is safe by construction
because the only consumer is the finance UI, which lives in the same atomic
version and therefore moves in lockstep. The CLI is unaffected either way, since
it imports logic directly and never calls the API.

`AuthMiddleware` runs before the catch-all, so `request.state.user_id` is
populated exactly as it is today. **Modules cannot serve unauthenticated
routes**: the public-route allowlist is host-owned, and publishing a module must
never be able to widen the API's public surface.

### The host surface: what a module may import

| Layer | Owner | Rationale |
|---|---|---|
| Derived / business logic | **Module** | The code that changes weekly. The point of the feature. |
| API route handlers | **Module** | Follows the logic it wraps. |
| CLI commands and renderers | **Module** | Same. |
| ORM entities, tables, migrations | **Host** | Migrations are already manual SQL run by the maintainer; coupling a hot path to a slow one defeats the purpose. |
| Repositories, DB session, auth, user resolution | **Host** | The stable imported surface. |
| Python dependencies | **Host** | A module may import only what the API already ships. Adding a dependency is a normal deploy. Direct mirror of the UI externals contract. |
| Worker tasks, routines, scheduled jobs | **Host** | Different runtime and lifecycle; out of scope for v1. |

**Repositories stay host-side, so a module cannot write its own SQL**; it
composes existing repository calls. This keeps modules from silently depending
on column layout. The accepted ceiling: a genuinely new query shape needs a repo
change, and therefore a deploy. In practice the derived services already load
window rows and compute in Python, so this is not expected to bite; if it does,
the escape hatch is exposing a read-only session to modules later.

**Write endpoints are allowed.** There is no read-only restriction; the trust
model is identical to UI artifacts.

The Python host surface carries **its own contract version**, independent of the
`@y/host` browser contract, because the two evolve for unrelated reasons. A
module records a backend contract floor at publish time; a module requiring a
newer host than the running API refuses to load with an explicit message.

### Loading mechanics

The published API bundle is an archive, so a module is not forced into one file.
Loading, in the API process:

```
resolve active version for slug
  -> cached by sha256?  yes -> use it
  -> fetch bundle bytes (S3 or local bundle dir)
  -> verify sha256(bytes) === version.api_sha256
  -> materialize under /tmp and import under a version-unique package name
  -> module.router : APIRouter
  -> build sub-app, cache by sha256
```

Two details are load-bearing. Imports use a **version-unique top-level package
name** derived from slug and hash, so two versions of the same module can coexist
in one warm container without colliding in `sys.modules` mid-switch. And the
cache key is the **content hash**, not the version id, so an unchanged rebuild
reuses a loaded module and a rollback to an already-loaded version is free.

Cold-start cost, fetch plus verify plus import on the first request to a module
route, is accepted. It is bounded, it is paid once per container per module, and
it applies only to modules actually called.

### Atomic joint versioning

One `module_version` row spans both published halves. Publishing builds both,
records both, and moves one pointer.

```
module
  module_id           public string id
  user_id             owner (FK)
  slug                unique per owner
  active_version_id   FK -> module_version, nullable
  enabled             bool

module_version
  version_id           public string id
  module_id            FK
  version_no           monotonic per module
  -- UI part (nullable: a backend-only module has none)
  ui_sha256
  ui_storage_key
  label
  icon
  min_host_version     browser contract floor
  -- API part (nullable: a UI-only module has none)
  api_sha256
  api_storage_key
  min_backend_version  Python host surface floor
  source_digest
  built_at
  description
```

Both parts are nullable, which is what makes "a UI artifact is a module with
only a UI part" true in the schema rather than only in prose.

**The CLI part is deliberately not versioned.** It is never published and never
stored; it is always read from local source on disk. This is a real asymmetry and
is stated rather than hidden: the CLI is the *development* surface and the
published version is the *deployed* surface. A rollback restores the API and UI;
it does not touch what the CLI runs, because the CLI runs whatever is currently
on disk. The corollary is the intended workflow, iterate against the CLI, then
publish the source you tested.

### CLI dynamic command registration

The dynamic UI artifact PRD explicitly ruled this out, on the grounds that
importing remote Python into `y` is a materially harsher problem than a browser
ES module. That reasoning is superseded by a fact about the current install, not
by a change of risk appetite: **`y` already executes Python out of the user's
home directory**, because the VM's tool install is editable and points at the
working checkout. Importing `$Y_AGENT_HOME/modules/<slug>/` is the same
capability, differently spelled.

The CLI scans the modules directory and registers one click group per slug,
**lazily**: a custom group resolver imports only the module actually invoked. `y`
is on the hot path for every agent turn, and the root group already imports
around thirty command modules eagerly; module discovery must not add to that.

The CLI reads **local source, never the published bundle**. There is no
fetch-the-bundle fallback in v1: a second code path for a case that may never
arise. The known consequence is that `y <slug>` does not exist on a machine
without the module source, which after the finance migration means the Mac.
`$Y_AGENT_HOME` exists on both machines, so the mechanism works anywhere the
source is present; getting it there is `y file download`.

### Failure isolation

Once backend code ships outside the deploy pipeline there is no CI between a
mistake and the running API, so failure handling is a requirement rather than
polish.

- Bundles load **lazily, on first request** to a module route. A broken module
  cannot affect an unrelated endpoint and cannot crash a cold start.
- Fetch failure, hash mismatch, import error, and backend-version incompatibility
  each return a distinct error naming slug, version, and failure kind, the
  server-side mirror of the loader's distinct error cards.
- A handler that raises produces an ordinary error response confined to that
  request inside the sub-app.
- On the CLI side, lazy per-group import gives the same property for free: a
  module whose `cli.py` fails to import breaks only `y <slug>`.
- Recovery is `y module rollback <slug>`, not restoring repo code.

### Unification: `y ui` becomes `y module`

A hard cut, no alias, matching how the `y ... list` time filters were cut.

| Surface | Change |
|---|---|
| Tables | `ui_artifact` → `module`, `ui_artifact_version` → `module_version`; `sha256`/`storage_key` → `ui_sha256`/`ui_storage_key`; add nullable API-part columns. Manual SQL, run by the maintainer. |
| Endpoints | `/api/ui/*` → `/api/module/*` |
| CLI | `y ui create/list/versions/publish/rollback/activate/enable/disable/delete` → `y module ...` |
| Web loader | Retargeted to the new endpoints; ships in the bundle, deploys with the app. |
| `@y/host` contract | **Unchanged, no version bump.** The artifact-facing surface does not know what the table is called. |
| VM source layout | `$Y_AGENT_HOME/ui/<slug>.tsx` and `<slug>/` → `$Y_AGENT_HOME/modules/<slug>/` |

The browser runtime contract stays authoritative in the dynamic UI artifacts
PRD. This PRD owns module identity, versioning, publish, the CLI surface, and
the backend half.

**Cutover ordering is a hard requirement, not a hope.** Renaming the endpoints
means the API and the web bundle must deploy together, and all existing
artifacts must be republished from their relocated sources. The prior PRD already
documents a live instance of this hazard, where a contract bump stranded any
artifact published in the deploy gap. Same shape here, so the sequence is
specified rather than discovered: migrate the DB, deploy API and web together,
relocate sources, republish every module, and run no publish in the gap.

The source relocation invalidates the `/Users/roy/luohy15/ui/...` paths recorded
in existing plan notes and delivery records. Those records are historical and are
not rewritten.

### The finance seam

Every importer of the finance code was traced. The seam is not "everything named
`finance_*`":

| Code | Owner | Why |
|---|---|---|
| Derived / positions / price-series / fundamentals / realtime-quote services | **Module** | Read and derive side. Nothing outside finance imports them. |
| Finance controller, `y finance` command group including the `beancount` subgroup | **Module** | The worker shells `y finance beancount ...` over SSH onto the VM, where module source lives, so this keeps working unchanged. |
| Thin CRUD services for holdings, prices, transactions, and finance config | **Host** | The scheduled worker sync writes through them, and the worker is host-side. |
| Entities, repositories, DTOs | **Host** | Per the host surface split. |

The module is the **read/derive half**; the host keeps the **write/sync half**.
The line is principled rather than convenient: the sync path is scheduled
infrastructure, the derive path is what changes weekly.

**The built-ins are deleted outright.** No dual-run, no in-bundle fallback: the
same bet already taken when the built-in Finance, Bots, Calendar, and Todo
surfaces were removed after their artifact migrations.

## Testing Decisions

Test the observable contract, not the loader's internals.

- **Publish and rollback semantics** are the highest-value target and need no
  runtime loading: a publish creates one immutable version spanning both parts
  and moves the pointer; a failed build leaves the active version untouched;
  rollback repoints both halves without rebuilding; activating a historical
  version by number works. Service-level tests, the established pattern on the
  Python side.
- **Atomicity is the distinguishing property** of this design over the previous
  one, so it gets an explicit test: there is no reachable state in which the
  active version's API and UI halves come from different publishes.
- **Integrity enforcement must be tested as a negative**, and matters more here
  than in the browser: a bundle whose bytes do not match the recorded hash is
  refused and never imported. This is the control standing in for runtime
  containment.
- **Failure isolation** is tested by asserting the blast radius, not the message:
  a module that fails to load returns its distinct error on its own routes while
  unrelated endpoints answer normally, and each failure kind is distinguishable.
- **Version-unique import naming**: two versions of one module load in the same
  process without collision. This is the subtle bug that would otherwise appear
  only under warm-container version switches in production.
- **Backend contract gating**: a module declaring a floor above the running host
  refuses to load and reports why.
- **Lazy CLI registration**: invoking an unrelated command does not import module
  code, and a module whose CLI raises on import leaves other groups working. The
  first is a performance guarantee on the agent hot path and deserves an assertion
  rather than trust.
- **Finance migration is verified by behavioral equivalence**: the module's
  endpoints return the same figures for the same inputs as the built-in
  controller did. The existing finance service tests are the prior art and move
  with the code they cover.
- Not worth testing: esbuild's correctness, the exact bytes of a build, or
  FastAPI's own routing.

## Out of Scope

- **Worker tasks, routines, and scheduled jobs as module parts.** A module is
  API + CLI + UI. The worker is a different runtime with a different lifecycle,
  and the finance reference case does not need it.
- **Module-owned tables and migrations.** Schema stays in the repo, applied as
  manual SQL. Finance needs no new tables.
- **Module-owned raw SQL.** Repositories are host-side; modules compose them.
- **Adding Python dependencies without a deploy.** The importable set is fixed by
  the deployed API image.
- **Publishing the CLI half.** The CLI always runs local source; it is not
  versioned, not uploaded, and not covered by rollback.
- **Sandboxed execution of untrusted third-party modules.** v1 assumes
  owner-authored code. If modules ever come from other authors, the isolation
  model must be revisited.
- **Sharing modules between users, or a module marketplace.**
- **Unauthenticated module routes.** The public-route allowlist stays host-owned.
- **Automatic rollback on failure.** Failure surfaces an explicit error; it does
  not silently change what is live.
- **Migrating domains other than finance.** Existing UI-only artifacts are
  renamed into modules but keep only a UI part; giving them backends is separate
  work.
- **Changing the browser runtime contract.** The loader, hash verification, error
  boundaries, externals set, and `@y/host` surface carry over untouched and remain
  owned by the dynamic UI artifacts PRD.
- **A compatibility shim for `/api/finance/*` or `y ui`.** Hard cut.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3020 | Requirements converged and PRD written: in-process module loading in the API behind a per-version sub-app, lazy local-source CLI registration, atomic API+UI versioning, `y ui` folded into `y module`, finance as the reference migration | - | - | - | - | planned |
