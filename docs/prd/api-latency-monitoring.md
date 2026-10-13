---
title: API Latency Monitoring
type: prd
project: y-agent
feature: api-latency-monitoring
status: active
---

# API Latency Monitoring

## Problem Statement

y-agent has no durable, privacy-safe account of how long its API requests take.
When a page feels slow or an API change may have regressed performance, the user
has to reproduce the symptom, inspect scattered logs, or optimize from intuition.
There is no baseline that answers which routes are slow, whether latency changed,
how the tail differs from the median, or whether errors and latency moved
together.

Ordinary request logs are not an adequate substitute. They are not a bounded
analytics store, do not provide mergeable latency distributions or percentile
trends, and can accidentally preserve raw paths, query values, identifiers, or
other sensitive and high-cardinality data. Streaming responses, disconnects,
retries, and routes dispatched into hot-loaded modules also make a naive
"middleware start to handler return" timer misleading.

The immediate need is API latency evidence. The durable product boundary is a
broader `monitor` module so later monitoring domains, such as trace monitoring,
can join one operational surface without renaming or fragmenting it. Those later
domains must not inflate the first delivery into a general observability system.

## Solution

Instrument the authoritative server request boundary once and record one bounded,
privacy-safe latency event for each completed inbound API attempt. Route identity
is a normalized matched route template, never a raw URL. Timing spans the full
response lifecycle, including streaming, and classifies exceptional completion
such as cancellation or disconnect. The event contains only the request start,
duration, HTTP method, normalized route, status class, completion class, and a
small allowlisted set of low-cardinality operational dimensions. It never stores
request or response bodies, query strings or values, headers, credentials,
personal data, user or resource identifiers, raw paths, or arbitrary labels.

Retain raw events for 14 days. Build mergeable hourly latency distributions kept
for 90 days and daily distributions kept for one year, with bounded cleanup of
expired data. These distributions support request count, p50, p95, p99, error
rate, and slow-route rankings without averaging percentiles or retaining raw
events indefinitely. Time ranges are rolling `1h`, `6h`, `24h`, `7d`, `30d`,
`90d`, and `1y`, with `24h` as the default. Storage and buckets are UTC; the UI
renders timestamps in the configured user timezone.

Expose the feature in a standalone hot-loadable module with slug `monitor`, label
`Monitor`, and its own sidebar entry. The initial module contains an API Latency
area with a current/recent overview, route ranking, trends, and route-level
drill-down. Clicking a route shows its count, p50, p95, p99, error rate, latency
trend, bounded method/status/completion filters, and no more than 100 recent or
slow raw events. A raw row is intentionally sparse and cannot be expanded into a
request inspector.

The host owns capture at the request boundary and the kernel telemetry state it
must write on every API request. The `monitor` module is the presentation and
query control plane over a narrow, owner-bound host contract. This is the same
kind of deliberate kernel exception used when runtime infrastructure must access
state outside a module-capable API request. It avoids making the host import a
module schema, avoids a second proxy or telemetry service, and still keeps
monitoring queries and UI evolution on the module publish loop.

## User Stories

### Capture boundary and timing

1. As a user, I want every eligible inbound API attempt timed at one authoritative
   server boundary, so that route comparisons use one definition of latency.
2. As a user, I want duration to start when the server receives the request and
   end when the terminal body frame is handed to the outer server, so that the
   measurement includes streaming up to that handoff and excludes time spent
   inside the final send itself (adapter backpressure, or a process freeze
   after the response is already complete). A failed or cancelled handoff is
   not a successful finish: it is measured through the unwind instead.
3. As a user, I want streaming and long-lived responses measured through their
   final body frame, so that a stream is not reported as fast merely because its
   headers were produced quickly.
4. As a user, I want disconnected or cancelled requests classified explicitly,
   so that incomplete work does not silently disappear or masquerade as a normal
   success.
5. As a user, I want requests that fail before producing an ordinary response
   recorded as exceptional completions, so that server failures remain visible.
6. As a user, I want each retry that reaches the API recorded as its own inbound
   attempt, so that telemetry reflects load actually handled without pretending
   the server can infer client retry intent.
7. As a user, I want duration measured with a monotonic clock, so that wall-clock
   adjustments cannot create negative or distorted latency.
8. As a user, I want event start times stored as UTC instants, so that records are
   unambiguous across process timezones and daylight-saving changes.
9. As a user, I want capture to include built-in API routes and hot-loaded module
   routes under the same semantics, so that moving a feature into a module does
   not remove it from monitoring.
10. As a user, I want non-API browser routes and static asset delivery outside the
    API application excluded, so that the dataset describes the y-agent API.
11. As a user, I want health checks, documentation, schema, CORS preflight, and
    other explicitly classified operational-noise endpoints excluded by one
    allowlist, so that probes do not dominate product-route statistics.
12. As a user, I want the monitor module's own read endpoints measured like other
    eligible API routes, so that their cost remains visible rather than becoming
    a blind spot.

### Safe route identity and dimensions

13. As a user, I want a matched route represented by its normalized template, so
    that requests to different resources aggregate under one stable route.
14. As a user, I want hot-loaded module requests attributed to the resolved module
    slug and normalized child route, so that module endpoints remain actionable
    instead of collapsing into one catch-all dispatcher route.
15. As a user, I want unmatched requests assigned to a bounded sentinel category,
    so that a 404 containing a random or secret path cannot create a label or leak
    into storage.
16. As a user, I want telemetry to store the HTTP method and status class, so that
    reads and writes, successes, client failures, and server failures can be
    compared without preserving response content.
17. As a user, I want completion class to distinguish normal, disconnected,
    cancelled, and internal-failure outcomes, so that lifecycle edge cases are
    queryable.
18. As a user, I want any additional operational dimension to come from a finite,
    reviewed allowlist with bounded values, so that cardinality cannot grow from
    request-controlled input.
19. As a user, I want request and response bodies categorically excluded, so that
    monitoring cannot become a second content archive.
20. As a user, I want query strings, query values, headers, cookies, tokens, and
    credentials categorically excluded, so that telemetry cannot capture secrets.
21. As a user, I want user IDs, email addresses, trace IDs, chat IDs, todo IDs,
    resource IDs, IP addresses, user-agent strings, and raw URL paths excluded, so
    that latency evidence is not personal or high-cardinality activity tracking.
22. As a user, I want unknown route and dimension values normalized or dropped
    rather than stored verbatim, so that future endpoints fail closed on privacy
    and cardinality.

### Retention and aggregation

23. As a user, I want raw request events retained for 14 days and then deleted, so
    that recent diagnosis is possible without indefinite event-level history.
24. As a user, I want hourly aggregates retained for 90 days, so that medium-term
    regressions can be investigated after raw events expire.
25. As a user, I want daily aggregates retained for one year, so that long-term
    baselines survive without unbounded growth.
26. As a user, I want retention enforced automatically and idempotently in bounded
    batches, so that cleanup does not depend on manual housekeeping or create a
    large blocking transaction.
27. As a user, I want aggregation to be idempotent and safe to rerun, so that a
    delayed or repeated maintenance run neither loses nor double-counts requests.
28. As a user, I want aggregate distributions to be mergeable across buckets, so
    that p50, p95, and p99 over a selected range are computed from the combined
    distribution rather than averaged from bucket percentiles.
29. As a user, I want aggregation to preserve request count, latency distribution,
    error count, completion classes, and the approved low-cardinality dimensions,
    so that retained history supports the same headline analysis as recent data.
30. As a user, I want UTC bucket boundaries and configured-timezone labels, so that
    storage remains deterministic while the display is locally understandable.
31. As a user, I want partial current buckets included and visibly treated as
    in-progress, so that the current view is fresh without implying a complete
    hour or day.
32. As a user, I want late-arriving records folded into affected aggregates within
    the raw retention window, so that delayed maintenance converges to the raw
    source of truth.
33. As a user, I want raw, hourly, and daily sources selected consistently by range
    and resolution, so that crossing the 14-day or 90-day boundary does not create
    unexplained gaps or double counting.
34. As a user, I want expired raw and aggregate data to be irrecoverable through
    the API after cleanup, so that UI bounds and storage retention agree.

