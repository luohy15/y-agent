---
title: Module System
type: prd
project: y-agent
feature: module-system
status: active
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

The data layer is where this bites hardest, and it is worth being precise about
why. Schema changes are *already* out of band: migrations are hand-written SQL in
a gitignored directory, applied with psql, never gated on a deploy. What is gated
on a deploy is the ORM model of that schema, and the repository holding the
queries. So adding one column to a finance table costs a psql run the user
controls, plus a full backend redeploy for the two files that describe the column
they just added. A domain's data model is the part of it most likely to change
alongside its logic, and it was the part furthest from the fast loop.

## Solution

A **module** is a user-owned, versioned unit that contains everything for one
domain: its data model, its API routes, its CLI commands, its business logic, and
its UI. It lives in one directory on the user's VM, publishes as data, and loads
at runtime without deploying the application.

"Everything" is meant literally, down to the database. A module owns its ORM
entities, its repositories, its knowledge of its own schema, and the migration
SQL that shapes it. The host contributes a database connection and transaction
management, and nothing else about data. A domain's tables, the models over
them, and the queries against them live in one directory with one owner, instead
of being split across a repo that deploys slowly and a module that publishes
fast.

The authoring loop is a directory and a command. Module source lives at
`code/y-module/<slug>/`, a fixed path (`/Users/roy/luohy15/code/y-module`)
independent of `Y_AGENT_HOME`. The CLI picks up the module's commands directly
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
PostgreSQL directly, through its own repositories over a host-provided session,
so nothing about the data path changes: no SSH hop, no proxy, no latency
regression.

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

### Module-owned data

11. As a module author, I want my module to define its own ORM entities, so that a
    domain's tables are described where the domain lives rather than in a package
    that deploys on a different clock.
12. As a module author, I want my module to own its repositories and write its own
    queries, so that a new query shape is a module edit rather than a host change
    and a deploy.
13. As a module author, I want my module's entities registered in their own
    metadata rather than the host's, so that two versions of one module can be
    resident in the same process without colliding.
14. As a module author, I want the host to give me a database session with
    transaction handling, so that I get connection pooling and commit/rollback
    semantics without owning connection management.
15. As a module author, I want my migration SQL to live in my module directory, so
    that the DDL, the models over it, and the queries against it are one unit with
    one history.
16. As a user, I want migrations applied only by me, by hand, so that publishing
    code can never reshape my database as a side effect.
17. As a user, I want `y module schema-sql <slug>` to print DDL derived from the
    module's models, so that writing the migration for a new table is mechanical
    rather than transcription.
18. As a user, I want a publish to be refused when the module's models reference
    tables or columns the database does not have, so that forgetting to run the
    migration fails at publish rather than on a user's request.
19. As a user, I want a module's tables to be unaffected by host database
    initialization, so that host deploys never create, alter, or reason about
    module schema.

### API routes

20. As a module author, I want to declare routes with an ordinary FastAPI
    `APIRouter`, so that authoring a module handler is the same work as writing a
    built-in controller.
21. As a module author, I want `Query` validation, path parameters, and
    `HTTPException` to work normally, so that migrating an existing controller is
    close to a file move.
22. As a module author, I want the authenticated user resolved by the host before
    my handler runs, so that I never handle tokens.
23. As a user, I want module routes reachable at a predictable path derived from
    the slug, so that the UI knows where to call without extra configuration.
24. As a user, I want module code loaded only when one of its routes is actually
    requested, so that a module I never call costs nothing.
25. As a user, I want a loaded version cached for the life of the container, so
    that repeated requests do not refetch and re-import code.
26. As a user, I want a version switch to take effect without restarting
    anything, so that publishing is the only step.

### CLI commands

27. As a user, I want a module's commands to appear under `y <slug>`, so that a
    module-owned command is invoked exactly like a built-in one.
28. As a user, I want module commands discovered from the modules directory
    automatically, so that adding a module does not mean editing the CLI's
    command registry.
29. As a user, I want a module's code imported only when one of its commands is
    actually invoked, so that module discovery does not slow down every `y`
    invocation on the agent hot path.
30. As a user, I want a module whose CLI fails to import to break only its own
    command group, so that one bad module does not make `y` unusable.
31. As a user, I want the CLI to read local source rather than the published
    bundle, so that I can test a change before promoting it.

### Background jobs

32. As a user, I want a module's scheduled work to be one of its own CLI commands,
    so that a background job is written, run, and debugged exactly like anything
    else in the module.
33. As a user, I want a routine that runs a command directly instead of firing an
    agent session, so that a deterministic data sync costs no model call and
    produces no conversation.
34. As a user, I want a scheduled module command to run on my VM against local
    source, so that changing what a job does needs no publish.
35. As a user, I want modules to have no worker-side code, so that module Python
    runs in exactly one runtime and I never debug a bundle loaded inside a
    background Lambda.

### The host surface

36. As a module author, I want a small, explicit set of host capabilities —
    session and transaction management, the resolved authenticated user, VM
    command execution — so that the surface I depend on is one I can hold in my
    head.
37. As a module author, I want the host surface versioned with a stated stability
    obligation, so that a published module keeps working after the host
    redeploys.
38. As a user, I want a module built against a newer host surface than the running
    API to refuse to load with a clear message, so that version skew surfaces as
    an explicit error rather than a confusing runtime failure.
39. ~~As a module author, I want the browser-side contract to stay exactly as it is
    today, so that migrating an existing artifact into a module changes its
    address, not its code.~~ Superseded (todo 3042): the contract held unchanged
    through the finance, bot, calendar, todo, and module migrations, but chat
    needed a third UI slot and host-owned render leaves, so `@y/host` went v4 → v5
    and gained a `shell` surface. See *The `shell` surface and the renderer seam*.

### Cross-module boundaries

40. As a module author, I want to reference host kernel tables such as the owning
    user, so that module rows belong to a user the same way host rows do.
41. As a user, I want no module to read another module's tables, so that a module
    can change its own schema without breaking code it cannot see.
42. As a user, I want a table needed by more than one module to live in a `common`
    module, so that shared data still has exactly one owner and stays as
    hot-loadable as everything else.
43. As a module author, I want `common`'s code copied into my bundle at publish
    time, so that my version stays self-contained bytes and a rollback restores
    the shared code I was built against.
44. As a user, I want one module to reach another only through its published HTTP
    routes or CLI, so that the contract between domains is the interface rather
    than the storage layout.

### Atomic versioning and rollback

45. As a user, I want one version to span a module's API and UI, so that "the
    version of finance" is a single unambiguous thing.
46. As a user, I want backend and frontend to activate together, so that a UI can
    never go live expecting a response field the API does not serve yet.
47. As a user, I want every publish to create an immutable version, so that
    history is a real record and not overwritten state.
48. As a user, I want the active version to be a single pointer, so that what is
    live is unambiguous.
49. As a user, I want `y module rollback <slug>` to restore the previous version
    of both halves, so that recovery is one command and cannot leave a mismatched
    pair.
50. As a user, I want rollback to require no rebuild, so that it still works when
    the source is mid-edit or the build is broken.
51. As a user, I want to activate any historical version by number, so that I can
    move to a known-good build, not only the immediately previous one.
52. As a user, I want rollback to restore code without touching my database, so
    that recovery is never a data-loss decision.
53. As a user, I want `y module list` to show my modules, their parts, and their
    active version, so that I can see what is installed at a glance.
54. As a user, I want `y module versions <slug>` to show history with the active
    version marked and each version's description, so that I can correlate a
    version with the change that produced it.
55. As a user, I want to disable a module without deleting it, so that I can turn
    a domain off while keeping its history.
56. As a user, I want `y module delete <slug>` to remove the module and its
    versions while leaving my authoring source and my tables alone, so that
    deleting deployed state never destroys data or working files.

### Safety and failure isolation

57. As a user, I want a module that fails to load to return an error only on its
    own routes, so that a bad publish never takes down unrelated endpoints.
58. As a user, I want fetch failure, hash mismatch, import error, and host-version
    incompatibility to produce distinct messages, so that I can tell a storage
    problem from a code problem.
59. As a user, I want the API to verify a bundle's content hash before importing
    it, so that tampered or corrupted bytes never execute.
60. As a user, I want a module handler that raises to produce an ordinary error
    response confined to that request, so that one bad endpoint does not affect
    the rest of the module.
61. As a user, I want only my authenticated session to be able to publish, so that
    the publish path is not an open code-execution endpoint.
62. As a user, I want module routes to require authentication like every other
    non-public route, so that publishing a module cannot widen the API's public
    surface.
63. As a user, I want a module load failure never to crash a cold start, so that
    an unrelated request is never punished for a broken module.

### Unifying `y ui` into `y module`

64. As a user, I want one command for publishable units, so that I never have to
    ask whether something is a "UI artifact" or a "module".
65. As a user, I want existing UI-only artifacts to keep working as UI-only
    modules, so that the unification is a rename rather than a rewrite.
