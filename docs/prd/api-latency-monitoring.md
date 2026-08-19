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
   end when the response body finishes, so that the measurement reflects the
   server-side lifecycle rather than only handler execution.
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
- A normal response completes on its final body frame. Streaming duration therefore
  includes the lifetime of the stream. Disconnect, cancellation, and an exception
  escaping the application are distinct bounded completion classes.
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

### Query and UI contract

- The overview returns total count, one merge-derived latency distribution (or its
  p50/p95/p99 projection), error count/rate, a bounded time series, and bounded
  per-route rows for one supported range.
- Error rate is the fraction of completed attempts in the 5xx status class plus
  internal-failure completions over all attempts in the cohort. Disconnects and
  cancellations remain separate outcomes rather than silently counting as 5xx.
- Slowest routes rank by p95 among routes meeting a declared minimum sample count.
  Low-volume routes remain visible but cannot silently win the primary ranking
  from a single request.
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

## Out of Scope

- Automated performance recommendations, root-cause diagnosis, anomaly detection,
  regression alerts, SLO enforcement, or automatic optimization.
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
| 3211 | Establish the `monitor` module with privacy-safe API latency capture, bounded raw/hourly/daily retention, percentile and error aggregation, recent overview, and route-level drill-down | - | `pages/plan-3211-api-latency-monitoring.md` | `pages/decision-3211-retained-window-rollup.md` | `pages/review-3211-api-latency-monitoring-host.md` (approve, round 8), `pages/review-3211-monitor-module.md` (approve) | Shipped: host capture/rollup/capability deployed (y-agent `b2d5c5d`, durable `collection_start` marker `a82e658`); migration `3211_api_latency.sql` applied; E4 production baseline PASS (`pages/verification-3211-api-latency-baseline.md`); `monitor` module published as v1 from y-module `951f577` |
| 3224 | Exclude the SSE chat stream `/api/chat/messages` from API latency capture and delete its raw/rollup history so global percentiles reflect request latency | - | `pages/plan-3224-exclude-sse-latency.md` | - | `pages/review-3224-exclude-sse-latency.md` (approve) | implemented; deploy and production cleanup pending |
| 3226 | Push route/method/status/completion/module-slug predicates into raw and rollup repository queries for monitor route detail (and shared summary/routes seams), keep payloads and percentile semantics identical, and avoid instrumentation recursion | - | `pages/plan-3226-slowest-api-routes.md` | - | - | implementing |