### Overview and ranges

35. As a web user, I want `Monitor` to be a standalone sidebar module, so that
    operational evidence has a stable home rather than being hidden under an
    unrelated feature.
36. As a web user, I want the initial area named API Latency, so that the module can
    later contain other monitoring areas without claiming they already exist.
37. As a web user, I want `1h`, `6h`, `24h`, `7d`, `30d`, `90d`, and `1y` rolling
    ranges, so that I can inspect incidents, regressions, and long-term baselines
    from one surface.
38. As a web user, I want `24h` selected by default, so that opening the module
    gives a useful recent overview without excessive historical smoothing.
39. As a web user, I want the overview to show total request count, p50, p95, p99,
    and error rate for the selected range, so that central tendency, tail latency,
    traffic, and reliability are visible together.
40. As a web user, I want a latency trend at a resolution appropriate to the
    selected range, so that regressions are visible without rendering every raw
    request.
41. As a web user, I want route rankings to show count, p50, p95, p99, and error
    rate, so that a slow route can be evaluated alongside its traffic and health.
42. As a web user, I want the slowest-route ranking to use p95 with an explicit
    minimum sample threshold and to show low-volume routes separately or mark them,
    so that one anomalous request does not outrank a consistently slow route.
43. As a web user, I want routes with no data in the range omitted and the empty
    state explained, so that absence of traffic is not rendered as zero latency.
44. As a web user, I want counts and percentile units formatted consistently while
    retaining exact values in tooltips or accessible detail, so that the overview
    is readable without hiding material differences.
45. As a web user, I want the selected range reflected consistently across every
    overview card, trend, ranking, and drill-down, so that panels cannot silently
    compare different windows.
46. As a web user, I want refresh to revalidate the current data without starting a
    collection job, so that reading telemetry has no hidden operational side
    effect.

### Route drill-down

47. As a web user, I want to open a normalized route from the ranking, so that I
    can move from system symptoms to one endpoint without re-entering filters.
48. As a web user, I want route detail to show request count, p50, p95, p99, and
    error rate over the selected range, so that its headline metrics remain
    comparable with the overview.
49. As a web user, I want a time-bucketed latency trend for the route, so that I
    can locate when its distribution changed.
50. As a web user, I want bounded filters for HTTP method, status class, completion
    class, and approved operational dimensions, so that I can isolate a safe
    cohort without arbitrary label search.
51. As a web user, I want recent and slow event views capped at 100 server-selected
    rows, so that raw access remains diagnostically useful and operationally
    bounded.
52. As a web user, I want a raw row limited to start time, duration, method,
    normalized route, status class, completion class, and approved dimensions, so
    that the event list cannot turn into a request inspector.
53. As a web user, I want event ordering and limits enforced by the server, so that
    changing browser parameters cannot request an unbounded export.
54. As a web user, I want raw event views unavailable beyond the 14-day window with
    an explanation that aggregates remain, so that retention is clear rather than
    appearing as missing data.
55. As a web user, I want no free-text raw-event search, cursorless full scan,
    download-all, or event expansion, so that the first version stays bounded and
    privacy-preserving.
56. As a web user, I want navigation back to the overview to preserve range and
    filters, so that inspecting one route does not discard my monitoring context.

### Correctness, overhead, and operations

57. As a user, I want a baseline to begin at the first verified deployment with its
    collection start visible, so that absent pre-feature history is never
    fabricated or mistaken for zero traffic.
58. As a user, I want controlled requests with known timing and outcomes to verify
    count, duration, route normalization, percentiles, status class, streaming,
    cancellation, and aggregation, so that the dashboard is evidence rather than
    decorative telemetry.
59. As a user, I want aggregate totals reconciled against raw events while those
    events still exist, so that dropped or duplicated records are detectable.
60. As a user, I want privacy and cardinality audits against representative and
    adversarial paths, queries, headers, and identifiers, so that forbidden data
    cannot enter route names or dimensions.
61. As a user, I want retention tested at each raw/hourly/daily boundary, so that
    old data is removed while retained ranges remain continuous.
62. As a user, I want instrumentation overhead measured against an uninstrumented
    baseline across fast, ordinary, and streaming requests, so that the monitor
    does not become a material source of API latency.
63. As a user, I want capture failure isolated from the application response and
    surfaced through bounded operational logging, so that telemetry trouble does
    not take down product requests or fail silently without any signal.
64. As a user, I want monitoring writes and maintenance to avoid recursive API
    requests, so that collecting or reading metrics cannot create an amplification
    loop.
65. As a user, I want storage volume, route cardinality, and dropped-event or
    capture-failure counts inspectable, so that the telemetry system's own health
    can be assessed without broad infrastructure monitoring.
66. As a user, I want existing logging and module conventions reused where they
    satisfy these contracts, so that latency monitoring does not create a parallel
    observability stack.

### Extensible monitor identity

67. As a user, I want the module slug to be `monitor` and its display name to be
    `Monitor`, so that later monitoring areas do not require a migration from a
    latency-specific module identity.
68. As a user, I want API latency to remain an independently named area and feature
    key inside Monitor, so that its requirements and delivery history stay
    discoverable as the module expands.
69. As a user, I want future trace or infrastructure monitoring to arrive through
    separate scoped requirements and deliveries, so that this first version is not
    delayed by speculative observability architecture.
70. As a module maintainer, I want the host-to-module telemetry interface narrow,
    owner-bound, and versioned, so that the module can evolve its views without
    direct access to unrelated host state.

### Daily latency review routine

71. As a user, I want a scheduled daily routine to review API latency against a
    P95-below-one-second objective, so that slow routes become optimization work
    without me reading the Monitor overview every day.
72. As a user, I want a route qualified only when a representative 7d window and a
    corroborating 24h window both meet fixed sample floors and both show P95 at or
    above the threshold, so that one slow request or a stale week cannot open work.
73. As a user, I want the routine to use exact raw-backed percentiles and to create
    nothing when the evidence is approximate, empty, or unreadable, so that a
    finding is never invented from degraded metrics.
74. As a user, I want a clean day to produce no todo, no dispatch, and no message,
    so that the routine is silent unless there is evidence-qualified work.
75. As a user, I want at most one new optimization todo per Asia/Shanghai calendar
    day and at most two routine-created todos open at once, enforced against the
    todo database rather than a log file, so that the work queue cannot flood.