66. As a user, I want the browser loader, hash verification, error boundaries, and
    `@y/host` contract to carry over untouched, so that the unification does not
    put five shipped panels at risk.
67. As a user, I want existing artifact sources relocated into module directories,
    so that "everything for a domain in one place" is true rather than aspirational.
68. As a user, I want the rename to be a hard cut with no `y ui` alias, so that
    there is one name for one concept.

### Finance as the reference module

69. As a user, I want finance's tables, entities, repositories, derived logic, API
    routes, CLI commands, and UI to live in one module, so that the concept is
    proven end to end on the domain that motivated it.
70. As a user, I want a change like todo 3018's realized-trade list to reach the
    web UI without a backend deploy, so that the problem that started this is
    actually solved.
71. As a user, I want a new finance column to cost one hand-run migration and one
    publish, so that extending the data model is no longer a deploy.
72. As a user, I want finance to behave exactly as before after migration, so that
    the change is invisible in daily use.
73. As a user, I want the built-in finance controller, CLI group, services,
    repositories, and entities deleted rather than kept as a fallback, so that
    there is one implementation and no ambiguity about which one is live.
74. As a user, I want finance Refresh to move with the finance module while
    host-owned auth, session management, and VM execution remain stable, so that
    the domain boundary is complete without pulling infrastructure into
    publishable code.
75. As a user, I want the dead worker finance sync deleted rather than migrated, so
    that the reference module carries no code that was already unreachable.

## Implementation Decisions

### Execution model: in-process dynamic import in the API

Module Python is fetched, verified, and imported **inside the API process**. It
reads PostgreSQL directly, through its own repositories over a host-provided
session, on the same connection pool the built-in controllers use today.

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