76. As a user, I want candidate routes deduplicated against the full text of every
    pending, active, and awaiting todo, so that routes already owned by open work
    (including todo 3520's eight endpoints) are excluded rather than duplicated.
77. As a user, I want the routine never to modify, resume, dispatch into, or finish
    a user-owned todo, so that automatic creation stays the only automatic write.
78. As a user, I want shared-tail groupings stated as an unproven hypothesis with
    every member route's own numbers preserved in the todo, so that the generated
    task reports evidence without asserting a cause.
79. As a user, I want the generated todo dispatched to dev coordination at tier1 on
    its own new trace, so that optimization work is planned and reviewed like any
    other delivery instead of running inside the routine session.
80. As a user, I want optimization work to stop at local verification plus an
    awaiting handoff with a valid chat pointer, so that no integration,
    publication, deployment, rollback, or production mutation happens without my
    approval.
81. As a user, I want the awaiting report to state that production P95 is not yet
    verified and to name the post-publication Monitor check as my follow-up, so
    that local replay numbers are never presented as the deployed outcome.
82. As a user, I want a hard failure of the routine (CLI missing, auth failure,
    unreadable payload) to send exactly one Telegram line, so that a broken routine
    cannot go silent forever while a clean run still sends nothing.

## Implementation Decisions

### Product and module boundary

- The canonical feature key is `api-latency-monitoring`. The hot-loadable module
  slug is `monitor` and its label is `Monitor`.
- Monitor is a standalone sidebar module. API Latency is its first area, not the
  permanent name of the whole module.
- The first version covers authenticated operational use by the configured module
  maintainer. It is not a public analytics surface.
- Capture is host infrastructure because it must wrap every eligible API request,
  including requests that never reach a module. Query behavior and presentation
  belong to Monitor.
- The telemetry tables are a deliberate host-kernel exception. Host capture and
  maintenance own their writes; Monitor reaches only owner-scoped query operations
  through a narrow versioned host capability. Neither side imports the other's
  runtime implementation or schema.
- This exception does not authorize a general-purpose SQL or metrics capability
  for modules. The contract exposes only the fixed latency queries needed by this
  feature.

### Event contract

- One event represents one inbound attempt observed at the API boundary. Retries
  are separate events; no deduplication or client-attempt inference is performed.
- Duration uses a monotonic clock. The persisted start is an absolute UTC instant.
- A normal response completes when its terminal body frame is handed to the
  outer send. The sample is taken immediately before that await and kept only
  if the handoff succeeds. Streaming duration therefore includes every body
  frame up to the handoff, but not time spent inside the final send: adapter
  scheduling, backpressure, or a freeze after the response is already complete
  (the Lambda adapter can finish the response and freeze the process before
  this coroutine resumes). A failed or cancelled terminal handoff discards the
  candidate and measures through the unwind. Disconnect, cancellation, and an
  exception escaping the application remain distinct bounded completion classes.
  Historical rows already stored under the previous boundary are left as they
  are; they age out with the 14-day raw retention.
- Method, normalized route template, status class, and completion class are the
  core dimensions. Any additional dimension requires an enumerated value set,
  cardinality budget, privacy review, and explicit schema field. Arbitrary label
  maps are rejected.
- Status class, rather than response content or error text, is retained. When a
  request ends without a response status, completion class carries the outcome and
  status class is a bounded unknown value.
- Matched built-in paths use their framework route template. Module paths include
  the resolved module slug plus the matched child template. Unmatched requests use
  a sentinel and never preserve the submitted path.
- Excluded operational noise is governed by one auditable classifier. The initial
  exclusions are health checks, API documentation/schema routes, CORS preflight,
  and non-API/static traffic. Long-lived server-push streams are also excluded:
  their connection duration is a session lifetime, not an API latency signal. The
  initial streaming member is `/api/chat/messages`. Monitor reads are intentionally
  included and marked only by their ordinary normalized route.

### Storage, aggregation, and retention

- Raw events have a hard 14-day retention. Hourly distributions have a hard 90-day
  retention. Daily distributions have a hard one-year retention.
- Aggregates retain a mergeable distribution representation, not only precomputed
  percentile scalars. Range percentiles come from the combined distribution;
  percentiles are never averaged.
- Aggregation and cleanup are deterministic, idempotent maintenance operations.
  They run on a schedule through the existing routine/VM-command convention or an
  already-established host maintenance mechanism selected during planning. No new
  agent-driven background loop is introduced.
- Aggregation revisits a bounded overlap window so late events converge before raw
  expiry. Upserts replace the affected bucket/dimension result atomically.
- Maintenance deletes in bounded batches. Capture and product responses must not
  wait for rollup or retention work.
- Rolling ranges are `1h`, `6h`, `24h`, `7d`, `30d`, `90d`, and `1y`; `24h` is
  default. Recent ranges may use raw or hourly data, medium ranges use hourly data,
  and `1y` uses daily data. The query layer owns seam selection and prevents gaps
  or overlap.
- Buckets and range boundaries are UTC. The configured user timezone affects labels
  only. The current incomplete bucket is included and identified as partial.
- Resolved range label (todo 3580, display-only): the range selector shows the
  applied `summary.start` / `summary.end` in `summary.timezone` via the host
  `@y/host` v14 `ResolvedRangeLabel`. Longer presets (`30d` / `90d` / `1y`) keep
  their bucket-aligned start; the label names the server zone rather than the
  browser zone. No query or seam change.

### Query and UI contract

- The overview returns total count, one merge-derived latency distribution (or its
  p50/p95/p99 projection), error count/rate, a bounded time series, and bounded
  per-route rows for one supported range.
- Error rate is the fraction of completed attempts in the 5xx status class plus
  internal-failure completions over all attempts in the cohort. Disconnects and
  cancellations remain separate outcomes rather than silently counting as 5xx.
- Slowest routes rank by p95 among routes meeting a declared minimum sample count.
  Low-volume routes remain visible but cannot silently win the primary ranking
  from a single request. A user-selected sort field ranks all routes in the
  window globally before the row limit; the default is p95 descending.
- Route detail accepts only the supported range and enumerated filters. It cannot
  accept arbitrary dimensions, SQL-like expressions, raw paths, or user/resource
  identifiers.
- Summary, route-ranking, and route-detail queries push the closed route, method,
  status-class, completion, and module-slug predicates into the raw and rollup
  repository reads. Range selection and percentile semantics stay unchanged:
  exact percentiles on raw seams, merge-derived percentiles on hourly/daily seams.
  Add indexes only when a measured plan shows a filter-specific bottleneck beyond
  the existing `(route, started_at)` / `(route, bucket_start)` indexes.
- The latency query path itself (summary, routes, events, meta) only reads
  storage: it does not call the monitor HTTP API, trigger maintenance, or invoke
  capture. Ordinary outer-middleware capture still records one event for each
  eligible monitor HTTP response after it completes, so reads remain visible
  without recursive instrumentation from the query path.
- Raw event endpoints are limited to the raw retention window and at most 100 rows
  per request, with server-owned ordering modes for recent and slowest. There is no
  unbounded export or free-text search.
- The module view follows the shared y-agent design language and module host
  contracts. Exact visual hierarchy and responsive behavior belong to the linked
  design artifact, not this requirement prose.

### Reliability and overhead

- Telemetry failure is fail-open for the product request: an event write or
  aggregation failure cannot change the request's response status or body.
- Fail-open does not mean silent. Capture failures and dropped events use bounded,
  non-recursive operational signals without logging forbidden request data.
- The implementation must measure added latency and resource cost against a
  capture-disabled baseline. Acceptance requires no material regression at p50 or
  p95 for fast and representative API requests, with the measured method and
  result recorded in the delivery artifacts.
- The first trusted baseline starts only after deployed capture passes correctness,
  privacy, cardinality, retention, and overhead checks. Earlier time ranges show an
  explicit collection-start boundary.

### Daily latency review routine

- The routine is one skill (`api-latency-review`) plus one scheduled routine
  registration, run as a chat dispatch. It reads evidence only through a read-only
  Monitor CLI half over the published Monitor API: no publish, host change,
  contract bump, migration, or worker step. The CLI resolves only from the
  canonical module source checkout, so the routine cannot run until that change
  is integrated there.
- Objective is P95 below 1000 ms. This supersedes the earlier P50 goal for both
  eligibility and the acceptance of generated work. P50, a single fast request,
  or an under-sampled window never substitutes for P95.
- Eligibility requires both windows on raw exact percentiles: `7d` with at least
  100 requests and P95 at or above 1000 ms, and `24h` with at least 20 requests
  and P95 at or above 1000 ms. `7d` is the representative window; `24h` only
  corroborates that the problem is present today. Approximate percentiles in
  either window end the run with a logged limitation and no todo.
- Routes with P95 at or above 1000 ms and P50 below 250 ms are tail-dominated.
  Three or more such routes form one candidate whose description states only that
  their medians are fast while they share a P95 band, and that a common cause is
  an unproven hypothesis to investigate. When that candidate does not form, because
  fewer than three tail-dominated routes survive or because the shared-tail grouping
  is switched off, those routes are not discarded: they group ordinarily like any
  other eligible route. Ordinary grouping is by owning surface when two or more
  routes share it, and a route that shares its surface with no other becomes its own
  single-route candidate. Every eligible route therefore belongs to exactly one
  candidate, and one or two evidence-qualified fast-median routes can never end a run
  as clean. Already-owned routes are trimmed before grouping, so no grouping threshold
  is re-evaluated afterwards. Candidates rank by 7d P95 and one run takes the top one.
- Caps: `max_new_per_day=1` counted by Asia/Shanghai creation date across all todo
  statuses including completed and deleted, and `max_open=2` routine-created todos
  in pending, active, or awaiting. A routine-created todo is identified by a
  `latency-candidate: <key>` marker line in its description, so both caps are
  derived from the todo database and survive retries, re-runs, and ledger loss.
  Both counts are trusted only after every list and every record read passes the
  same validation: a list is accepted only as the exact empty sentinel or a known
  table shape, any unexplained row rejects the run rather than being filtered
  away, and each record must carry the requested id. A command that exits
  successfully with malformed output is an uncertainty, not an empty result, for
  the open dump and the day dump alike.
- Deduplication scans the full text of every pending, active, and awaiting todo,
  matching route identity literally and delimiter-aware rather than by substring or
  regex, and retaining the owning todo id. A route that appears only inside a
  previously generated todo's exclusion line is not owned by it, so work is not
  suppressed indefinitely after the real owner closes. A matched member route is
  removed from the eligible set before grouping and recorded as covered by that
  todo. Todo 3520 is a dedup source only: it is never modified, resumed, or
  dispatched into, and a shared-tail candidate never claims to cover or supersede
  its per-endpoint work.
- The ledger `start`/terminal lines and the run-overlap guard are advisory only.
  Two runs starting inside the same read/append window both proceed; the caps are
  therefore best-effort and must never be described as guaranteed. There is no
  time-based guard expiry and no liveness inference from chat text, which shows
  assistant commentary while tools are still running: an unterminated start line
  always skips the run. Every ledger line carries its run id so a healthy run is
  never mistaken for a crashed one. Repeated blocking surfaces as a hard failure
  on the fourth consecutive invocation blocked by the same run, after three
  prior skips, for the user to clear by hand; that count is a notification trigger
  and never a liveness conclusion. If a race ever fires in practice, a routine
  guard function would narrow the window but is not an atomic reservation across
  scheduler and manual invocations, so it stays a tentative suggestion rather
  than a planned fix.
- Dispatch recovery is pending-only: a routine-created pending todo with the
  marker, the authorization-boundary clause, and zero chats on its trace is
  dispatched once. The routine never recovers, resumes, or finishes an awaiting
  or active todo, and never auto-finishes any user-owned todo. Any failure to
  obtain dedup or recovery inputs creates nothing (skip on uncertainty).
- Creation and dispatch each require a confirmed receipt: a parsed todo id and a
  parsed chat id. A failed or unparsable creation is reported as unconfirmed and is
  never retried, since the write may have landed. A dispatch error is an
  unconfirmed handoff, not proof that the todo was left pending: the enqueue may
  have succeeded before the receipt was lost. The run therefore keeps the known
  todo id in both the ledger line and the notification, never retries, and leaves
  the next run's zero-chat check to decide whether recovery applies. A success
  outcome is never reported from an unconfirmed write.
- The ranking the API returns is capped at 100 rows per window, so a window that
  returns a full page of rows all meeting the sample floor is treated as possibly
  truncated and the run stops without a verdict. A clean or under-sampled result is
  never claimed from a possibly capped list.
- The generated todo is dispatched to `dev` at tier1 on its own new trace
  (trace id equals the new todo id). Its description carries every member
  route's 7d and 24h P95, P50, and count, the window bounds and source, the
  marker line, the two-tier acceptance, and the authorization boundary.
- Acceptance is two-tiered. Local: a stated replay protocol (at least 30
  requests, named parameters, cache state, measurement boundary) with before and
  after P95 and explicit sample and window limits. Production: P95 below 1000 ms
  in Monitor over a window meeting the same sample floors, observable only after
  publication and never claimed at awaiting time.
- Optimization work stops at local verification plus `awaiting` with a valid chat
  pointer. Integration into shared branches, publication, deployment, rollback,
  and production mutation each need the user's approval; the routine's
  registration, enabling, and the module CLI integration are likewise not
  authorized by this feature and remain the user's steps.
- Notification: the platform notifies only when the routine's dispatch itself
  raises, never on a session outcome, so the session sends exactly one Telegram
  line on hard failure and nothing on creation or on a clean day. Every run
  appends one ledger outcome line.
- Default schedule is 09:45 in the configured Asia/Shanghai timezone, after the
  morning changelog routines. The 24h window is a rolling span ending at observation
  time, so it covers only part of the previous calendar day. The overview bounds
  are fetched in separate calls after the ranking and each call resolves its own
  range, so the generated description labels them as separately fetched context
  for the range labels, keeps the ranking's own observation time as uncertain
  rather than claiming exact bounds for the route metrics, and records the
  collection-start limitation when it applies.
  The routine session runs at the default tier; only its `dev` dispatch is pinned
  tier1.

## Testing Decisions

- Test the external event and query contracts rather than middleware internals.
  A fixed request matrix covers successful, 4xx, 5xx, unmatched, excluded,
  module-dispatched, exception, streaming, disconnected, and cancelled requests.
- Use controlled monotonic time to assert start/duration semantics, including
  multiple streaming body frames and a final frame. Durations must never be
  negative.
- Assert route normalization with adversarial raw paths, resource IDs, encoded
  segments, query secrets, headers, cookies, and unknown module paths. Stored
  events and aggregate keys must contain none of the submitted sensitive values.
- Assert the dimension allowlist and per-field cardinality bounds. Unknown values
  must normalize or drop, never pass through.
- Assert one event per inbound attempt and verify that two retries produce two
  events rather than one inferred operation.
- Build deterministic distributions with known percentiles, aggregate them across
  hourly and daily buckets, and prove that selected-range p50/p95/p99 come from the
  merged population rather than an average of bucket percentiles.
- Reconcile aggregate counts, error counts, completion counts, and latency
  distributions to raw events before raw expiry. Re-running rollup must produce
  byte- or value-equivalent buckets.
- Exercise the 14-day, 90-day, and one-year cutoffs on both sides of each boundary,
  including partial current buckets and late events inside the overlap window.
- Contract-test every supported range, source seam, empty range, partial bucket,
  unsupported range, and configured-timezone label. A seam query must neither omit
  nor count a bucket twice.
- API tests assert maintainer ownership, enumerated filters, maximum 100 raw rows,
  server-owned ordering, rejection of arbitrary searches, and no raw access beyond
  14 days.
- UI tests cover loading, empty, partial-data, collection-start, error, and stale
  maintenance states; range persistence; metric consistency across overview and
  drill-down; low-volume ranking treatment; bounded raw lists; and back navigation.
- Performance verification compares capture disabled/enabled over warmed fast,
  representative, module, and streaming requests. Report sample size, concurrency,
  environment, p50, p95, and write/capture failure rate rather than relying on one
  manual timing.
- A post-deployment baseline check sends known fast, delayed, error, and streaming
  requests, reconciles them through raw and aggregate views, confirms cleanup is
  scheduled, and records the collection start. Browser-driven visual verification
  remains opt-in unless explicitly requested.
- The review routine is verified in dry-run shape: every prescribed command runs
  once by hand and exits cleanly with no todo, dispatch, Telegram, or ledger
  write; the open-todo dump passes a completeness check; dedup finds every
  endpoint named by an open todo; the day and open caps count zero markers; and
  the read-only Monitor CLI has unit coverage with a mocked API client plus a
  module-boundary test that keeps the CLI half out of the API half.
- The routine's failure paths are verified against mocks rather than live runs,
  because most of them cannot be produced safely on purpose: a failing list, a
  failing or unparsable todo record, an empty status, a status at the row cap, a
  day count spanning completed and deleted records, one record carrying the marker
  twice, sub-route and near-miss route identities, an exclusion line that must not
  confer ownership, a terminated versus unterminated ledger run, repeated skips
  reaching the stuck-guard threshold, and every failed or unconfirmed create and
  dispatch receipt. The shell cases must run the command blocks extracted from the
  skill file itself, not a separately maintained helper that may be stricter than
  the shipped prose, and must include a successful command returning a malformed
  list and a successful malformed day-record read, both of which have to end the
  run as uncertain. The grouping and truncation rules are regression-tested against
  a reference model, including one, two, and three tail-dominated routes, the
  switched-off shared-tail case, and trimming before grouping.

## Out of Scope

- Automatic optimization *inside the routine session*, root-cause diagnosis, anomaly
  detection, regression alerts, or SLO enforcement. This does not cancel the `dev`
  execution phase: the generated todo still authorizes local optimization and local
  verification before awaiting. The daily review routine only qualifies routes
  against fixed thresholds and creates bounded todos; it never changes code,
  publishes, deploys, or claims a cause.
- Concurrency-safe caps for the review routine. The overlap guard is advisory
  and a guard function stays a tentative suggestion, not an atomic reservation
  and not planned work; a real lock is out of scope for the first version.
- Trace monitoring, trace waterfalls, session-tree health, logs, infrastructure
  metrics, database query profiling, worker latency, queue latency, VM metrics, and
  third-party dependency tracing. These may become separately specified areas of
  `monitor` later.
- Distributed tracing, span ingestion, OpenTelemetry rollout, correlation across
  API, worker, and agent processes, or storage of trace/chat/todo identifiers.
- Request or response payload capture, headers, cookies, query data, raw paths,
  error messages/stacks, IP addresses, user agents, personal identifiers, or a
  general request inspector.
- Per-user, per-chat, per-trace, per-todo, per-resource, per-IP, or per-client
  latency attribution.
- Arbitrary labels, arbitrary group-by, custom query language, ad hoc SQL, raw
  event export, full-text search, or more than 100 raw rows in one response.
- Client-side browser performance, Core Web Vitals, frontend render timing, network
  timing outside the server boundary, or synthetic uptime monitoring.
- Persisting or backfilling historical latency from ordinary logs. The baseline
  begins when verified collection starts.
- A separate metrics database, hosted observability vendor, log scraper, or
  parallel observability stack unless future measured scale proves PostgreSQL and
  existing maintenance conventions insufficient.
- Monitoring-module domains beyond API latency in the first delivery. The broad
  `monitor` identity reserves a coherent home, not speculative implementation.
- Public or cross-user monitoring access. The first version is an owner-scoped
  operational tool.
- Changing application behavior, retry policy, timeout policy, endpoint semantics,
  or response contracts based on collected latency.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3792 | Monitor routes/overview P95 under 1s: host aggregates raw latency in SQL (exact percentiles, global sort kept) and excludes terminal-send freeze from events; Monitor module runs sync capabilities in managed worker threads so DB work no longer blocks the event loop. Evidence: `pages/impl-3792-monitor-latency.md`, `pages/impl-3792-monitor-module.md` | - | `pages/plan-3792-monitor-latency.md` | - | `pages/review-3792-monitor-host.md`, `pages/review-3792-monitor-module.md` (approve) | Shipped: host `52faace`, Deploy run 36672939500 success; Monitor v14 active from canonical `673c4bc`. A7 synthetic (prod, n=30/cohort, 0 errors) client P95: routes 24h 201, overview 24h 190, routes 7d 330, overview 7d 302 ms. A7 server-side, fully post-fix 1h window at 2026-09-30 06:36Z: routes n=14 P95 211 ms, overview n=14 P95 122 ms (below the n>=20 natural floor). Baseline 24h P95 ~8.7s. Natural traffic, fully post-fix 6h window at 2026-10-01 03:47Z: routes n=44 P95 277 ms, overview n=42 P95 232 ms, 0 errors (meets n>=20 floor). 24h window still mixes ~1.6h pre-fix samples until 2026-10-01 05:25Z. Rollback target Monitor v13, authorization required. |
| 3781 | Fix global route sorting: selected field/direction reaches the host and applies before limit; UI requests 100 rows, default P95 behavior retained. Evidence: `pages/impl-3781-monitor-routes-sort.md`. Supersedes initial explain-only diagnosis after Roy clarified Count sorting. | - | `pages/plan-3781-monitor-routes-truncation.md` | - | `pages/review-3781-monitor-routes-sort.md` (approve, round 3) | Shipped: host `238c900`, Deploy run 36666078399 success; Monitor v13 active from canonical `39f967d` (reviewed `dbc5844`), UI `b8ada29a962c`, API `821efe514c78`. Published-build difference independently verified as path comments plus three unused scoped CSS utilities, no changed existing rules. Required checks pass; existing TypeScript and stale boundary-test failures unchanged. No browser acceptance run: Roy to refresh Monitor, select 7d and Count descending, and confirm `/api/todo/list` appears near the top. Previous Monitor v12 is the rollback target, authorization required. |
| 3669 | Retain finance price-series compact 3m payload and early date filtering with an Eastern/UTC boundary guard; income-statement unchanged. Evidence: `pages/delivery-3669-finance-route-latency.md` | - | `pages/plan-3669-finance-route-latency.md` | `pages/delivery-3669-finance-route-latency.md` | `pages/review-3669-finance-route-latency.md` (approve, round 3, local-only) | Published Finance v49 from canonical `cfc2f66` (reviewed candidate `9375a79` mapped unchanged onto `a583f3d`), with explicitly approved SDK/UI rebuild and host floor 15; no repository push or host deploy. Release record: `pages/release-3669-finance.md`. Local candidate was based on `e412b075` in retained worktree `finance-latency-3669`; 61 tests pass and all seven range envelopes match excluding fetched_at. Two counterbalanced repeats, n=30 per arm/cohort/repeat; supported local warm-path P95 improvements only for 3m (-132.90/-32.85 ms) and 1y (-84.76/-47.99 ms). Other win claims withheld; all-range filtering adds a small cost, and two unchanged income controls trip the pooled regression gate. Bare-router middleware replay excludes host ModuleDispatcher and WAN cost; historical-sized income fixture does not establish current production behavior. Publication verified active and enabled; production P95 not verified. Sub-second objective remains unclaimed, pending Roy's qualified post-v49 Monitor check for each route (7d n>=100 or 24h n>=20). |
| 3626 | Remove unused full message bodies from authenticated `/api/trace/chats`, retaining segments and the public share projection; evidence in `pages/evidence-3626-trace-payload.md` | - | `pages/plan-3626-trace-payload.md` | `pages/evidence-3626-trace-payload.md` | `pages/review-3626-trace-payload.md` (approve, round 2) | Published isolated two-file candidate `8cf7b3a` to main/production on 2026-09-21 from baseline `3a2171c`; Deploy run `35556703589` and Deploy Web run `35556703622` succeeded. Canonical unpublished backlog preserved. Response sizes 161687 -> 7231 B and 4665047 -> 48991 B; n=30 per cell, primary warm P95 31.01 -> 17.94 / 24.78 -> 17.59 ms, contemporaneous supplementary large P95 124.57 -> 45.33 / 123.59 -> 52.53 ms. Complete matrix and 48 percentiles independently verified; 8 equivalence tests and build pass. Pre-existing TypeScript ref error persists in both arms. Successful-share equivalence is mocked handler coverage, not live HTTP 200. No post-deploy smoke run; production P95 not verified. Release record: `pages/release-3626-trace-payload.md`. |
| 3561 | Reject import-time DB warm-up after paired local replay of all seven routes; evidence in `pages/delivery-3561-shared-tail-experiment.md` | - | `pages/plan-3561-shared-cold-path-tail.md` | `pages/delivery-3561-shared-tail-experiment.md` (no-go) | `pages/review-3561-shared-tail-no-go-evidence.md` (approve rejection/report, not performance acceptance) | Local experiment concluded, no application delta retained. N=30 per route/arm/cold-or-warm cohort; startup-to-response proxy P95 increased 0.6% to 26.4% in sequential, confounded arms despite lower Monitor timings. No commit, integration or publication; production P95 not verified and the objective remains unachieved. |
| 3542 | Skip OpenRouter catalog fetching for bot list/config when no returned configuration needs it; local evidence in `pages/impl-3542-bot-list-latency.md` | - | `pages/plan-3542-bot-list-latency.md` | - | `pages/review-3542-bot-list-catalog-guard.md` (approve, round 3, local-only) | Locally verified, uncommitted API-only candidate on baseline `c9d9daf`; API blob `f41b2db`, API zip `59318933` (baseline `ff108e3b`). Local C1/C2-before/C3 P95 139.130/5.496/3.284 ms, N=30 each; 48 tests pass. No integration or publication; production P95 not verified. Worktree UI is pre-v38 and must not ship; future publication requires a fresh authorized baseline preserving then-active UI. |
| 3211 | Establish the `monitor` module with privacy-safe API latency capture, bounded raw/hourly/daily retention, percentile and error aggregation, recent overview, and route-level drill-down | - | `pages/plan-3211-api-latency-monitoring.md` | `pages/decision-3211-retained-window-rollup.md` | `pages/review-3211-api-latency-monitoring-host.md` (approve, round 8), `pages/review-3211-monitor-module.md` (approve) | Shipped: host capture/rollup/capability deployed (y-agent `b2d5c5d`, durable `collection_start` marker `a82e658`); migration `3211_api_latency.sql` applied; E4 production baseline PASS (`pages/verification-3211-api-latency-baseline.md`); `monitor` module published as v1 from y-module `951f577` |
| 3224 | Exclude the SSE chat stream `/api/chat/messages` from API latency capture and delete its raw/rollup history so global percentiles reflect request latency | - | `pages/plan-3224-exclude-sse-latency.md` | - | `pages/review-3224-exclude-sse-latency.md` (approve) | implemented; deploy and production cleanup pending |
| 3226 | Push route/method/status/completion/module-slug predicates into raw and rollup repository queries for monitor route detail (and shared summary/routes seams), keep payloads and percentile semantics identical, and avoid instrumentation recursion | - | `pages/plan-3226-slowest-api-routes.md` | - | `pages/review-3226-monitor-detail-filter-pushdown.md` | shipped in ba411ad, deployed 2026-08-19; production latency verification (plan sub-task 7) outstanding |
| 3227 | Make the Monitor center view self-sufficient: render the overview (summary metrics, percentile trend, route ranking) at wide-column size with no route selected, and drill into a route in place | `pages/design-3227.html` | - | - | `pages/review-3227-monitor-center-overview.md` (approve, round 2) | Shipped: `monitor` module published as v4 from y-module `e5fb9c0` (ui `73f8a680d7d7…`, api `af646a43a3bb…`); UI-only, no host or migration change |
| 3518 | Sort the Monitor slowest-routes table by any applicable column header, with ascending/descending toggling, an active-sort indicator, and numeric comparison on raw values | - | - | - | `pages/review-3518-monitor-route-sort.md` (approve, round 1) | Shipped: `monitor` module published as v6 from y-module `6418b25` (ui `3576f4599b94…`, api `af646a43a3bb…`); UI-only, no host or migration change |
| 3521 | Stack the Monitor wide overview vertically so the percentile trend chart sits above the slowest-routes table and the table gets the full column width, superseding the two-column "trend and ranking share the frame at roughly 54/46" rule in `pages/design-3227.html` | - | - | - | `pages/review-3521-monitor-wide-overview-stack.md` (approve, round 1) | Shipped: `monitor` module published as v7 from y-module `3bdd240` (ui `01d4b112da0b…`, api `af646a43a3bb…`); UI-only, no host or migration change |
| 3520 | Reduce P50 below 1000 ms for eight slow API endpoints: batch income-statement FX and reuse the narrow posting projection, fetch the holdings realtime overlay once per request, batch live balance-sheet liability FX, collapse `file/list` into one VM call, return note inventories as `JSONResponse`, and share usage-sync target/basis resolution across one bounded concurrent batch | - | `pages/plan-3520-endpoint-latency.md` | `pages/decision-3520-link-content-meta-no-consolidation.md` | `pages/review-3520-file-list-single-vm-call.md` (approve, round 2), `pages/review-3520-note-browse-serialization.md` (approve), `pages/review-3520-usage-sync-shared-basis.md` (approve, round 2), `pages/review-3520-finance-endpoint-latency.md` (approve, round 2) | Partial: published y-module `6e64cfa` as note v12 / file v39 / finance v42 and deployed y-agent `6fd82d9` (Actions run 34731153553); six GET endpoints pass their controlled production cohorts (`pages/verification-3520-production-acceptance.md`, note pages passes narrowly at 983.69 ms, holdings provisional at 19/20 events); `link/content-meta` ships no code by measured decision; `usage/sync` and `link/content-meta` remain above target and pending authorized POST replay; no disjoint natural-traffic window established |
| 3524 | Add a bounded daily API latency review routine: read-only `y monitor` CLI half in the `monitor` module, the `api-latency-review` skill (P95 < 1000 ms objective, 7d n>=100 / 24h n>=20 raw floors, `max_new_per_day=1`, `max_open=2`, full open-todo dedup, pending-only dispatch recovery, awaiting-only handoff), and a disabled registration package | - | `pages/plan-3524-daily-latency-routine.md` | `pages/decision-3524-staged-integration.md` | `pages/review-3524-monitor-cli.md` (approve, CLI only), `pages/review-3524-latency-review-routine.md` (approve, round 4) | Staged delivery: CLI locally integrated as `6e2f4f5`, canonical meta smoke passed; skill v0.3.1 locally committed as `894fa9f`; routine `6d76f8` registered disabled at 09:45 Asia/Shanghai. Initial dry-run `d2b2cb` required one continuation prompt; additional skill execution `18b96f` completed unattended in 6m28s with `ok:created dry_run=true`, proposing finance holdings/balance-sheet without optimization writes. Evidence: `pages/delivery-3524-latency-review-skill.md`, `pages/decision-3524-staged-integration.md`. Scheduler fire path was not retested; route matching was re-derived inline rather than using the shipped block. Routine `6d76f8` enabled by explicit user authorization on 2026-09-14 08:15 Asia/Shanghai with unchanged `dry_run=false` configuration, verified by readback; no immediate manual fire. No push or module publication; first scheduled execution and real creation/dispatch remain unverified |
| 3579 | Hydrate `/api/module/tag/` lookup members from column projections (todo/note/entity) instead of full DTOs, and memoize the module bundle S3 client; local evidence in `pages/delivery-3579-tag-lookup-latency.md` | - | `pages/plan-3579-tag-lookup-latency.md` | - | `pages/review-3579-tag-lookup-latency.md` (approve, round 1, local-only) | Shipped: y-agent `bde0e0c` (commits `ce66231` projection + `bde0e0c` S3 memo, rebased onto `9abd02e`) pushed to main, Deploy run 35174682562 succeeded 2026-09-17. Replay n=36 per arm (six tags, user 85, warm pool, service-call boundary): pooled P95 54.9 -> 25.2 ms (impl), 54.2 -> 20.2 ms (independent review), identical payload fingerprints, 3 SQL statements. Production P95 not verified (Roy's follow-up in Monitor); 7d window judged not route-reachable (shared cold band, todo 3561) |
| 3591 | Overlap the two independent `/api/module/note/list` inventory sources by acquiring the VM root scan and the DB note read concurrently via `asyncio.gather(return_exceptions=True)`, offloading the synchronous read with `asyncio.to_thread`; local evidence in `pages/verification-3591.md` | - | `pages/plan-3591.md` | - | `pages/review-3591-note-source-concurrency.md` (approve, round 3, local-only) | Locally verified, unpublished module candidate `0637932` on clean baseline `e412b07` (worktree `note-perf-3591`, browse sha256 `5ffeaca5…`); module-only, no host, UI, schema or contract change. Local replay at the `ApiLatencyMiddleware` boundary against a synthetic fixture (4000 registered rows / 2000 file-only, local-subprocess VM path, no SSH or wake): default-inventory cohorts improve repeatably across four runs, e.g. A n=200 P95 619.30 -> 559.70 and 504.53 -> 457.45 ms, B n=40 507.04 -> 397.28 ms, D n=40 391.61 -> 352.80 ms; tag cohort C and tail maxima are inconclusive (C regressed 141.20 -> 174.55 ms in one n=40 run) and the todo-scoped cohort E is unchanged. 78 tests pass; 57 differential cases byte-identical through the real dispatcher. Cancellation drains the owned read through repeated parent cancellation with no request-level deadline, so a stuck read can delay cancellation indefinitely (accepted: matches the serial baseline and avoids introducing DB timeout policy here). Remaining local bottleneck is the VM scan call, whose production SSH/wake cost the fixture excludes; wake-branch counts are counts, not latencies, and select no host candidate. No integration, publication or deployment; production P95 not verified and remains Roy's qualified Monitor-window follow-up (7d n>=100 or 24h n>=20) against the 1878.4/1826.5 ms qualifying observation |
| 3781 | Rank Monitor routes server-side by the user-selected column before the row limit (`sort_by` / `sort_dir`, default p95 desc), so a route such as `/api/todo/list` is not hidden by P95 truncation; backend contract v19 to v20, Monitor `min_backend_version` 20 | - | `pages/plan-3781-monitor-routes-truncation.md` | - | - | Locally implemented and verified, uncommitted on isolated `origin/main` worktrees; evidence in `pages/impl-3781-monitor-routes-sort.md`. Not published; release order is host v20 first, then Monitor. |
| 3616 | Single-flight the stale VM wake prelude per VM per process (y-agent `ec2_wake.py`, revised C1) and add `ETag` / `Last-Modified` / `Cache-Control: private, max-age=60` with `If-None-Match` 304 to `/api/module/file/raw` (y-module S5); C2 SSH client reuse dropped for correctness; local evidence in `pages/delivery-3616-file-latency.md` | - | `pages/plan-3616-file-module-latency.md` | `pages/delivery-3616-file-latency.md` | `pages/review-3616-file-raw-cache.md` (approve S5, round 1), `pages/review-3616-wake-prelude-and-ssh-reuse.md` (approve C1 + note, round 3, local-only) | Shipped C1 only: y-agent `3a2171c` (reviewed `ec963f4` rebuilt onto origin/main `dac0711`) pushed to main, Deploy run 35428923687 succeeded 2026-09-19. S5 held unpublished: y-module `166a95c` on `fbab320` (worktree `file-mod-3616`), pending a cheaper ETag decision. Loopback SSH replay at the `ApiLatencyMiddleware` boundary, alternated arms, n=30/30/36: cohort C burst describes 12 -> 1 and readiness probes 12 -> 1 per burst, but burst p95 688.6 -> 762.0 ms and warm `/raw` p95 171.7 -> 223.3 ms because every non-304 `/raw` now pays a measured S5 miss cost (+21..+35 ms block medians, scaling with payload). Plan D2: P95 < 1000 ms is not reachable in production for any member route while the shared ~1.4 s cold band (todo 3561) stands. No integration, publication or deploy; production P95 not verified and remains Roy's Monitor follow-up (7d n>=100 or 24h n>=20) |
| 3624 | Bounded local baseline replay of the five shared-tail routes (`/api/trace/chats`, `/api/chat/bot-options`, `/api/user-preference`, `/api/vm-config/list`, `/api/module/bot/list`) isolated no supported in-boundary candidate; no application change retained. Evidence in `pages/evidence-3624-baseline-and-s2-decision.md` | - | `pages/plan-3624-shared-route-tail.md` | `pages/evidence-3624-baseline-and-s2-decision.md` (no-go) | `pages/review-3624-shared-tail-no-go.md` (approve, round 2, evidence-only no-go, not performance acceptance) | Local experiment concluded on clean baseline `3a2171c` (worktree `latency-tail-3624`); `git diff HEAD` empty, S3/S4 not applicable without a candidate. Isolated loopback fixture, 15 cohorts x n=30 = 450 events, zero failures, percentiles recomputed independently and all 16 harness-file hashes matched provenance. Cold minus warm p50 is 115.1/116.1/115.7 ms on the three simple routes, dominated by boundary-qualified once-per-process first use (`init_db` ~67 ms incl. lazy `psycopg` import, ORM registry ~35 ms); reconnect cohort isolates loopback connection setup at ~4.5 ms. Removing that span from the measured window requires import relocation, already measured and reverted under todo 3561. Warm P95 on the simple routes is 2.49-2.95 ms, below the plan's >=10 ms retention gate, so a pure-ASGI `AuthMiddleware` rewrite was rejected on the gate. Todo 3616's wake prelude is measured unreachable from all five routes (tripwires, zero calls, incl. the `vm_config`-empty fallback). Module cold excess on `/api/module/bot/list` remains explicitly unattributed, not dismissed as module-owned. Reported not queued: trace full-message-body payload, `y-module/bot/pricing.py` in-request third-party GET with no timeout or negative caching, unlocked `init_db`. Local absolute values are not a production prediction and no production cause is claimed; no commit, integration, publication or deploy; production P95 not verified and remains Roy's qualified Monitor-window follow-up (7d n>=100 or 24h n>=20) |
| 3627 | Stop `/api/module/file/history` from waking a hibernated VM (host backend v18 `run_vm_command(wake=False)` with a stale-gated read-only EC2 sleep probe and `ModuleVmAsleepError`; File maps it to `{"url": null}`), and replace the 15 s `InstanceRunning` waiter and 5 s SSH readiness interval with 1 s polling under the existing 600 s / 180 s budgets, tolerating transient `ClientError`; local evidence in `pages/delivery-3627-file-cold-wake.md` | - | `pages/plan-3627-file-read-history-cold-wake.md` | `pages/delivery-3627-file-cold-wake.md` | `pages/review-3627-file-cold-wake.md` (approve, round 2, local-only) | Published 2026-09-22: y-agent candidate `03798e9` rebased same-content to `f63ed15` on origin/main `8cf7b3a` and pushed to main/production, Deploy run `35676361381` success (backend-only, no Deploy Web); then y-module `869be4d` fast-forwarded onto canonical main `5ba3d30` and File published as v42 (api `a4e42ef7ceda`, ui unchanged `f7477b591091`, floor v18). Canonical y-agent unpublished backlog preserved; y-module git not pushed. Root cause: after todo 3564 the VM hibernates on 15 min SSH idle, so 13 of 20 file opens in the 24h window paid a 13-55 s EC2 cold wake on the request path; warm path unchanged. Loopback replay with a stateful fake EC2 (describe 120 ms, pending 12 s, sshd ready 18 s), n=30 pairs per cohort: cold `/history` P95 20699.9 -> 134.8 ms with 1 start per pair, cold `/read` 20663.4 -> 18824.0 ms (still blocking on a real boot), warm `/history` 251.1 -> 217.4 ms with 0 describes; cold describes per pair 3 -> 14 (rate-limit exposure named). Plan F4: with every cold sample removed the 24h P95 is still ~2.0/2.2 s, so P95 < 1000 ms is not reachable while the shared ~1.4 s band (3561/3624 no-go) stands. Evidence at `/Users/roy/luohy15/assets/file-perf-3627/`. Release order if authorized: host v18 deploy before File publish (preflight floor rejects the reverse). Production P95 not verified and remains Roy's Monitor follow-up (7d n>=100 or 24h n>=20) |
| 3628 | Audited the shared 3-route P95 tail (`/api/chat/detail`, `/api/user-preference`, `/api/vm-config/list`); rejected another speculative shared-tail patch and retained one route-specific candidate: a metadata-only read used solely by `GET /api/chat/detail`, dropping the unread `search_text` column transfer and the full `Message` construction/sort. Evidence in `pages/delivery-3628-chat-detail-metadata-read.md` | - | `pages/plan-3628-three-route-tail-audit.md` | `pages/delivery-3628-chat-detail-metadata-read.md` (S2 go) | `pages/review-3628-chat-detail-metadata-read.md` (approve for local retention, round 2, local-only) | Local-only candidate `e546a93` on clean baseline `8cf7b3a` (worktree `latency-tail-3628`), 5 files +157/-3; `get_chat`, `_entity_to_chat`, `Chat.from_dict`, `get_chat_meta(s)` and all full-message callers unchanged. Plan rejected re-running todo 3624's five-route matrix: two of the three member routes carry 3624's reviewed negative result and their request paths are unchanged at this baseline. Discriminator measured at the `ApiLatencyMiddleware` boundary against a synthetic loopback fixture (240 measurements, 0 errors): warm `chat-detail-large` 25.4 ms vs `vm-config-list` 1.8 ms for a byte-identical 332-byte response; avoidable spans ~6.2 ms `search_text` transfer + ~11.7 ms message hydration/sort. Authoritative paired runs 3-4 (runs 1-2 superseded after the F1 fix), n=30 per shape/cohort/arm: large-detail cold P95 -16.57 ms/-11.3% and -14.91 ms/-10.1%, warm -14.78 ms/-10.4% and -14.98 ms/-10.6%; no control regression above `max(10%, 5 ms)`; worst startup-proxy regression 2.95%. Review round 1 blocked on F1, a reproduced 404 -> 200 regression where the new validator omitted `int(dt.timestamp() * 1000)`; fixed, and round 2 re-verified 33 equivalence fixtures with zero mismatches plus 256 recomputed percentile/delta values. 1311-test suite failing set matches baseline (84 pre-existing), not a clean suite. Limits: synthetic n=30 micro-cohorts, loopback DB, no Lambda freeze/thaw, no measured production payload distribution; the win scales with transcript size and is worth ~0.9-2.2 ms on a 100-message chat; warm P95 reflects a short-lived-process mixture, not steady state. Nothing here identifies the cause of the ~1400 ms production band, which remains correlation only. Detail-only, so **todo 3628's three-route objective is not met**: `/api/user-preference` and `/api/vm-config/list` are unchanged. No integration, publication or deploy; production P95 not verified and remains Roy's qualified Monitor follow-up (7d n>=100 or 24h n>=20) for **each** member route after any separately authorized publication. |
| 3684 | Audited the shared four-route P95 tail (`/api/chat/bot-options`, `/api/user-preference`, `/api/calendar/list`, `/api/vm-config/list`) and concluded an evidence-only duplicate/no-go: this audit identified no supported in-boundary candidate, and repeating todo 3624's replay is not justified given verified per-file continuity on the overlapping member paths. Evidence in `pages/plan-3684-shared-four-route-tail.md` | - | `pages/plan-3684-shared-four-route-tail.md` | `pages/plan-3684-shared-four-route-tail.md` (no-go) | `pages/review-3684-shared-four-route-tail.md` (approve, round 2, evidence-only no-go, not performance acceptance) | Audit only; no worktree, no candidate, no local replay, no application delta, no commit, integration, publication or deploy. Fourth overlapping selection of the same band in ten days: 3561 (7 routes) covered all four members, 3624 (5) covered three, 3628 (3) covered two; `/api/calendar/list` was individually audited here for the first time (`api/controller/calendar_event.py`, `storage/service/calendar_event.py`, `storage/repository/calendar_event.py`: one owner-scoped SELECT, optional tag subquery, filters/order/limit default 200, DTO conversion; no N+1, VM or third-party call) and yields no supported candidate by source inspection, which is not proof that none exists -- `limit` has no upper cap, rows carry a Text description, and scan/sort, payload volume, contention and conditional first-use latency are unmeasured. Read-only `y monitor` observations (raw, `approximate_percentiles=false`): 7d global P95 1358.86 ms at n=44074/44277 (P50 66.2 ms); member P95 1471.5/1421.0/1403.9/1400.8 ms at n=175/3255-3307/1306-1316/1488-1498, requiring a 400.8-471.5 ms decrease to reach 1000 ms; relative P99 gaps 2.7/4.5/8.9/5.7%; seven qualified host rows span [1383.9, 1471.5] ms P95 (6.33% range) with a 2.16x median spread (40.35/18.64 ms). Occupancy is an all-route, uncontrolled median-of-hourly-medians association reproducing todo 3561's sparse-hour pattern (bins 1-5/6-20/21-50/51-200/201-1000/>1000 requests per hour give 1488.4/1271.4/853.2/77.5/67.3/64.2 ms; sparse share 1.858%); it does not establish request isolation, environment identity or a cold fraction, and Monitor carries no process/cold-start dimension. **Review round 1 blocked on four findings and they are load-bearing corrections, not polish:** P50 is not an upper bound on route-specific tail cost (a component is bounded by total duration on the same request, not by the median of other requests, and reducing slow-mode frequency can move P95), correlation was promoted into shared-additive-cost attribution with exclusive-remedy wording, the occupancy bins were read causally, and the claimed 50x median spread came solely from below-floor `/api/chat/attach-image` (n=32, `meets_min_samples=false`). Round 2 withdrew the median-derived handler and calendar ceilings, the impossibility framing, the 50x spread, the shared-cost attribution and the unmatched-only assertion; cheaper first-use work stays open rather than disproven. Reported not queued (non-exhaustive, unverified options, none authorized here): one bounded process-age or per-process-ordinal dimension on `api_latency_event` so the cold fraction can be measured instead of inferred; a one-off production split of first `init_db` / first connect into CPU versus connection cost; Lambda memory 512 (~0.29 vCPU), SnapStart or provisioned concurrency; reducing SPA boot fan-out to test whether cold-environment creation falls; the unlocked `init_db` check-then-act race (correctness, carried from 3561/3624); `/api/chat/attach-image` P50 924.4 ms at n=32, never audited. Also reported: the `api-latency-review` routine dedups against open todos, not against reviewed negative evidence, so this band regenerates whenever its members clear the sample floors. **Todo 3684's local before/after acceptance is not met** (no candidate, no replay) and the objective is explicitly unmet, not performance acceptance. Production P95 not verified and remains Roy's qualified Monitor follow-up (7d n>=100 or 24h n>=20) for each member route after any separately authorized future change. |
| 3650 | Audited `/api/module/file/read` and `/api/module/file/history` after the todo 3627 cold-wake release and concluded an evidence-only no-go: no new regression and no new supported in-boundary candidate were established, and todo 3627's already-published fix must not be recreated. Evidence in `pages/plan-3650-file-p95-regression-audit.md` | - | `pages/plan-3650-file-p95-regression-audit.md` | `pages/plan-3650-file-p95-regression-audit.md` (no-go) | `pages/review-3650-file-p95-regression-audit.md` (approve, round 1, evidence-only no-go, not performance acceptance) | Audit only; no worktree, no candidate, no local replay, no application delta, no commit, integration, publication or deploy. Retained 24h Monitor rows at `/Users/roy/luohy15/assets/file-perf-3650/audit-monitor-24h.json`; review independently rederived read n=26 P50 692.65 P95 22349.11 and history n=29 P50 701.03 P95 1432.02 by `(n-1)*p` interpolation matching `_exact_percentile`, and confirmed all samples postdate File v42 (`2026-09-22T01:39:46.758Z`; earliest sample 30 min 43 s later). Read's tail is three requests (20654.45 / 22913.996 / 22975.61 ms); excluding them leaves n=23 P95 1464.02 ms, a descriptive sensitivity figure and not a measured warm cohort. History shows no multi-second wake tail, consistent with 3627's no-wake path; its three paired durations (883.08 / 1488.71 / 1593.75 ms) sit in the warm band rather than the ~135 ms no-wake-null signature, so they are a discriminator to measure rather than corroboration of cold wake (review nit). The 7d figures (read P95 27971.09 n=118; history P95 16457.03 n=249) include pre-v42 traffic and are qualification numbers only, not causal before/after arms. Residual cold VM wake remains the leading but unproven explanation: Monitor carries no VM identity, request parameters, EC2 state or component spans. Source audit confirms no missing 3627 implementation (`file/api.py` `/read` single bounded VM command, `/history` `wake=False`; pinned host `run_vm_command(wake=False)` stale-gates an off-loop probe and never falls back to waking; EC2/SSH poll at 1 s). Pooled SSH stays rejected on todo 3616's reproduced duplicate-execution-after-timeout and cross-request cancellation; the rejected shared warm-up and five-route experiment stay closed. **Binding baseline correction:** canonical y-agent working-tree HEAD `6faece4` does not contain host `f63ed15` (merge-base `39ca7a3`; HEAD still uses the `instance_running` waiter and lacks `wake=False`), so any future local host work must pin `origin/main` lineage `e15a292`, not canonical HEAD; y-module local main `2ca038d` is a valid File baseline (`git diff 869be4d HEAD -- file/api.py file/module.json` empty). **Todo 3650's local before/after acceptance is not met** (no candidate, no replay) and both routes fail the qualifying 24h gate, so this is an explicit unmet-objective outcome, not performance acceptance. Production P95 not verified and remains Roy's qualified Monitor follow-up (7d n>=100 or 24h n>=20) for each member route after any separately authorized future change. |