The security framing is inherited from the dynamic UI artifact system but must be
stated *tightened* for backend code: because a loaded API half executes
in-process under the shared API database/AWS role, the runtime boundary is
authorship and integrity, **not** containment. In v1 that is an explicit
trusted-principal rule, not just ownership scoping: **publish is restricted to a
single, explicitly configured trusted maintainer account** (resolved by its
public `user_id`, never a synthetic "default" user created as a bootstrap row).
The API is multi-user and invite-gated, so mere authentication is deliberately
*not* the boundary for authorship — metadata ownership (one account cannot
repoint another's module) does not prevent uploaded Python from querying every
tenant's rows, reading secrets, or using the Lambda role, so any account other
than the configured maintainer is refused at publish (403), and the check fails
closed when no maintainer is configured. **Who may invoke that maintainer-authored
code is a separate, per-version question**, opened by todo 3042 and answered by
`dispatch_scope` (see *Per-version exposure*): a version published as
`authenticated` is dispatchable by any logged-in account, still resolved and
loaded as the maintainer's, still with the caller's identity bound for data
scoping. That widens the caller set, never the author set, which is why it does
not reopen the containment argument; `maintainer` stays the default, so a module
is exposed only by an explicit, immutable, per-version choice. If multi-user backend modules are ever required, in-process
execution under one DB/AWS identity cannot provide that isolation; it needs a
larger design (for example separate database roles per module). Remaining
controls within the trusted principal are content hash verification before
import and an immutable version audit trail.

Module-owned repositories widen what a loaded bundle can *reach* — a session is a
session, so a module can query any table in the database, including one holding
credentials, and could issue DDL if the role permits it. This is worth stating
plainly, and it changes nothing about the threat model: code running in-process
under the composing-repositories design could already reach the same data by
other means, and the API's database role is not per-module. The mitigations are
the ones above, plus keeping the cross-module rules a review obligation. If
modules ever accept code from other authors, this is the paragraph that must be
revisited first, and the answer would be separate database roles per module
rather than tighter Python.

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
never be able to widen the API's public surface. *Which* authenticated users a
module answers is a per-version property; see the next section.

### Per-version exposure: dispatch scope, claimed surfaces, public UI

Modules began as a single-user feature: every module row is owner-scoped, and the
dispatcher answered only the maintainer account. That is right for a maintenance
console like bot management and wrong for a domain every account uses. Todo 3042
hit it head-on — 124 live users, 114 with at least one chat — where a
maintainer-only chat module would have left 113 accounts with no Chats panel and a
403 on the list route.

The resolution is to make exposure **a property of a published version**, not a
global switch. Three columns live on `module_version`, set from `module.json` at
publish time and immutable afterwards, so a rollback restores the exposure the
code was written for and a republish must re-state it:

| Column | Values | Meaning |
|---|---|---|
| `dispatch_scope` | `maintainer` (default) / `authenticated` | Who may reach `/api/module/<slug>/*` and see the module in `GET /api/module/list`. |
| `ui_surfaces` | comma list drawn from `panel` / `detail` / `shell` (default `panel`) | Which host slots this version **claims**. |
| `ui_public` | boolean (default `false`) | Opt-in for anonymous delivery of UI bytes (public demo lookup and public bundle). Never opens backend dispatch. |

**`dispatch_scope` widens the caller, never the owner.** The dispatcher still
resolves and loads the *maintainer's* active version — one owner, one code
pointer, one loader cache keyed on the bundle hash — and then binds the
**caller** as the request owner, so a module's data access stays scoped to
whoever made the request. A non-maintainer's `GET /api/module/list` returns only
enabled modules whose active version is `authenticated`, projected down to the
fields the browser loader needs (`version_id`, `version_no`, `ui_sha256`,
`min_host_version`, `ui_surfaces`, label, icon) — never storage keys, the API
hash, or the source digest. Two alternatives were rejected: widening the gate
globally, which would have exposed maintenance modules like bot management to
every account, and keeping the host built-ins as a non-maintainer fallback, which
means two implementations and no DRY win. The consequence worth stating: a
module's maintainer-only guarantee is no longer a global property of the system,
it is whatever its **active version** declared. Bot's stays true because every bot
version publishes the `maintainer` default; a republish that adds
`"dispatch": "authenticated"` to `module.json` widens that module and nothing else
warns, and a rollback restores the scope the older version was published with.

**`ui_surfaces` records what a version claims, not what it has.** Only `shell` is
enforced from the column: the host picks the shell claimant from module metadata
*before* fetching any bundle, because the slot has to be decided while the
conversation is mounting. `panel` and `detail` are still introspected from the
loaded bundle's exports, and the loader still requires a `panel`, so a version
declaring `shell` alone still gets a sidebar entry. The column's name promises
more than it delivers; treat it as a claim on host slots, not as a manifest of
the bundle.

**`ui_public` gates anonymous UI-byte delivery.** It is the version-level opt-in
for public demo lookup and public bundle routes (Option B of
`pages/decision-3042-public-dispatch-scope.md`: anonymous *UI bytes only*, never
anonymous backend dispatch). Host public-demo routes consume it; *Unauthenticated
module routes* (backend dispatch) remain out of scope.

### The host surface: a kernel, not a data layer

The host keeps only what is genuinely shared infrastructure. Everything that
describes or interprets a domain belongs to the module, **including its data
model**.

| Layer | Owner | Rationale |
|---|---|---|
| Derived / business logic | **Module** | The code that changes weekly. The point of the feature. |
| API route handlers | **Module** | Follows the logic it wraps. |
| CLI commands and renderers | **Module** | Same. |
| ORM entities and table definitions | **Module** | A table's shape is domain knowledge. Splitting the model from the queries over it puts one table's definition on two clocks. Narrow exception: `bot_config` / `bot_route_state` stay host tables because worker runtime code reads them; see *Bot as the second full-stack module*. |
| Repositories and queries | **Module** | A new query shape must not require a host change and a deploy; that ceiling was the main cost of the earlier boundary. |
| Migration SQL | **Module** | Lives beside the models it changes, applied by hand by the owner. |
| Database connection, session, transaction management | **Host** | Pooling and commit/rollback semantics are infrastructure, and one engine per process is not negotiable. |
| Auth and resolved authenticated user | **Host** | Publishing a module must never be able to widen or weaken authentication. |
| VM command execution | **Host** | Credentials, SSH, and EC2 lifecycle are infrastructure. |
| Python dependencies | **Host** | A module may import only what the API already ships. Adding a dependency is a normal deploy. Direct mirror of the UI externals contract. |
| Worker tasks and Lambda runtimes | **Host** | Modules have no worker part at all; see *Background jobs*. |
| Tables shared by more than one module | **`common` module** | Shared data still has one owner, and stays hot-loadable rather than frozen into the deploy cycle. |

The kernel a module imports is therefore small and stable: a database session
with transaction handling, the resolved user, and
`run_vm_command(user_id, vm_name, argv, timeout=...)`. Modules do not receive
`Tool`, VM credentials, Paramiko objects, worker internals, or raw engine
handles.

**The resolved user has two halves, and both are host-resolved.** The API half
reads `request.state.user_id`, set by the host's auth middleware. The CLI half
has no request, so the kernel also exposes `cli_user_id()`, which resolves the
same identity the rest of `y` uses. Without it a module's CLI would have to
import a host service to know who it is acting for, which the rules below
forbid; with it, "who am I acting for" has exactly one host-owned answer on
both sides.

**A module marks the kernel tables it references but does not own.** D4 allows
`user_id -> user.id`, and SQLAlchemy cannot resolve that foreign key unless the
`user` table is present in the module's own `MetaData` — `sorted_tables` and
`CreateTable` both raise without it. So the module declares a reference stub and
tags it with the kernel's `EXTERNAL_TABLE_INFO_KEY` marker. Host tooling that
walks module metadata (publish preflight, `y module schema-sql`) filters those
stubs out through one host-owned helper: a module never has its kernel-table
stub preflighted as if it owned it, and `schema-sql` never emits DDL that would
recreate a host table. The marker is the smallest explicit representation of the
difference between *referencing* a table and *owning* one; without it, ownership
would have to be inferred from a hardcoded list of host table names.

**A module writing its own SQL is now the design, not a leak.** The earlier
boundary kept repositories host-side to stop modules depending on column layout;
that reasoning inverts once the module owns the columns. A module depending on
its own schema is not coupling, it is ownership. What remains forbidden is
depending on *someone else's* schema, which the cross-module rules below make
explicit.

**Write endpoints are allowed.** There is no read-only restriction; the trust
model is identical to UI artifacts. Finance proves this with its refresh route:
the module owns the route, its orchestration, and the writes it performs.

**Module entities declare their own `DeclarativeBase`.** This is forced rather
than stylistic. Bundles are imported under version-unique package names so two
versions of one module can be resident in one warm container, and a shared
`MetaData` would raise `Table 'finance_holding' is already defined` at the moment
of a version switch. Separate metadata also removes module tables from the host's
`init_tables()` import list, which is the point: host database initialization,
including the daily `init_db` schedule, neither creates nor reasons about module
schema.

The Python host surface carries **its own contract version**, independent of the
`@y/host` browser contract, because the two evolve for unrelated reasons. A
module records a backend contract floor at publish time; a module requiring a
newer host than the running API refuses to load with an explicit message.

Backend contract **v1** was: `session()`, `run_vm_command()`, `cli_user_id()`,
and `EXTERNAL_TABLE_INFO_KEY`, plus the named pure-function allowlist
(`storage.service.time_range`, `storage.util` timestamp helpers). The last two
arrived with the finance migration rather than the first sketch of the surface,
and shipped as v1 rather than a v2 bump only because v1 had never shipped at the
time finance was written: no host carrying `BACKEND_CONTRACT_VERSION` had been
deployed and no backend module version had been published against it, so no
published module could observe the difference.

That argument is now retired. Todo 3028 (bot module consolidation) is the surface's
first genuine addition: a narrow bot-config store —
`bot_config_list` / `bot_config_get` / `bot_config_upsert` / `bot_config_delete` /
`bot_config_set_enabled` / `bot_config_rename` — operating on host-owned
`BotConfig` values only (no repositories, no raw sessions, no entities, no
generic host-table access), request-owner-scoped exactly like
`run_vm_command()`. That addition bumped `BACKEND_CONTRACT_VERSION` from 1 to 2;
the bot module declares `min_backend_version: 2` while finance continues to
declare 1 because it never needed the new surface.

Todo 3042 added the second, in the same shape: `chat_list` / `chat_get` /
`chat_create_share`, request-owner-bound and returning plain dictionaries rather
than entities, sessions, or repositories. That bumped
`BACKEND_CONTRACT_VERSION` from 2 to **3**, and the chat module declares
`min_backend_version: 3`. `chat_mark_read` was deliberately left out: the host
service behind it takes no `user_id`, so exposing it would have been an unscoped
write, and its route has no caller in web or CLI. The pattern is now the
established one for a control-plane module over host-owned runtime state — a
short list of named, owner-bound functions, added as a version bump, never a
generic table accessor.

Todo 3068 added the first extension to an *existing* capability rather than a
new one: `run_vm_command` gained explicit `work_dir` and stdin parameters
(the underlying local/SSH execution already supported both; the file module
is the first caller that needs them as part of the contract rather than a
host-internal default), plus a new narrow lookup, `note_list_at_path`, so the
file module's rename endpoint can enforce the note `content_key` guard
without importing the note service. That bumped `BACKEND_CONTRACT_VERSION`
from 3 to **4**, and the file module declares `min_backend_version: 4`. See
*File: a control-plane module over VM infrastructure* below.

Todo 3071 added the note control-plane surface (`note_list` / `note_get` /
`note_create` / `note_import` / `note_update` / `note_delete` /
`note_list_by_todo` / `note_relation_create` / `note_relation_delete` /
`note_relations_by_todo` / `note_relations_by_note`), bumping
`BACKEND_CONTRACT_VERSION` from 4 to **5**; the note module declares
`min_backend_version: 5`. Todo 3137 extended the existing chat list row dict
with `needs_attention`, bumping it from 5 to **6**. Todo 3152 extends
`chat_list` again with optional closed `sort_by` (`updated_at` | `created_at`)
and `sort_order` (`asc` | `desc`) parameters — separate parameters, not a
combined sort enum — defaulting to `updated_at` + `desc` so callers that omit
them keep pure-recency order. That bumps `BACKEND_CONTRACT_VERSION` from 6 to
**7**, and the chat module raises its floor to 7 so list ordering stays
server-side and globally correct across pagination. On the host query path,
`created_at` ordering applies `NULLS LAST` in both directions because a large
historical cohort has NULL `created_at_unix` with no recoverable source; the
`updated_at` branch keeps its pre-3152 form so `idx_chat_user_updated` stays
usable. The ownership boundary is unchanged: the host still owns the `chat`
table and list query; the module owns the controls and validates/forwards the
sort choice.

Todo 3164 added the owner-bound tag control-plane surface
(`tag_list_vocabulary` / `tag_get` / `tag_add` / `tag_remove` / `tag_backfill`)
over host-owned `entity_tag` state, bumping `BACKEND_CONTRACT_VERSION` from 7
to **8**. Todo 3169 then enriched the existing `tag_get` todo row shape with
`updated_at_unix` (the todo row's own timestamp, not the list's effective chat
activity value) so the tag module can sort drill-down todos by recency without
a second fetch or host-imposed display policy. That surface-shape change bumps
`BACKEND_CONTRACT_VERSION` from 8 to **9**; the tag module raises its floor to
9 when it depends on the field. Other carrier row shapes are unchanged, and
API/CLI lookup order stays incidental: presentation ordering remains a module
concern.

**v1 has shipped and been
superseded**, so the versioning rule going forward is the plain one stated
above: every later addition to the host surface is a version bump, and a module
that needs it raises its `min_backend_version`; a host below a module's declared
floor refuses to load that module's bundle with an explicit message
(`agent/src/agent/module_host.py` carries the authoritative capability list per
version; `agent/tests/test_module_host.py` and `api/tests/test_module_runtime.py`
pin the floor-rejection behavior).

### Migrations: owner-applied, never automatic

Module migration SQL lives in the module directory and is applied **by the owner,
by hand**, exactly as host migrations are today. There is no migration runner, no
DDL at publish time, and no DDL at activation time. Loading a bundle never
touches schema.

This is a deliberate refusal of the obvious convenience. An automatic runner
would mean an HTTP request or a pointer move could alter the database, which
turns a code rollback into a data event and makes the blast radius of a bad
publish unbounded. Hand-applied SQL keeps the destructive operation attached to a
human decision, and it is not the slow part of the loop anyway: schema changes
were never gated on a deploy, only the ORM models were.

`y module schema-sql <slug>` generates `CREATE TABLE` DDL from the module's own
metadata as an authoring aid. It **prints**; it never executes. Bootstrapping a
module on a fresh database is that output, reviewed, piped to psql by the owner.

### Code/schema skew: publish-time preflight, no runtime gate

Ownership puts a module's two halves on different clocks — code moves by pointer
in seconds, schema moves when the owner runs psql — so drift is a real failure
mode with three directions:

| Drift | Severity | Handling |
|---|---|---|
| Code published that needs schema not yet applied | Common; fails at request time with a raw SQL error after the pointer already moved | **Prevented**: publish-time preflight |
| Code rolled back to a version predating a column | Benign; an unused column is invisible | None needed |
| Destructive DDL applied (drop / rename / narrow) | Breaks every rollback-reachable older bundle at once | **Discipline**: expand/contract |

`y module publish <slug>` walks the module's own metadata and checks every table
and column against live `information_schema`, refusing the publish when the
models reference schema the database does not have. This needs no revision table
and no stamping step to forget, because the database is already the authoritative
record of what has been applied, and it folds into the existing rule that a failed
publish leaves the active version untouched.

There is deliberately **no runtime schema check at bundle load**. It would buy
only a nicer message for a case the preflight already prevents, at the cost of an
`information_schema` query on every cold load, and failure isolation already
bounds the blast radius to the module's own routes.

Destructive changes cannot be caught at publish time by construction, so they are
a stated discipline: **migrations are expand-only while any older version is still
rollback-reachable**. Removing a column is a two-step contract — publish code that
stops using it, then drop it — which is the standard expand/migrate/contract
pattern and costs nothing extra when the SQL is being written by hand regardless.

**Rollback restores code, never data.** `y module rollback` moves a pointer; it
does not run down-migrations, and `y module delete` leaves the module's tables in
place. Recovery is never a data-loss decision.

### Cross-module data access

One table has exactly one owner, and only its owner reads it directly.

| Reference | Verdict |
|---|---|
| Module table → host kernel table (`finance_holding.user_id → user.id`, FK with `ON DELETE CASCADE`) | **Allowed.** Kernel schema changes only through a host deploy, so a module can depend on it as it depends on the Python host contract. |
| Module A code → module B's tables | **Forbidden.** B reshapes its schema at any publish with no coordination; the read would break silently, at a distance, with no version pin. |
| Module A table → FK to module B's table | **Forbidden.** Same, plus it couples two independently applied migration timelines and creates create/drop ordering nobody owns. |
| Host code → module tables | **Forbidden.** The host must not know any module's schema, or the ownership claim is fiction. |

The escape hatch for genuinely shared data is a **`common` module** rather than
promotion into the host: a table read by more than one module is by definition
not private, so it moves to `common`, which owns it like any other module owns
its own tables. Shared data therefore stays hot-loadable instead of being frozen
into the deploy cycle, and the one-owner-per-table rule survives intact.

`common` owns **tables**, not cross-schema queries. Letting `common` hold a query
that joins two modules' private tables would not remove the coupling, only
relocate it: `common` would become the schema-dependent reader that the fourth
row forbids for the host, breakable by either module's next migration with no
signal at publish time.

Consumers get `common` by **build-time vendoring**: `y module publish finance`
copies `code/y-module/common/` into finance's bundle. A module version stays
self-contained bytes, so the single-pointer atomicity the versioning design rests
on is preserved — rolling back finance restores the `common` code it was built and
tested against. A runtime dependency edge with declared version floors and loader
resolution was rejected: it means rolling back `common` can break `finance` while
rolling back `finance` does not restore `common`, and that is a dependency graph
with currently zero demand. The cost of vendoring is that `common`'s DDL has a
single timeline shared with older vendored copies, so its migrations are
expand-only under the same discipline as any other module's.

Anything a module needs from another domain's *behavior*, as opposed to its
storage, it gets through that module's published HTTP routes or CLI.

### Background jobs

**A module has no worker part.** Its scheduled work is one of its own CLI
commands, and the host contributes only a trigger.

The `routine` table is already a generic per-user cron scheduler with a pre-fire
guard, ticked by the admin Lambda. Today its only action is chat dispatch, which
fires an agent session; that remains available and is how a judgment-shaped
routine should run. For deterministic work it gains a second action type: **run
an argv on the owner's VM** via the same `run_vm_command` capability the host
already exposes to modules. A module's scheduled sync is then `y finance sync`
plus a routine row — no model call, no conversation, no bundle loading anywhere.

Running module code inside the worker Lambda was rejected. It would put module
Python in a second runtime with its own image, dependency set, contract version,
failure isolation, and Lambda lease/handoff semantics, in exchange for nothing
that VM execution does not already provide.

Two consequences are stated rather than left to be discovered:

- **Scheduled jobs run local source, so they are unversioned**, the same asymmetry
  already accepted for the CLI half. A rollback restores API and UI; it does not
  change what a scheduled job runs.
- **A module's schedule is host data, not part of its version.** The `routine` row
  is created by hand and survives publish, rollback, and delete.

Jobs inherit the EC2 instance's wake latency and availability. That is correct for
daily syncs and wrong for anything latency-critical; nothing in scope is.

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
  ui_surfaces          claimed host slots: comma list of panel/detail/shell
  ui_public            opt-in: anonymous UI-byte delivery (public demo/bundle; never backend dispatch)
  -- API part (nullable: a UI-only module has none)
  api_sha256
  api_storage_key
  min_backend_version  Python host surface floor
  -- exposure (version-level, see Per-version exposure)
  dispatch_scope       maintainer | authenticated
  source_digest
  built_at
  description
  trace_id             todo/trace this version was published for
```

Both parts are nullable, which is what makes "a UI artifact is a module with
only a UI part" true in the schema rather than only in prose.

**`icon` is a validated host registry key.** `module.json` declares the icon
stored on every immutable `module_version`; `y module publish` rejects unknown
keys before building. The valid keys are `chart`, `calendar`, `list`, `bot`,
`todo`, `file`, `file-text`, `package`, `box`, and `message`. `box` is the
`y module create --icon` default and the host rendering fallback for unknown
legacy persisted values. The host owns the SVG registry so every module stays
small and existing published versions can gain a corrected glyph through an
ordinary host deploy.

**The CLI part is deliberately not versioned.** It is never published and never
stored; it is always read from local source on disk. This is a real asymmetry and
is stated rather than hidden: the CLI is the *development* surface and the
published version is the *deployed* surface. A rollback restores the API and UI;
it does not touch what the CLI runs, because the CLI runs whatever is currently
on disk. The corollary is the intended workflow, iterate against the CLI, then
publish the source you tested. Scheduled jobs inherit this asymmetry, since a job
is a CLI command.

**Schema is not versioned either, and for a stronger reason.** The version
pointer governs code only. Migrations are applied by hand and never reversed by
the system, so a version is a claim about what code was running, not about what
the database looked like. The publish-time preflight is what keeps the two
consistent in the forward direction, and the expand-only discipline is what keeps
older versions loadable in the backward one.

### CLI dynamic command registration

The dynamic UI artifact PRD explicitly ruled this out, on the grounds that
importing remote Python into `y` is a materially harsher problem than a browser
ES module. That reasoning is superseded by a fact about the current install, not
by a change of risk appetite: **`y` already executes Python out of the user's
home directory**, because the VM's tool install is editable and points at the
working checkout. Importing `code/y-module/<slug>/` is the same
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

Finance established the clean reference case: **nothing outside finance touches
finance data.** Its entities are imported only by finance repositories and
services; the only outward schema edge is an integer `user_id`. The boundary is
**domain versus infrastructure**, not reads versus writes: the module owns its
tables, models, queries, HTTP behavior (including Refresh), and CLI; the host
keeps auth, session/transaction management, VM execution, and dependencies. This
supersedes the part of decision 3020-D2 that had the host retaining finance
writer services for a worker path that never existed. Built-ins were deleted
outright (no dual-run, no in-bundle fallback). Instance inventory and hazards:
`code/y-module/finance/README.md`.

### Bot as the second full-stack module: a host-kernel-table exception

Bot established a deliberate exception to "ORM entities and table definitions:
**Module**". Unlike finance, `bot_config` is read on the worker dispatch hot path
(`agent/config.py`, `worker/runner.py`, usage sync, inline/link bots, `y init`).
Modules have no worker half, and host code must not read module-owned tables, so
a finance-style data move was impossible.

The rule: when (and only when) host runtime code outside the API process depends
on domain state on a hot path, that state may stay host kernel and the module
becomes a **control-plane** over it through a narrow, versioned `module_host`
capability (`bot_config_*` on backend contract v2). The module owns management
surfaces; the host keeps the tables and routing-selection routes such as
`GET /api/chat/bot-options`. This is not a general escape hatch from
module-owns-its-tables. Authorization decision:
`pages/decision-3028-bot-module-auth.md`. Instance inventory:
`code/y-module/bot/README.md`.

### The `shell` surface and the renderer seam

Until todo 3042 the browser contract had two slots: a no-props `panel` in the
~280px sidebar, required, and an optional `detail` that opens full-width as a
tab. Chat's live conversation is neither. It is the persistent centre column, and
a `detail` tab is unmounted when closed, which would tear down a live SSE
session mid-turn.

**Panel location is a v6 host capability.** A module may mount the same `panel`
export in either sidebar, including simultaneous mounts, without receiving props.
`@y/host` therefore exports `usePanelLocation(): "left" | "right"`. The host's
`ArtifactMount` provides the location through React context only for
`surface="panel"`; it defaults to `"left"` when the host caller does not specify
a location. `detail` and `shell` mounts do not provide a panel location and the
hook consequently retains its `"left"` default there. This additive browser
contract v6 capability describes placement only. It does not prescribe any
module behavior.

**`shell` is the third slot**: an optional export, claimed through `ui_surfaces`,
occupied by **at most one module at a time** (the lowest slug among enabled
claimants, which is a tie-break rather than a feature). The host resolves the
claimant from module metadata before fetching any bundle, and the slot has an
explicit precedence order: logged-out renders the host branch and never waits on
the module list; a logged-in user whose module list is still loading waits rather
than mounting a fallback that would open a wasted SSE; an enabled claimant
mounts; otherwise the host renders `ChatFallbackView`. Like the other surfaces it
receives **no props**: what the shell module needs from the app arrives through
the existing intent channel, and what it needs the app to do goes out through
`runHostCommand` (the host registers nine for chat, e.g. `chat.open`, `chat.setTraceFilter`,
`chat.openFile`, `chat.openArtifact`, `chat.openTrace`).

**The renderer seam is below the bubble, not above the list.** A shell module that
merely orchestrated a host-owned message list would leave the part that actually
changes weekly — how a message looks — on the deploy clock, which is the whole
problem this feature exists to solve. So the module owns the message list, the
bubble and its chrome, the message parser, the export view, layout, markdown
component overrides, citation and file-link presentation, and the artifact
**fence dispatch** (deciding that a fence is mermaid / vega-lite / artifact-svg
and in which mode). The host owns every leaf whose dependency is measured in
megabytes and hands them to the module as component values on `@y/host`:
`ArtifactView` / `ArtifactRenderer` (mermaid, vega, DOMPurify, highlight.js),
`PatchDiff` (`@pierre/diffs/react`), `ImageLightbox`, the PNG capture
primitive, and (since todo 3068 / contract v7) `CodeEditor` (CodeMirror with
host-lazy language grammars). The rule of thumb: **the module owns everything
that decides what a message looks like; the host owns every leaf measured in
megabytes.**

The numbers are why the seam sits there. Bundling the whole subtree into the
module produces **20.8 MB** (shiki grammars ≈ 9.95 MB, the artifact subtree
≈ 10.3 MB, because esbuild inlines `import()` when splitting is off). With the
leaves external it is 479 KB, and with `react-markdown` + `remark-gfm` also
external it is **102 KB** — the same order as bot (155 KB) and finance (238 KB).
Chat's shipped v5 UI is ~170 KB against a stated 250 KB ceiling.

`react-markdown` and `remark-gfm` becoming externals is the first growth of the
externals list since contract v4 added `swr/infinite`, and it is free in the
dimension that list was protecting: both are already eager in the host's main chunk and stay there,
because the host's own renderer still uses them, so the main chunk gains 0 bytes.
mermaid, vega, cytoscape, and katex remain **not** externals: they are already
lazily split chunks reached from inside host code, and making them externals
would move their cost from first-artifact-render to before-shell-mount. That is
the content of the `@y/host` **v4 → v5** bump, together with the exported leaf set
and a default parsing set the module may use as-is or replace.

**Drift control is one degraded host renderer plus physically shared leaves.**
The host keeps exactly one simple renderer, `HostMessageView` (markdown plus the
leaves above, ceiling 300 lines), used by three call sites: the public trace
projection `/t/:shareId`, the public chat share `/s/:shareId`, and
`ChatFallbackView`. Everything carrying real rendering logic is one physical copy
shared with the module, so only bubble chrome and layout *can* diverge — which is
the deliberate "the fallback is plainer" property, not an accident. The line
ceiling is the tripwire: growth past it means the host renderer is drifting back
toward parity and the seam should be revisited rather than quietly re-implemented.

The version-coupling consequence inverts, and that is the point: **message
rendering is now a `y module publish`**, and only a change to an artifact, diff,
or image leaf needs a host web deploy.

### Chat: a control-plane module over the runtime kernel

Chat extends the bot control-plane precedent in two directions: a domain every
account uses (per-version `dispatch_scope: authenticated`) and a domain that
owns the app's centre column (the `shell` surface and the renderer seam). The
module owns **browsing and presentation**; the host owns the **runtime**.

Four hard constraints shaped the boundary. Modules having no worker half, no
unauthenticated routes, and no host reads of module tables all still stand, so
the `chat` table/worker/Telegram path and every conversational route stay host.
Maintainer-only backend dispatch was the one that dissolved: it became a
per-version property (*Per-version exposure*). `y chat` is a **hybrid group**:
dispatch (`-m` / `-i`), `stop`, `attach`, and import stay built-in so a bad
module edit cannot take out the recovery mechanism; browse subcommands fall
through to module CLI. Under every failure mode, conversations remain reachable
through host routes and `ChatFallbackView`. Instance inventory and hazards:
`code/y-module/chat/README.md`. Scope decision:
`pages/decision-3042-chat-module-scope.md`.

### File: a control-plane module over VM infrastructure

File established that a module may own a **control plane over host VM
infrastructure** with no database tables of its own. Files are credentials,
SSH, EC2 lifecycle, and local-vs-remote execution — not module-owned data. The
module owns authenticated file HTTP, the transfer CLI, and the Files panel /
`detail` workspace; the host keeps VM credentials/execution, request-owner
enforcement, the note `content_key` rename guard (via `note_list_at_path`), and
the generic special/public tab shell in `FileViewer.tsx`.

Two transferable operational lessons. (1) After a browser-contract bump, verify
the live `__Y_HOST__.version`; a green deploy report is not proof the new
bundle is being served. (2) A module published against routes another module is
about to cut must be retargeted first. Backend contract v4 added
`run_vm_command` work_dir/stdin and `note_list_at_path`; browser contract v7
exported host `CodeEditor` after direct CodeMirror bundling breached the module
size ceiling (`pages/decision-3068-codemirror-bundle-measurement.md`). Instance
inventory and hazards: `code/y-module/file/README.md`.

### Tag: a presentation module over shared kernel projection state

Tag is a presentation module over the host-owned **`entity_tag` projection**.
The module owns the authenticated `/api/module/tag/*` facade, lazy `y tag` CLI,
and `artifact:tag` panel. Its backend uses the owner-bound `tag_*` capabilities
introduced in backend contract v8 and enriched in v9 (`tag_get` todo rows carry
`updated_at_unix` for client-side recency sorting); it neither reads the
database directly nor duplicates normalization or resolver behavior. The host
retains the projection table, normalization, carrier synchronization and
cleanup, resolver hydration, every carrier's exact-tag filters, and the
`tag.open` navigation adapter. Presentation ordering (todo recency, note
alphabetical) is module-owned. Disabling or deleting the module removes tag
browsing and command presentation only. Carrier authoring, projection
maintenance, and filters keep working in the kernel. Instance inventory:
`code/y-module/tag/README.md`.

### Note: a control-plane module over shared kernel state

Note is a control-plane module over **shared host kernel state**, not a
finance-style data move. Host code reads note state on unauthenticated and
in-process share paths (`trace.py`, public shares, the file rename guard), so
the `note` / `note_todo_relation` / `note_share` tables, all five share routes,
`y assoc note`, the todo 3041 content-path authority, and `PublicNoteList` stay
host. The module owns the authenticated authoring/browsing surface and reaches
host note state only through the owner-bound `note_*` capability (backend
contract v5). Disable or rollback therefore affects the authenticated control
plane, not public shares or the association primitive. Instance inventory:
`code/y-module/note/README.md`.

### Host CSS contract (additive, not versioned)

Beyond the `@y/host` browser contract and the `sol-*` color-token contract (see
`pages/feature-y-agent-theming.md`), host `web/src/style.css` ships an
**append-only CSS class contract** for module UI: `.y-check` and `.y-field`, plus
theme keys `--radius` and `--shadow-float` registered in
`cli/src/yagent/sdk/theme.css` under `@theme reference`. Modules apply the class
names from TSX and inherit the tokens at runtime; the class names must never be
renamed while older module versions stay rollback-reachable. Full control
conventions live in `docs/prd/design-language.md`.

## Documentation ownership

y-agent documents the **host**: architecture, the module-system contract and its
precedents, host-retained tables/routes/render leaves, and the backend/browser
contract versions it ships. The standalone `y-module` repository documents each
**module**: what it owns, its surfaces, routes, CLI, host capabilities it
depends on, and its rollback hazards. Where both are true, y-agent states the
rule and y-module states the instance.

Active version numbers and bundle hashes are queryable (`y module list`,
`y module versions <slug>`) and must not be restated in prose in either repo.
Known-bad version *ranges* are not queryable and remain durable knowledge in
each module README's rollback-hazards list. Historical Delivery Records rows
are exempt and stay verbatim.

Public docs under `docs/*.md` (copied into the deployed SPA by
`scripts/build-docs.sh`) are a user surface, not an authority surface: they
describe what a user can do, drop internal ownership/version prose, and gain
**no** links into the private y-module repository.

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
- **Version-unique import naming and metadata isolation**: two versions of one
  module, each declaring the same tables against its own `DeclarativeBase`, load
  in the same process without collision. This is the subtle bug that would
  otherwise appear only under warm-container version switches in production, and
  it is the reason module entities may not share the host's `Base`.
- **Backend contract gating**: a module declaring a floor above the running host
  refuses to load and reports why.
- **Schema preflight is tested in both directions**: a publish is refused when a
  model references a table or column the database lacks, and succeeds once the
  migration has been applied. The negative case is the one that matters, since it
  is the whole reason the check exists.
- **Preflight failure leaves the active version untouched** — same assertion shape
  as a failed build, and worth its own test because it is what makes a rejected
  publish safe rather than merely annoying.
- **Host database initialization ignores module tables**: running `init_tables()`
  creates no module-owned table and errors on none. This asserts the metadata
  separation from the host's side.
- **Lazy CLI registration**: invoking an unrelated command does not import module
  code, and a module whose CLI raises on import leaves other groups working. The
  first is a performance guarantee on the agent hot path and deserves an assertion
  rather than trust.
- **Finance migration is verified by behavioral equivalence**: the module's
  endpoints return the same figures for the same inputs as the built-in
  controller did. The existing finance service and repository tests are the prior
  art and move into the module with the code they cover, including the ones that
  now exercise module-owned entities.
- Not worth testing: esbuild's correctness, the exact bytes of a build, SQLAlchemy's
  own DDL generation, or FastAPI's own routing.

The cross-module access rules are **not mechanically enforced** and so are not
tested. Nothing stops a module from importing another's package or querying its
table; the rule is upheld in authoring and review, the same way the host's
"controllers do not call repositories directly" convention is. Making it
enforceable would require either separate database roles per module or an import
hook, both of which cost more than the single-user failure mode justifies.

## Out of Scope

- **Module code running in the worker Lambda.** A module is data + API + CLI + UI.
  Scheduled work is a module CLI command triggered by a host routine, so module
  Python runs in exactly one runtime.
- **An automatic migration runner, and DDL at publish or activation time.**
  Migrations are applied by the owner, by hand. `y module schema-sql` prints DDL
  and never executes it.
- **Down-migrations and data rollback.** The version pointer governs code only;
  recovery never destroys data.
- **A runtime schema check at bundle load.** The publish-time preflight covers the
  drift direction that actually occurs.
- **Schedules declared in the module manifest and reconciled by publish.** Routine
  rows are created by hand; revisit when a second module wants one.
- **A runtime module dependency graph.** `common` is vendored at build time; there
  are no declared inter-module version floors and no loader-side resolution.
- **Cross-module table access, and `common` as a holder of cross-schema queries.**
  A table read by more than one module moves into `common` and is owned there.
- **Mechanical enforcement of the cross-module rules.** No per-module database
  role, no import hook; the boundary is upheld by authoring and review.
- **Adding Python dependencies without a deploy.** The importable set is fixed by
  the deployed API image.
- **Publishing the CLI half.** The CLI always runs local source; it is not
  versioned, not uploaded, and not covered by rollback.
- **Sandboxed execution of untrusted third-party modules.** v1 assumes
  owner-authored code. If modules ever come from other authors, the isolation
  model must be revisited.
- **Sharing modules between users, or a module marketplace.**
- **Unauthenticated module routes.** The public-route allowlist stays host-owned.
  `module_version.ui_public` is the live opt-in for anonymous *UI-bytes* delivery
  (public demo lookup and public bundle); anonymous backend dispatch is not on
  the table (`pages/decision-3042-public-dispatch-scope.md`).
- **Automatic rollback on failure.** Failure surfaces an explicit error; it does
  not silently change what is live.
- **Migrating domains other than finance.** Existing UI-only artifacts are
  renamed into modules but keep only a UI part; giving them backends is separate
  work. (As of todo 3028, bot is that separate work done, and as of todo 3042 so
  is chat: see *Bot as the second full-stack module* and *Chat: a control-plane
  module over the runtime kernel* above. Other UI-only artifacts remain UI-only
  until their own migration.)
- **Changing the browser runtime contract.** The loader, hash verification, error
  boundaries, externals set, and `@y/host` surface carry over untouched and remain
  owned by the dynamic UI artifacts PRD. (Held through five migrations; **partly
  superseded by todo 3042**, which added the `shell` surface, two externals, and
  the host render leaves as `@y/host` v5. The loader, hash verification, and error
  boundaries are still untouched, and ownership still sits with that PRD.)
- **A compatibility shim for `/api/finance/*` or `y ui`.** Hard cut.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3020 | Hot-loadable module system live; finance is the reference full-stack module (v20 active, v19 full-stack rollback twin). In-process loading, canonical `$Y_AGENT_HOME/modules` source, atomic API+UI versioning, `y ui` folded into `y module`, module-owned data + hand-applied migrations + publish preflight, trusted-maintainer backend gate, lazy CLI, `routine vm_command`. Built-in finance controller/CLI/storage deleted; routes at `/api/module/finance/*`. Known limitation: finance Refresh is still synchronous and hits the ~30s Cloudflare edge timeout (server work completes). Legacy `vm_config.finance_config` intentionally retained for a later contract. PRD: `code/y-agent/docs/prd/module-system.md`. Rollout: `pages/rollout-3020-finance-module-cutover.md` (executed on main `f50f14e`). | - | `pages/plan-3020-module-system.md` | `pages/decision-3020-module-system-boundaries.md`, `pages/decision-3020-module-system-vm-command-timeout.md` | `pages/review-3020-module-system-phase-1.md`, `pages/review-3020-module-system-phase-2.md`, `pages/review-3020-module-system-phase-3.md`, `pages/review-3020-module-owned-data-phase-4.md`, `pages/review-3020-module-system-phase-5.md`, `pages/review-3020-module-system-phase-6.md`, `pages/review-3020-module-system-phase-7.md`, `pages/review-3020-module-system-phase-7-rereview.md`, `pages/review-3020-module-system-phase-7-final.md`, `pages/review-3020-module-system-phase-8.md`, `pages/review-3020-p0-maintainer-config.md` | shipped |
| 3028 | Bot domain consolidated into the module system as the second full-stack module (v12 active, v11 full-stack rollback twin; v10 and earlier unsafe post-cutover because their UI calls the deleted built-in routes). Hybrid boundary rather than a finance-style full move: the module owns bot **management** (`/api/module/bot/*`, `y bot` CLI, Bots UI panel, pricing display, maintainer-only), while `bot_config` and `bot_route_state` stay **host kernel tables** because the worker reads them on the dispatch hot path and modules have no worker half. Module reaches them only via the new **backend contract v2** `bot_config_*` capability on `agent/module_host.py` (bot declares `min_backend_version: 2`; finance still 1). Built-in bot controller, CLI group, and `storage/service/bot_pricing.py` deleted. `GET /api/chat/bot-options` added and intentionally retained on the host: read-only `name`/`backend`/`model`, all authenticated users, because picking a bot in chat is routing selection, not management. Shipped in two host deploys (A `d1ba83e` additive contract v2, B `7266337` the cut) plus docs `99fbab1`; module source in the home repo at `ba62f8e` / `5dbfa82`. Rollback drill executed: v12 -> v11 -> v12. No DB migration. | - | `pages/plan-3028.md` | `pages/decision-3028-bot-module-auth.md` | `pages/review-3028-subtask2.md`, `pages/review-3028-module-source.md`, `pages/review-3028-cut.md` | shipped |
| 3164 | Tag presentation migrated to the authenticated `tag` module: `/api/module/tag/*`, lazy `y tag`, and `artifact:tag` replace the built-in controller, CLI group, and panel. Backend contract v8 supplies owner-bound `tag_*` capabilities. The host retains the `entity_tag` projection, normalization, carrier synchronization and cleanup, resolver hydration, all exact-tag filters, and `tag.open`; disabling the module therefore affects presentation only. The active module is v1, so `y module rollback tag` is a no-op. Recovery is `y module disable tag` or `y module delete tag`. No database migration. | - | `pages/plan-3164.md` | - | `pages/review-3164-host-tag-capabilities.md`, `pages/review-3164-tag-module-source.md`, `pages/review-3164-live-parity.md` | implemented; static verification passed |
| 3169 | Tag detail presentation ordering: host backend contract v9 enriches `tag_get` todo rows with `updated_at_unix`; the tag module sorts todos by that field descending and notes alphabetically ascending, leaving other carrier groups and fixed group order unchanged. No schema migration; host deploy must precede the v9 module publish. | - | `pages/plan-3169-tag-detail-ordering.md` | - | - | planned |
| 3042 | Chat consolidated into the module system as the **third full-stack module** and the first `shell` claimant (`modules/chat` v5 active, v4 the immediate rollback target). The first audit's "chat stays host kernel" boundary was overridden by Roy and is superseded. Three module-system additions shipped with it: per-version **`dispatch_scope`** (`maintainer` default / `authenticated`, immutable, rolls back with the code) so a module can serve every logged-in account; the **`shell` UI surface** (third slot, one claimant, `ui_surfaces` claim column, host precedence logged-out → loading → module → `ChatFallbackView`) with **`@y/host` v5** (host render leaves `ArtifactView` / `PatchDiff` / `ImageLightbox` / PNG capture exported, `react-markdown` + `remark-gfm` added as externals for 0 main-chunk bytes); and **backend contract v3** (`chat_list` / `chat_get` / `chat_create_share`, request-owner-bound). `module_version.ui_public` shipped as a published-but-inert reservation for anonymous UI bytes (Option B). The module owns browsing, the `panel` / `detail` / `shell` surfaces, the whole message renderer (list, bubble, parser, export view, fence dispatch), `/api/module/chat/{list,content,share}`, and the `y chat list/get/search/share` browse commands; the host keeps the `chat` table/worker/Telegram, every conversational route, the `y chat` dispatch primitive (hybrid group), the megabyte render leaves, and one degraded renderer `HostMessageView` (185 lines against a 300 ceiling) behind `/t/:shareId`, `/s/:shareId`, and `ChatFallbackView`. Host `ChatView` / `MessageList` / `MessageBubble` / `chatMessageParser` / `MessageExportView` and the built-in Chats panel + three browse routes are deleted. Three hand-applied additive migrations, all applied to prod: `migration/3042_module_dispatch_scope.sql` (38 rows backfilled to `maintainer`), `migration/3042_module_ui_surfaces.sql`, `migration/3042_module_ui_public.sql`. Shipped across host deploys `d524468` (P0+P1) → `4dfc72a` (P2) → `d1ae931` / `48e11e2` / `bbe118a` / `2a12f4e` / `7203c33` (V1–V4) → `a91c289` / `b502b5f` → `9625478` (the cut); module source at `7f4e6e5` / `39d2822` / `380ced5` / `73eaef2`. Known follow-ups (not queued): the S3 dispatcher resolves each request twice, and `ArtifactMount`'s inline rollback button 404s for non-maintainers. | - | `pages/plan-3042-control-plane.md`, `pages/plan-3042-chatview.md`, `pages/plan-3042-renderer.md` (`pages/plan-3042-chat-module.md` superseded) | `pages/decision-3042-chat-module-scope.md`, `pages/decision-3042-public-dispatch-scope.md`, `pages/decision-3042-chat-shell-host-seam.md` | `pages/review-3042-chat-module-track-a.md`, `pages/review-3042-control-plane-p0-p1.md`, `pages/review-3042-control-plane-p2.md`, `pages/review-3042-chat-module-p3.md`, `pages/review-3042-chat-snapshot-v3.md`, `pages/review-3042-shell-v1-pb1.md`, `pages/review-3042-host-contract-v5.md`, `pages/review-3042-chat-fallback-v4.md`, `pages/review-3042-chat-module-v2-renderer.md`, `pages/review-3042-host-seam-v5a.md`, `pages/review-3042-chat-cli-p4.md`, `pages/review-3042-chat-cut-v6.md` | shipped; runtime verification pending |
| 3048 | Module management GUI shipped as `module`, a **UI-only** module (v1 active, `ui=7728f7ea…`), not built-in web code: `panel` lists every deployed module (including disabled and never-published rows, so it requests `/api/module/list` without `enabled_only`) and `detail` renders read-only newest-first version history. Reads the host's existing `GET /api/module/list` and `GET /api/module/versions` from the browser through `@y/host` (`API` / `jsonFetcher`), so there is no API half, no `module_host` capability, no new endpoint, and no `web/src` change; slug `module` is safe because the reserved management routes resolve before `/api/module/<slug>/*` dispatch. `dispatch: maintainer` (matches `/versions` owner scoping), `min_backend_version: null`, `surfaces: panel,detail`. Selection crosses panel→detail via module-local namespaced localStorage plus a same-document event, then `openArtifactDetail("module")`. Self-listing is ordinary metadata, not recursive loading. Read-only by design: publish/activate/rollback/enable/disable/delete stay in `y module`. **First-publish caveat:** `y module rollback module` is a no-op at v1 (no version below the active one); recovery until v2 is `y module disable module` / `y module delete module` plus the host `ArtifactMount` failure card. Module source in the home repo at `5c79acc`. No y-agent deploy, no DB migration. Open follow-up (Roy's call): the modules workspace has no JS test toolchain, so the plan's component-test verify steps for M2-M4 were unrunnable and one rendering bug (F1) reached review. | - | `pages/plan-3048-module-management-gui.md` | - | `pages/review-3048-module-management-gui.md` | shipped |
| 3051 | Module versions now store their todo/trace structurally in nullable `module_version.trace_id`; publish sends `Y_TRACE_ID` separately and keeps descriptions plain, while `y module versions` preserves the familiar `[trace]` audit display from the new column. The hand-applied additive migration backfilled and stripped 20 historical numeric prefixes with 0 bracket-prefixed descriptions remaining. The UI-only `module` module v2 (`ui=55a19a63e511…`) adds a clickable trace badge to version history through the existing contract-v4 `todo.openTrace` host command, with no host-contract or `web/src` change. Host shipped on main `a702517`; module source commit `3036fc3`. | - | `pages/plan-3051-module-version-trace.md` | - | `pages/review-3051-module-version-trace.md`, `pages/review-3051-module-ui-trace.md` | shipped; UI verification pending |
| 3105 | Restyled the module management version history as compact, newest-first chronological rows grouped by publish date. Each row emphasizes the description, version, trace, publish time, and UI/API short hashes; the active version is accented. Parts, dispatch scope, and contract floors no longer occupy list columns and are summarized once for the active version in the detail header. Published as `module` v3 (`ui=0cbfbc09c277…`); rollback target is v2 via `y module rollback module`. | `pages/design-3105.html` | - | - | `pages/review-3105-version-history-list.md` | shipped; runtime UI verification pending |
| 3110 | Made the module name heading itself a custom-styled version-history selector, with no separate selector panel, native system select, slug, or parenthetical suffix. The title menu and sidebar share the existing localStorage/event-backed selection authority and stay synchronized in both directions. A follow-up removed erroneous title truncation so short module names render in full. Published as `module` v6 (`ui=6f9126b39a25…`) from y-module `d0c5697`; rollback target is v5 via `y module rollback module`. | - | - | - | `pages/review-3110-module-selector.md` | shipped; runtime UI verification pending |
| 3116 | Sorted modules alphabetically ascending by their displayed name in both the left sidebar and the version-history title selector. One shared display-name helper and ordering function feed both surfaces, preventing ordering or label drift. Published as `module` v7 (`ui=afcc2a47b166…`) from y-module `eb0f93e`; rollback target is v6 via `y module rollback module`. | - | - | - | `pages/review-3116-module-list-ordering.md` | shipped; runtime UI verification pending |
| 3128 | Hardened `module` and `bot` UI payload boundaries against stale truthy non-array SWR values, preventing render-phase crashes and allowing revalidation to self-heal poisoned persisted cache entries. Published as `module` v9 (`ui=0cd7c5506292…`) and `bot` v21 (`ui=22315d44c33b…`, `api=208a45568b7c…`) from y-module `cfa4afe`. Rollback commands are `y module rollback module` and `y module rollback bot`, but rollback does not clear an already-poisoned host cache. | - | `pages/plan-3128-module-bot-render-crash.md` | - | `pages/review-3128-module-bot-payload-guards.md` | shipped; runtime UI verification pending |
| 3061 | Regression fix for the todo 3042 cut: logged-out `/t/:shareId` and `/s/:shareId` rendered every intermediate assistant narration and every tool call as top-level content, because commit `9625478` swapped the deleted `MessageList` (which compacted each turn via `filterLevel0`) for `HostMessageView`, which mapped every parsed message straight to a bubble. Fixed host-side only, in the shared degraded renderer: per-turn display selection shows the user message, one native collapsed `<details>` process summary, and the final assistant, with intermediate content re-using `HostBubble` inside the disclosure so tool output, edit diffs, artifacts, and images stay reachable. All three consumers (`/t`, `/s`, `ChatFallbackView`) get the compact default from one place; `modules/chat`, `ui_public`, and anonymous dispatch are untouched, and the renderer stays under its 300-line ceiling (247). Round-1 review caught a blocker where the process slice ended at the final assistant and dropped trailing tool activity (breaking the live streaming cursor); the fix collects every round message except the selected assistant, preserving order on both sides. Verified live logged-out with Playwright on `https://yovy.app` per Roy's explicit authorization. Shipped on main `9e2c375`. No DB migration, no module publish. | - | `pages/plan-3061-public-share-rendering.md` | - | `pages/review-3061-public-share-rendering.md` | shipped |
| 3068 | File consolidated into the module system as the **fourth full-stack module** and the first with no database tables: a control-plane module over host **VM infrastructure** rather than module-owned data (`modules/file` active **v6**, `ui=8fc9638bac0a` / `api=628244cb50ae`; **v1–v4 all hang on ordinary-file open** — the detail read effect cancelled itself after writing loading state — and **v1–v5 all render Markdown with no table of contents**, so none restores the full current viewer). Ships all 13 authenticated file routes at `/api/module/file/*`, the whole `y file upload`/`download` CLI (not a hybrid group — file transfer isn't the dispatch-recovery mechanism `y chat` is), the Files `panel` (location-independent via v6 `usePanelLocation()`), and a `detail` workspace (`ui:file`) owning every ordinary-file view. **Backend contract v3 → v4**: `run_vm_command` gains `work_dir`/stdin, plus a narrow `note_list_at_path` for the rename guard. **Browser contract v6 → v7**: the host's `CodeEditor` (CodeMirror) is exported as a versioned `@y/host` leaf after `pages/decision-3068-codemirror-bundle-measurement.md` measured direct bundling at ~957 KB against the 250 KB module ceiling; shipped module bundle (panel+detail) is ~93 KB at the cut. `agent/vm_command.py` extracts the VM execution primitive out of the deleted `api.controller.file`, so host `note.py`/`git.py`/`link.py` import it directly instead of from a controller. Host retains VM credentials/execution, request-owner enforcement, the note rename guard, and the generic special/public tab shell in `FileViewer.tsx` (`PublicFileViewer` plus every non-file special tab). Two-deploy cutover per the established pattern: deploy A (additive, main `2a5dba7`/`5a1719b`) then deploy B (built-in cut, main `787e8a0`). Deploy A's web half reported success but did not actually go live — `__Y_HOST__.version` stayed at 6 in production until deploy B, so v1/v2 rendered the loader's version-mismatch card the whole window, masked by the built-in Files panel still serving; browser contract v7 only became live at deploy B. The v2 → v1 → v2 rollback drill was run during that window; no separate drill was run on later pairs. Full boundary and follow-ups in *File: a control-plane module over VM infrastructure* above. **Chat image regression closed post-cut:** published chat v2–v10 called the deleted `/api/file/raw` for image bytes; fixed by publishing chat v11 (retarget to `/api/module/file/raw`) then activating the byte-identical v12 twin from an isolated tree that excluded concurrent chat-trace WIP (both `ui=11107bd79435` / `api=3d77a0331766`; `y module rollback chat` → v11). Chat v2–v10 remain unsafe rollback targets. **File detail Loading regression closed post-cut:** ordinary-file open stuck on `Loading...` forever because the detail read effect both wrote and depended on `data`, so setting `{loading:true}` re-ran the effect, ran the cancel cleanup, and dropped the in-flight response; fixed by publishing file v5 (drop the cancel, keep the `data` dep so Refresh still retriggers; module source `250d5b8`, `ui=e859bebc25dc`). **Markdown viewer TOC restored post-cut:** the built-in responsive TOC was never ported into the module, so v1–v5 all rendered Markdown with no table of contents; fixed by publishing file v6 alone (module-only, local rehype heading ids, no host/contract bump; `ui=8fc9638bac0a` / `api=628244cb50ae`). Rolling back to v5 keeps the Loading fix but drops the TOC; none of v1–v5 restores it. The cut also correctly flagged a cross-trace hazard: then-unpublished `modules/note` (todo 3071) still asserted deleted built-in `/api/file/*` paths. Todo 3071 retargeted those calls to `/api/module/file/*` before publishing note v1/v2 (v2 active, v1 byte-identical rollback twin). This remains a release trap for any module whose dependency is about to hard-cut its routes. `/file/move` still has no note-pointer rename guard (todo 2888 follow-up, pre-existing and unchanged). | - | `pages/plan-3068-file-module.md`, `pages/plan-3068-file-detail-loading.md`, `pages/plan-3068-markdown-toc.md` | `pages/decision-3068-codemirror-bundle-measurement.md` | `pages/review-3068-file-host-capabilities.md`, `pages/review-3068-codeeditor-host-export.md`, `pages/review-3068-file-browser-seam.md`, `pages/review-3068-file-module-api.md`, `pages/review-3068-file-cli.md`, `pages/review-3068-file-panel.md`, `pages/review-3068-file-detail-workspace.md`, `pages/review-3068-file-builtin-cut.md`, `pages/review-3068-file-detail-loading.md`, `pages/review-3068-markdown-toc.md` | shipped; chat image fix live as chat v12 / v11 twin; file Loading fix live as file v5; Markdown TOC live as file v6 (v1–v5 lack it) |
| 3071 | Note consolidated as a control-plane module over shared host kernel state. `modules/note` v2 is active, with byte-identical v1 as rollback twin (`ui=61364ab58245` / `api=5c7a4424f5d5`). The module owns ten authenticated note and note-relation routes at `/api/module/note/*`, `y note`, and the Notes panel. The host retains the `note`, `note_todo_relation`, and `note_share` tables, all five share routes, in-process trace sharing helpers, `y assoc note`, the todo 3041 content-path authority, and `PublicNoteList` for logged-out trace shares. Backend contract v5 adds the owner-bound `note_*` capability. Shipped host capability + contract v5 at `6fdb8e0`, UI seam at `79e7dab`, and hard cut at `d1bbd73`; no database migration. | - | `pages/plan-3071-note-module.md` | - | `pages/review-3071-note-backend-capability.md`, `pages/review-3071-note-host-ui-seam.md`, `pages/review-3071-note-module-source.md`, `pages/review-3071-note-cut.md`, `pages/review-3071-note-docs.md` | shipped |
| 3073 | Module source moved to the standalone `/Users/roy/luohy15/code/y-module` repository: a fixed canonical path with no config key, environment override, symlink, or home-repository ignore rule. The publish-free three-repository cutover is complete. `y-agent` main is pushed with `MODULE_SOURCE_ROOT` as its single resolver authority; tests patch that constant and prove `Y_AGENT_HOME` / `Y_AGENT_MODULES_DIR` cannot override it. The standalone `y-module` repository contains the live private-pushed source; the former `/Users/roy/luohy15/modules` tree has been removed. Current-path docs and stale source comments now name `code/y-module`; historical Delivery Records remain historical. | - | `pages/plan-3073-module-source-repository.md` | - | `pages/review-3073-y-agent-path-cut.md` | shipped |
| 3083 | Restored distinct file, note, module, and chat activity-bar glyphs through the host's canonical module-icon registry; the shared SDK contract now validates icon keys before publish, making an unknown icon a CLI error rather than a silent fallback. Finance and bot were audited and already resolved correctly. Host commit `dc27a1f` deployed successfully, and chat module v13 (`ui=2a83bb3b012b…` / `api=8ecab88cc6b6…`) is active with the restored message-bubble declaration; rollback is `y module rollback chat` to v12. No database migration. | - | `pages/plan-3083-module-icons.md` | - | `pages/review-3083-module-icons.md` | shipped |
| 3084 | Restored file-viewer affordances and the pre-3068 one-host-tab-per-file workspace. The final staged cutover shipped browser contract v8 and rollback-compatible host tab migration on y-agent `558c191` plus CI fix `8f7fe91`, then activated contextual file module v11 from y-module `014b9de`. Host again owns ordinary-file tabs, preview/pin/close/reorder/search/shortcuts/dirty state; the module owns each file's contextual viewer and preserved compact toolbar, Copy feedback, export, Markdown, editor, and media behavior. Rolling back file to v10 automatically collapses to the aggregate `ui:file`; reactivating v11 remigrates retained descriptors. No database migration. Module details and rollback hazards: `code/y-module/file/README.md`. | - | `pages/plan-3084-file-viewer-affordances.md` | - | `pages/review-3084-file-viewer-affordances.md` | shipped; runtime UI verification pending |
| 3107 | File History now resolves the containing Git repository on the selected VM, including linked worktrees, and builds a GitHub commits URL from a usable remote-backed ref plus the path relative to that repository root. Home-workspace files continue to resolve through y-history. Non-repository, untracked, non-GitHub-remote, detached, local-only, and ref/path-mismatch cases omit the action instead of guessing a likely 404. Published as file v12 (`ui=2b11f051f3ef…` / `api=522b9fc5d3d0…`) from y-module `bbfff23`; rollback target is v11 via `y module rollback file`. No host contract change or migration. | - | `pages/plan-3107-repository-aware-file-history.md` | - | `pages/review-3107-repository-aware-file-history.md` | shipped; runtime UI verification pending |
| 3119 | Made file downloads byte-exact by classifying `/read` content on the VM, carrying accepted UTF-8 text as base64, and reserving `/raw` for binary bytes. Binary and files over 10 MB now render a download-only pane instead of an editor or unsupported preview. Published atomically as file v14 (`ui=d22c4779cb76…` / `api=e9626790a071…`) from y-module `66568cc`; v1–v13 remain unsafe rollback targets for binary downloads. The reported ZIP matched production `/raw` byte-for-byte: 12,312 bytes and SHA-256 `81aa33e1882bdf4c8e4bfe85bedc229ff15be1ca63dfe52d1ddbb6d2d79c1c67`. No host contract change, host deploy, or migration. | - | `pages/plan-3119-file-viewer-binary.md` | - | `pages/review-3119-file-viewer-binary.md` | shipped; runtime UI verification pending |
| 3093 | Module documentation ownership split: each module's domain description lives in `code/y-module/<slug>/README.md`; y-agent keeps host architecture, the module-system contract, public user docs, and one pointer per module. Active version numbers/hashes leave prose (queryable via `y module list`); known-bad version ranges stay in module READMEs. PRD gains *Documentation ownership* (D1/D3/D6) and this row. | - | `pages/plan-3093-module-docs-ownership.md` | - | `pages/review-3093-y-module-docs.md`, `pages/review-3093-y-agent-docs-trim.md` | reviewed |
