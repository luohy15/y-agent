# Bot Usage: Spend Analytics and Subscription Limit Windows

## Problem Statement

The user's LLM spend flows through a relay (claude-relay-service, "CRS") that
keeps usage counters only in Redis with short retention: daily buckets expire
after about 32 days, and nothing outside the relay's own dashboard can answer
"how many tokens / dollars / requests did each model consume, per day, over
time". Before this feature, y-agent had no persisted LLM-usage time series at
all; the only visibility was the relay's dashboard (per-key, ephemeral) and a
subscription rate-limit scrape that measures something else entirely. The user
wants usage queryable and chartable alongside the other y-agent subsystems:
which models dominate spend, how usage trends week over week, and whether a
given day was heavy or idle, without the numbers silently rolling off. Spend
history also does not answer the operational question that matters before
starting another long agent turn: how much of each paid subscription (Claude,
GPT (Codex), and Grok) is still available, and when it recovers. Those
provider-native limits need a current status surface of their own rather than
being inferred from token or dollar totals. They also should not depend on a
relay: routing limit status through claude-relay-service made the numbers a
function of a separate service staying deployed, configured, and in sync, and
it structurally could not answer for a provider the relay had no usage concept
for at all.

## Solution

y-agent persists a provider-generic per-model daily usage time series in its
own database and renders it on the bot page. A daily sync pulls today's
per-model token/cost/request totals from the relay across every relay API key
the user's bots use, sums them into one global per-model aggregate per day, and
upserts idempotently, so the in-progress day is refreshed in place and history
accumulates past the relay's retention window. A one-shot admin backfill can
recover the relay's remaining dated window when the pipeline starts. A thin
usage API exposes the raw daily rows filtered by the same time grammar the
finance views use (specific dates, months, quarters, ranges, ytd/mtd/all), plus
a per-day totals endpoint for the contribution heatmap. The bot page gains a
Usage view with two modes: Live (donut of model shares with totals in the
center, a per-model table, and a GitHub-style daily contribution heatmap) and
Over-time (stacked per-period chart plus a per-model-by-period table with
daily / weekly / monthly granularity), with a Tokens / Cost / Requests metric
toggle shared across both.

The Live mode of that bot-page Usage view also presents a current
subscription-limit status section for the Claude, GPT (Codex), and Grok
backends, read **directly from each provider** rather than through any relay.
Each provider reports whichever windows it actually defines (Claude and Codex
report rolling windows, `five_hour` / `one_week`; Grok reports its current
billing period), with percent used, percent remaining, reset time, freshness,
and explicit unavailable / stale / re-auth states. The three reads run in the
`y` CLI **on the user's VM** (stable source IP, already known to these
vendors), behind one `y usage limits --json` envelope; the API SSH-execs that
command and normalizes the result, so no provider request originates from
Lambda and no snapshot is persisted on the y-agent side. Refresh is independent from spend
sync because the two datasets have different sources, cadence, and failure
modes.

Credentials are not y-agent's to own. For OpenAI and xAI the **vendor CLI's own
credential file** (`~/.codex/auth.json`, `~/.grok/auth.json`) is the single
source of truth: y-agent reads it live and, when the access token has expired,
refreshes it at the provider's OAuth endpoint and writes the rotated grant back
into that same vendor file, in that file's exact original shape: precisely
what the vendor CLI would have done itself. There is no y-agent credential
store and no y-agent login command. Anthropic handles no token here at all: its
reader drives the `claude` CLI's own `/usage` view, and that CLI owns its grant
end to end. Re-authentication is therefore always a **vendor** action
(`claude login` / `codex login` / `grok login`), which is exactly what the
expired-login card tells the user to run.

## User Stories

### Sync and storage

1. As a user, I want each model's daily token counts (input, output, cache
   create, cache read, total), request count, and real USD cost persisted in
   y-agent's database, so that usage survives the relay's ~32-day Redis
   retention and stays queryable forever.
2. As a user, I want the sync to cover every relay API key my bots are
   configured with (subscription and pay-as-you-go alike), so that no model's
   usage is missed just because it flows through a secondary key.
3. As a user, I want keys shared by multiple bots queried exactly once and the
   per-key results summed per model into a single global aggregate row per day,
   so that the numbers are complete without double counting.
4. As a user, I want re-running the sync on the same day to overwrite that
   day's rows in place, so that repeated runs (scheduled, manual, or web) are
   idempotent and the in-progress day converges on the final total.
5. As a user, I want the sync to run automatically once a day shortly before
   the local day ends, so that each day's near-final snapshot is captured
   without me remembering to trigger it.
6. As a user, I want a manual CLI command to trigger the same sync on demand,
   so that I can refresh the data immediately after heavy usage.
7. As a web user, I want a refresh button on the usage view that triggers the
   sync and then revalidates the panel, so that I can see up-to-the-minute
   numbers without leaving the page.
8. As a user, I want usage dates stamped in my configured local timezone,
   matching the relay's own day boundaries, so that "today" in y-agent and
   "today" on the relay dashboard agree.
9. As a user, I want a sync that fails on any key to write nothing rather than
   a partial sum, so that a previously correct daily aggregate is never
   overwritten with a silent undercount.
10. As a user, I want new relay keys picked up automatically when a bot config
    starts using one, so that adding or repointing bots never requires touching
    the sync code.
11. As a user, I want usage from bots routed to third-party providers through
    the relay (OpenRouter models fronted by the relay) recorded by the same
    pipeline, so that one ingestion path covers all my spend instead of one
    integration per provider.

### Backfill

12. As a user starting the pipeline, I want a one-shot backfill command that
    pulls the relay's remaining dated per-day history (about 32 days), so that
    the views are not empty until history accrues naturally.
13. As a user, I want the backfill to stop at yesterday, so that the recurring
    sync keeps sole ownership of the in-progress day and there is no mid-day
    clobber.
14. As a user, I want the backfill to authenticate with relay admin credentials
    supplied at invocation time only, so that no admin secret is ever persisted
    in the deployed system or the database.
15. As a user, I want re-running the backfill to be a no-op-equivalent upsert,
    so that a flaky run can simply be retried.

### Subscription limit-window status

16. As a web user, I want the Live tab of the bot Usage view to show
    subscription-limit status for all three subscriptions I pay for
    (Claude, GPT (Codex), and Grok), so that I can choose a backend with enough
    available capacity before starting work without adding operational status
    to the historical Over-time tab.
17. As a user, I want each provider's numbers read straight from that provider,
    so that limit status does not depend on a relay service staying deployed,
    configured, and in sync, and so that a provider the relay has no usage
    concept for can still be shown.
18. As a web user, I want each provider to show whichever windows it actually
    defines (Claude: rolling 5-hour and 1-week; Codex: its rolling rate-limit
    windows; Grok: the current billing period) rather than every provider being
    forced into one window shape, so that no card shows a permanently empty row
    for a window its provider does not have.
19. As a web user, I want each window to show percent used, percent remaining,
    and the reset time, so that I can judge both current headroom and how long I
    need to wait for recovery.
20. As a web user, I want reset times rendered in my configured timezone with
    a concise relative-time companion, so that provider timestamps are
    immediately actionable without manual conversion.
21. As a web user, I want the status to show when it was observed and whether
    it is fresh or stale, so that an old successful probe is never mistaken for
    current capacity.
22. As a web user, I want a manual refresh control for limit-window status
    that is separate from the spend-data refresh and that actually performs a
    fresh read rather than replaying a cached result, so that retrying after a
    failure is meaningful and checking headroom never triggers an unrelated
    spend sync.
23. As a web user, I want one provider's failure to leave the other providers
    visible, with a clear unavailable state and the last successful snapshot
    retained as stale when available, so that partial source failure does not
    blank the whole status section.
24. As a user with several accounts for the same backend, I want exactly one
    deterministically selected limit-status card per backend, so that
    account-wide subscription limits are not presented as bot-specific quotas
    or duplicate backend cards.
25. As an API consumer, I want a provider-neutral latest-status response that
    identifies the backend, provider, account scope, the windows that provider
    reports, observation time, and availability state, so that future surfaces
    do not need to parse provider-native output.
26. As a user, I want provider-native extra windows, such as Claude's optional
    model-specific weekly limit, preserved as optional metadata without
    displacing the primary window display, so that useful detail is not lost
    while the cross-provider comparison stays consistent.
27. As a user, I want a status read to never spend model tokens, so that
    looking at my remaining allowance never consumes it.

### Provider credentials

28. As a user, I want y-agent to read each vendor CLI's own credential file
    instead of keeping its own copy of my logins, so that there is exactly one
    grant per provider and nothing for me to keep in sync.
29. As a user, I want an expired access token refreshed automatically and the
    rotated grant written back into that same vendor file, so that the panel
    keeps working between my own uses of the vendor CLI and the vendor CLI
    picks up the refresh on its next run.
30. As a user, I want my vendor credential file left byte-identical whenever a
    refresh fails, and never observed half-written by a vendor CLI running at
    the same moment, so that reading a status number can never cost me a login.
31. As a user, I want an expired or absent login surfaced as an actionable card
    naming the **vendor** command to re-run (`claude login`, `codex login`,
    `grok login`), so that I can fix it without knowing y-agent's internals.
32. As a user, I want a CLI command that reports each provider's credential
    state without ever printing token material, so that I can diagnose a dark
    card from a terminal safely.
33. As a user, I want Anthropic's monthly re-authentication to be the only
    lifecycle work I do for it, with y-agent implementing no Anthropic token
    handling at all, so that its 30-day session cap costs one login and nothing
    more.

### Read cost and availability

34. As a user, I want the provider calls made from my own VM rather than from
    Lambda, so that requests come from a stable source IP these vendors already
    know instead of shared cloud egress.
35. As a user, I want a stopped VM to answer the status poll immediately with
    an explicit unreachable state instead of being started, so that opening a
    panel never boots an instance.
36. As a user, I want the expensive Anthropic reading cached on the VM for a
    few minutes while the two cheap HTTP reads always run fresh, and the cached
    reading to keep its original observation time, so that a 60-second poll
    does not spawn a terminal session every minute and freshness never lies.

### Usage API

37. As an API consumer, I want per-model daily rows filtered by source and date
    range, so that any client (web, future CLI) can build its own views from
    the raw grain.
38. As an API consumer, I want to pass a single free-text time expression using
    the same grammar as the finance views (day, week, month, year, 2024-05,
    2024-q2, a specific date, "day-7 to day", ytd/mtd/all), so that one
    authoritative parser serves both subsystems and the usage view is not stuck
    with a weaker dialect.
39. As an API consumer, I want the default query (no range given) to return
    today's snapshot, so that the common "what is happening now" case needs no
    parameters.
40. As an API consumer, I want a per-day totals endpoint (tokens, cost,
    requests summed across models) over a rolling 12-month or single-calendar-
    year window, so that the contribution heatmap renders its full window
    independently of the Live time filter.
41. As an API consumer, I want responses to carry only public fields (no
    internal integer ids), so that the ID convention holds on this surface like
    every other.

### Live view

42. As a web user, I want a donut chart of each model's share of the selected
    metric over the selected time range, top seven models plus an "Other"
    slice, sorted by share descending, so that I can see at a glance which
    models dominate.
43. As a web user, I want the range totals for tokens, cost, and requests
    displayed inside the donut's center hole, so that headline numbers and the
    breakdown share one compact card.
44. As a web user, I want a clean donut with a bottom dot-legend (no on-slice
    labels) and hover tooltips showing model, value, and percent share, with
    the tooltip rendering above the center overlay, so that the chart reads
    like the relay dashboard's distribution chart the user prefers.
45. As a web user, I want a per-model table with a percent column computed
    against whichever numeric column is the active sort column, so that
    "share of tokens" and "share of cost" are one click apart.
46. As a web user, I want the table columns ordered metric-first (Tokens, Cost,
    Requests, then Input, Output, Cache), clickable-sortable, with a sticky
    header and a sticky bottom Total row, and about five rows visible before
    internal scrolling, so that the table stays compact inside the panel.
47. As a web user on a narrow panel, I want less-important table columns
    (input/output, then cache) to hide progressively based on the panel's own
    width, so that the layout adapts to the resizable panel rather than the
    viewport.
48. As a web user, I want a GitHub-style daily contribution heatmap (one cell
    per day, weeks as columns left to right, Monday at top, a five-bucket
    sequential color scale on absolute per-metric thresholds, month labels,
    weekday gutter, hover tooltip with date and exact value, and a legend of
    numeric swatches rather than a Less-to-More row), so that heavy and idle
    days are visible over a year at a glance.
49. As a web user, I want the heatmap driven by the same selected metric as the
    donut and table, so that switching Tokens / Cost / Requests re-colors
    everything consistently.
50. As a web user, I want the heatmap window decoupled from the Live time
    filter: a rolling month-aligned past 12 months by default, or a whole
    calendar year when the time input is a bare four-digit year, so that
    narrowing the donut to "today" never blanks the heatmap.
51. As a web user, I want the heatmap to scale to the panel width (down to fit,
    up to a cap on wide panels) without horizontal scrolling, so that the full
    12-month grid is always visible.

### Over-time view

52. As a web user, I want a Live | Over-time mode toggle on the usage view
    styled after the finance viewer's mode toggle, so that the two analytics
    panels feel like one system.
53. As a web user, I want an over-time stacked chart of the selected metric per
    period, top seven models plus "Other", with daily / weekly / monthly
    granularity bucketed client-side, so that trends are visible at the grain I
    choose (the finance views stop at weekly; usage goes down to daily).
54. As a web user, I want one metric charted at a time via a Tokens | Cost |
    Requests toggle, so that the axis and stacking stay meaningful.
55. As a web user, I want a per-model-by-period table under the chart with a
    range-sum column and a per-column totals row consistent with the unfiltered
    chart's per-period totals, so that chart and table never disagree (see
    story 61 for the one deliberate exception, a legend "Other" filter).
56. As a web user, I want the over-time table to open scrolled to the most
    recent periods (and re-apply that on metric switch), with monthly headers
    rendered as month-plus-full-year, so that current data is what I see first.
57. As a web user, I want the Daily tokens contribution widget to appear in
    the Over-time tab rather than the Live tab, so that all day-by-day trend
    analysis is grouped with the other historical analytics.
58. As a web user, I want the Over-time tab to omit Subscription limits
    entirely, so that it remains focused on spend history instead of current
    provider capacity.

### Over-time legend and chart filter

59. As a web user, I want a legend row under the over-time chart listing the top
    five models by the selected metric plus an "Other" bucket, each with the
    color swatch used for its stack segments, so that I can tell which color is
    which model without hovering every bar.
60. As a web user, I want clicking a legend entry to filter the chart down to
    just that model's per-period values, and clicking the same entry again to
    clear the filter, so that I can read one model's trend without the other
    models stacked on top of it.
61. As a web user, I want the legend's "Other" entry to cover every model
    outside its own top five rather than mirroring the chart's "Other" stack
    segment, so that the six legend entries together account for 100% of every
    period and no model is missing from the legend; I accept that a filtered
    "Other" bar therefore reconciles with no single row of the table.
62. As a web user, I want an active filter to be obvious on screen (the other
    legend entries dimmed, and the caption under the chart naming the filtered
    model and how to clear it), so that a filtered chart is never mistaken for
    the full picture.
63. As a web user, I want the caption to disclose the "Other" filter's scope
    ("Filtered to Other (all models outside the top 5)") rather than just naming
    it, so that I understand why an Other bar reconciles with no row of the
    table below instead of reading the mismatch as a bug.
64. As a web user relying on assistive technology, I want each legend entry to
    expose its toggle state programmatically rather than through dimming alone,
    so that which model the chart is filtered to is announced, not just seen.
65. As a web user, I want the filter to survive a granularity change and to
    clear itself automatically when the filtered model is no longer in the top
    five (for example after switching metric), so that the chart never renders a
    stale or empty filter.
66. As a web user, I want the per-model-by-period table under the chart to keep
    showing every model regardless of the chart filter, so that the filter stays
    a chart-reading aid while the table remains the complete record of the range.

### Controls and state

67. As a web user, I want a free-text time input accepting the shared grammar,
    with independent per-mode values (Live defaults to today, Over-time
    defaults to the current month) persisted across sessions, so that each mode
    remembers its own natural window.
68. As a web user, I want the usage view's mode, view toggle, granularity, and
    time inputs persisted in local storage, so that the panel reopens the way I
    left it.
69. As a web user, I want wide ranges ("all", a full year) to return complete
    data rather than silently truncating at a small row limit, so that
    long-window charts are trustworthy.
70. As a web user, I want tokens formatted compactly (K / M / B), costs as
    dollars with cents, and requests as plain numbers, consistently across
    cards, charts, tooltips, and tables, so that numbers are readable at every
    scale.

## Implementation Decisions

### Storage

- **One generic table, one grain.** A single daily-keyed table holds the usage
  time series. Each row is unique on `(user, usage_date, source, scope_id,
  model)`; writes are idempotent upserts on that key (the same pattern as the
  finance price table). Token counters use 64-bit integers.
- **Row dimensions.** `source` is the spend pipe (currently only `crs`);
  `provider` is the model vendor derived from the model id (bare
  `claude-*`/`gpt-*`/`gemini-*`... prefixes, or the `vendor/` prefix of
  OpenRouter-style ids); `model` is the specific model id with `*` reserved as
  an all-models sentinel; `scope`/`scope_id`/`scope_name` allow finer
  attribution later, with the current pipeline writing only the global
  aggregate sentinel (`scope='aggregate'`, empty `scope_id`).
- **Metrics per row.** Input, output, cache-create, cache-read, and total
  tokens; request count; USD cost with a `cost_basis` marker. The relay always
  computes cost from official list API pricing, so the dollar figure is only
  *actual spend* for a pay-per-token key (`real`) and is **notional** for a
  subscription-backed key that charges a flat fee (`notional`): CRS marks such
  a figure up with list price even though no dollars were charged. Detection is
  per key at sync time: the relay's `GET {origin}/openai/key-info` names the
  subscription key `subscription`, and any key so named is `notional`; any
  other name, and any detection failure, defaults to `real` (never downgrade a
  spend figure to notional on uncertainty). On the go-forward per-key sync, a
  per-model row is `notional` only when *every* contributing key is
  subscription-backed, otherwise `real`. Historical backfill uses the relay's
  global admin stats, which do not attribute models to keys, so newly inserted
  rows default conservatively to `real`. When a row already exists, backfill
  refreshes its counters and cost without overwriting its go-forward
  `cost_basis`; it neither claims unsupported attribution nor erases known
  attribution.
- **Layering.** Standard entity, repository, service slice; the CLI and worker
  call only the service; migration SQL is hand-run by the maintainer per the
  repo convention.

### Sync (go-forward)

- **Single source: the relay.** A dedicated OpenRouter ingestion (provisioning
  key plus the activity endpoint) was built first and then removed once all
  OpenRouter-bound bots were re-fronted through the relay; the relay
  path-routes non-native model ids on its chat-completions endpoint to its
  OpenAI-compatible upstream account, so OpenRouter usage is recorded in the
  same per-key relay stats as Claude and Codex. One pipe, one parser. The
  sequencing rule was: never remove a working ingestion path until the
  replacement is confirmed capturing usage end-to-end.
- **Key enumeration is data-driven.** The sync derives its targets from the
  user's bot configs: every distinct relay key (deduplicated by origin plus key
  secret, since one subscription key is shared by multiple bots) is queried
  once against the relay's per-key user-model-stats endpoint for today's
  per-model rows. New keys are picked up with no code change. The completeness
  boundary is deliberate: keys that exist on the relay but appear in no bot
  config are not tracked.
- **Aggregate, not per-key.** Per-key results are summed per model into one
  global aggregate row per model per day. Per-key rows were designed and
  rejected: the product question is "what did each model cost", not "which key
  carried it", and the aggregate keeps the unique key simple and the web
  aggregation collision-free.
- **All-or-nothing error semantics.** If any key's fetch fails, the run writes
  nothing and reports an error. Writing a partial sum would silently replace a
  correct aggregate with an undercount; aborting preserves the last good rows.
- **Day stamping.** `usage_date` is local-today in the configured timezone
  (default Asia/Shanghai), mirroring the relay's timezone-stamped Redis day
  buckets, so both systems agree on day boundaries.
- **Triggers.** Three, all through the same service function: a scheduled
  worker-Lambda action on a daily cron at 23:50 local (just before the day
  rolls, since the relay's per-key daily endpoint only ever exposes today); a
  CLI sync command; and an authenticated API sync endpoint used by the web
  refresh button, which returns the sync result envelope so the panel can
  revalidate afterward.
- **Streaming caveat.** The relay records usage for non-streaming
  chat-completions only, and all in-scope bots are non-streaming. If a bot ever
  switches to streaming, the relay's streaming usage parser must be extended
  first or that bot's usage is silently lost.

### Backfill (one-shot)

- **Admin dated window, manual only.** A CLI backfill command logs into the
  relay's admin session with credentials supplied via environment or local
  config at invocation time, fetches per-model per-day stats for each day in
  `[today - N, yesterday]` (N defaulting to the relay's ~32-day daily-bucket
  retention), writes rows at the same daily aggregate grain as go-forward sync,
  and discards the session. The admin endpoint has no per-key breakdown, so the
  backfill does not supply `cost_basis`: a newly inserted row defaults
  conservatively to `real`, while an existing row keeps the label previously
  established by go-forward sync. Backfill therefore refreshes counters and cost
  without inferring historical per-model attribution from the current key
  topology or downgrading known attribution. Credentials and tokens never reach
  the database, logs, or the deployed Lambda.
- **Yesterday cap.** The backfill never writes today, so the recurring sync
  owns the in-progress day and the two paths cannot fight.
- **Lifetime anchor rejected.** A design for storing the relay's all-time
  cumulative total as a sentinel row (distinct scope, epoch date) was cut
  before implementation: a cumulative lump and an additive daily series in one
  table create a standing double-count hazard for every consumer, and the
  dated window covers the actual charting need. History older than the relay's
  retention is acknowledged as unrecoverable.

### Subscription limit-window status

- **Separate operational dataset, no persistence.** Subscription limit windows
  are current provider-account status, not spend history. They do not share the
  daily per-model table, relay sync, date filtering, or historical analytics,
  and y-agent stores nothing: every read is live. Nothing is written to
  PostgreSQL and this feature has no migration SQL.
- **Three providers, three readers, one envelope.** `claude_tui_usage` for
  anthropic (drive the `claude` CLI's own `/usage` view in an ephemeral tmux
  session and parse the rendered pane), `codex_usage_api` for openai/codex
  (authenticated GET of the Codex usage endpoint), `xai_billing_credits` for
  xai (authenticated GET of the xAI CLI's billing endpoint, tried in two
  shapes; see below). The three run concurrently; one reader's failure is
  isolated into the envelope's `errors[]` and can never take the other two
  down. There is no provider-selector flag: callers take the whole envelope or
  nothing.
- **claude-relay-service is not in this path at all.** The earlier design read
  both providers through a CRS self-service endpoint backed by CRS's Redis
  snapshots. That was removed, not wrapped: CRS's per-key fan-out, its
  passive Codex response-header snapshot, its relay-account scoping, and the
  `no_stable_account_scope` result no longer exist here. The daily **spend**
  sync still runs on CRS and is untouched. CRS remains the meter for relayed
  traffic; it is simply no longer the source of subscription status.
- **Window kinds are per provider, not a fixed pair.** Contract kinds are
  `five_hour`, `one_week`, and `billing_period`. Anthropic reports 5-hour and
  1-week; Codex reports its rolling rate-limit windows, keyed on each window's
  own reported duration and **never** on primary/secondary position (a live
  sample returned the one-week window as "primary" with the secondary null);
  xAI reports one `billing_period` usage row with the period end as its reset.
  A row is usable when **any** window carries a real percentage. Demanding the
  5-hour/1-week pair would leave Grok permanently unavailable. Claude's
  optional model-specific weekly window is retained under `extra_windows`, and
  a provider-specific `extra` map (xAI's `used`/`monthlyLimit`, prepaid
  balance, on-demand cap/used, unified-billing flag) rides along on the
  window.
- **xAI's percent has two source shapes, plain-first (todo 3001).** The
  reader is not a single fixed-field parse: it requests the plain
  `GET /v1/billing` view first and derives `used_percent` from
  `config.used.val / config.monthlyLimit.val * 100` (guarded against a
  missing/non-numeric/zero-or-negative denominator: a malformed pair
  normalizes to no window, never a fabricated percent); only when that view
  yields no window does it fall back to `GET /v1/billing?format=credits` and
  read `config.creditUsagePercent` directly when present. Both shapes share
  one parser and the same `billing_period` window kind, so nothing downstream
  (contract, envelope, web card) needs to know which shape produced a given
  reading. Plain-first exists because, as of 2026-08-03, the account's
  `?format=credits` view stopped carrying `creditUsagePercent` while the plain
  view's `used`/`monthlyLimit` pair stayed populated (the reverse of the
  shape this reader originally shipped against, todo 2872).
- **Execution on the VM, not in Lambda.** All provider HTTP and the scrape live
  in `y usage limits [--json] [--refresh]`, which runs on the user's VM;
  `GET /api/usage/limits` SSH-execs it and normalizes the returned envelope.
  The reason is source IP: shared cloud egress already drew a rate-limit
  response from one vendor on an unauthenticated probe and another vendor is
  Cloudflare-fronted, while the VM's address is stable and already known to all
  three. The CLI emits exactly the envelope shape the normalizer consumes, so
  the envelope *is* the boundary contract, pinned from both sides.
- **Layering: transport in `agent`, normalization in `storage`.** SSH
  orchestration, the poll memo, and the VM-asleep guard live in the `agent`
  package; `storage` keeps pure normalization behind one public
  `normalize_envelope(raw, ttl_seconds, origin)`: dict in, dict out, no
  transport vocabulary. Putting the SSH call in `storage` was infeasible rather
  than merely inelegant: `storage` declares no dependency on `agent`, the
  dependency runs the other way, and CI resolves each package's environment
  separately, so a `storage` import of `agent` would fail its own test job.
- **Error vocabulary is a closed set of codes, never free text.** The CLI's
  provider-level codes are exactly `not_logged_in`, `reauth_required`,
  `parse_failed`, `transport_error`. The backend wrapper adds transport-level
  codes `vm_unreachable`, `cli_failed`, `bad_payload`, plus `malformed_item` at
  envelope level. Availability is `available`, `unavailable`, or
  `reauth_required`. Raw exception text (which can carry a private IP or
  hostname) reaches logs only, never a caller-visible field, and the web maps
  every code to human copy with a generic fallback for anything unmapped.
- **Malformed data is never a number.** Missing, non-numeric, NaN, or infinite
  percentages normalize to null and render as unavailable; an unrecognized
  provider response shape becomes `parse_failed`. A vendor changing its schema
  must produce a dark card, never a fabricated 0%.
- **Degradation rules.** Any non-`available` availability collapses to
  `unavailable` freshness. A transient SSH/CLI failure degrades only rows that
  were `available` into `stale` with their last percentages retained; it must
  not overwrite an actionable per-row code such as a dead grant. A stopped EC2
  instance answers `vm_unreachable` immediately and is never started to serve a
  status poll; the last good snapshot returns intact on the next successful
  read.
- **Poll-cost guard, two layers.** A ~60s per-user in-process memo collapses a
  burst of panel polls into one SSH round trip; the CLI separately owns a ~240s
  on-VM cache for the scrape alone (a TUI spawn costs seconds; the two HTTP
  reads are cheap and always run fresh). The scrape TTL sits under the 300s
  freshness TTL so a cached reading never surfaces as stale, and a cache hit
  keeps the **original** observation time, since restamping it would make
  freshness lie. `--refresh` / `?refresh=true` bypasses both layers and is reachable only
  by explicit user action: the periodic poll keys on the bare URL, and the
  retry control is a one-shot fetch that seeds the cache without revalidating.
- **Never spend tokens for status.** The Anthropic reader launches its
  ephemeral session with no provider env vars, so it reads the subscription
  grant, runs no model turn, and cannot disturb concurrent relay-backed agent
  turns; the other two readers are plain authenticated GETs.
- **Account scope.** Status is account-wide, and the Usage view presents
  exactly one deterministically selected representative per backend, preferring
  a fresh available row with usable windows, then stale usable data, then an
  unavailable row (so a dead-grant card still renders), with ties broken by
  observation recency and stable identity fields.

### Realtime run rate

- **CRS is the authoritative source.** The Live Usage view can show the relay dashboard's system-wide RPM and TPM over CRS's own five-minute Redis bucket window. y-agent cannot reconstruct this from `model_usage_daily`, which is daily aggregate data, nor from its overwritten per-chat context-token counters.
- **VM-only admin access.** `y usage rate --json` authenticates to CRS's `GET /admin/dashboard` on the user's VM using the VM-local `[crs] admin_username/admin_password` config. `GET /api/usage/rate` SSH-execs that CLI command, applies a per-user ~60-second memo, and never wakes a stopped VM. Lambda receives only the CLI's closed envelope `{rpm, tpm, window_minutes, is_historical, observed_at, error}` plus an API-only `stale: true` marker when a transient VM/CLI failure retains the prior reading. It never receives or stores the admin credential.
- **Availability semantics.** A historical CRS fallback (`is_historical: true`, including a zero-minute source window) is unavailable rather than a live rate. Malformed source fields are null with a closed error code, never fabricated as zero. A transient VM/CLI failure retains the last good reading with a stale error marker; a VM-asleep poll responds `vm_unreachable` without starting EC2. The UI's 60-second, visibility-gated poll shares the existing Usage limits cadence.

### Provider credential lifecycle

- **The vendor's own credential file is the single source of truth.**
  `~/.codex/auth.json` (openai) and `~/.grok/auth.json` (xai) are read directly
  and live. y-agent keeps **no credential store of its own** and has **no login
  command**: `y usage login` and `$Y_AGENT_HOME/.credentials/provider-usage.json`
  were built, shipped once, and then deliberately deleted.
- **Anthropic handles no token at all.** Its reader asks the `claude` CLI to
  render a number that CLI already knows, so there is no PKCE flow, no refresh
  path, and no credential file on y-agent's side for this provider. The 30-day
  session cap on the subscription grant still applies; y-agent implements none
  of it and simply reports `reauth_required` when the CLI is logged out.
- **Refresh writes back into the vendor's file.** When the access token has
  expired (60-second margin), y-agent refreshes it at that provider's OAuth
  endpoint and writes the rotated grant back into the same vendor file in its
  exact original shape, i.e. what the vendor CLI would have done itself. Both
  providers rotate `refresh_token` on use, so writing back is mandatory, not a
  convenience.
- **Write safety is the contract, not an implementation detail.** Every write
  takes an exclusive advisory lock on a sibling `.lock` file (never the
  credential file itself), re-reads the file under that lock (a concurrent
  refresh makes this one a no-op instead of racing it), writes through a
  same-directory temp file with `fsync` plus atomic `os.replace`, preserves the
  original mode, preserves every unrelated field, and **never writes unless a
  refresh has already succeeded**, so any failure path leaves the file
  byte-identical.
- **File shapes were live-verified, not inferred.** The Codex file nests the
  grant under `tokens` and carries no expiry field, so the access token's own
  JWT `exp` claim is the expiry; the Grok file nests its record under a dynamic
  `"{issuer}::{client_id}"` key that must be discovered generically rather than
  hardcoded, and the rotated grant is written back under that same key.
- **Why the original design died (do not re-derive it).** The first design had
  y-agent hold its **own copy** of each grant, imported from the vendor CLI.
  Live evidence killed it: OpenAI revokes prior sessions account-wide on a new
  `codex login`, so the copied grant came back with a real
  `401 refresh_token_invalidated` and would have done so after every future
  `codex login`. xAI tolerates concurrent grants; OpenAI does not. Reading
  through removes the second grant entirely, so there is nothing left for a
  vendor login to invalidate and no per-provider login ordering to get right.
- **A read-only variant is rejected too, on separate evidence.** Reading the vendor's
  already-refreshed access token and never refreshing it goes dark whenever
  that token expires between the user's own CLI sessions, which makes a
  60-second-polled panel depend on unrelated CLI habits. And since both
  providers rotate the refresh token on use, refreshing *without* writing back
  is precisely what killed the live `codex` login during this work.
- **Re-auth is always a vendor action.** `claude login`, `codex login`,
  `grok login`, which is exactly what the `reauth_required` card names.
  `y usage credentials` reports each provider's state (`active` /
  `reauth_required` / `not_logged_in`) by exercising the real refresh path, and
  never prints token material.
- **Calibration, recorded because it cost real time.** Much of the original
  design was reverse-engineered from CRS source and strings grepped out of
  shipped vendor binaries. Of the five such wire shapes later checked against a
  live response, **five were wrong**: the Grok credential file's nesting, the
  Codex usage response, the xAI billing response, the `/usage` overlay labels,
  and OpenAI's `invalid_grant` error shape (flat for xAI, nested for OpenAI).
  Treat any undocumented vendor shape as a hypothesis until a live response
  confirms it, and write parsers that fail loudly (null / `parse_failed`)
  rather than silently mis-parsing.

### Usage API

- **Raw-grain passthrough.** The model-daily endpoint returns a bare list of
  per-(model, day) row dicts filtered by source (default `crs`), time range,
  and limit, with internal integer ids stripped. Multi-day aggregation is the
  client's job by design: daily rows are tiny, and the finance views'
  server-side aggregation exists only because finance history is expensive to
  derive, which usage is not.
- **Shared time grammar, server-side.** The finance time parser was extracted
  into a neutral shared module (aliases plus range parsing over the Fava date
  grammar) and both subsystems import it; the usage view's earlier client-side
  parser subset was deleted. A `time` query parameter is authoritative when
  present; the parser's exclusive end boundary is converted to the repository's
  inclusive filter by subtracting one day. `today` is aliased to `day` for
  compatibility with persisted UI state. Explicit from/to date parameters
  remain as a fallback; with no range at all, both default to local today.
  Relative tokens (`day`/`today`, `week`, `month`, `ytd`/`mtd`/`qtd`/`wtd`, and
  `day-N` ranges) always resolve against `Y_AGENT_TIMEZONE`, never the process
  timezone: Fava's underlying day resolver (`fava.util.date.local_today`,
  otherwise plain `datetime.date.today()`) is rebound at import in
  `storage/service/time_range.py` to a configured-TZ `local_today()` helper in
  `storage/util.py`, the same helper the write path's day-stamping uses. Lambda
  and the VM both run the process in UTC while `Y_AGENT_TIMEZONE` defaults to
  `Asia/Shanghai`, so without this bind every relative token resolved to
  yesterday's window for the first 8 hours of each local day (todo 2953).
- **Heatmap totals endpoint.** A separate daily-totals endpoint returns
  per-day sums (tokens, cost, requests) across all models over the heatmap
  window: a given calendar year, or the month-aligned past 12 months (the
  first of the month 11 months back through today). This decoupling exists so
  the heatmap always renders its full window regardless of the Live filter.
- **Generous default limit.** The default row limit is high (100k) so wide
  ranges never truncate; per-model daily rows are small enough that this is
  safe.
- **Latest limit status.** A provider-neutral, authenticated endpoint
  (`GET /api/usage/limits[?refresh=true]`) SSH-execs the VM CLI's one-shot
  read, normalizes each returned provider entry (used/remaining percent,
  absolute reset time, observation time, availability, freshness), and selects
  one deterministic best candidate per backend. A single reader's failure is
  isolated into a per-origin error list rather than failing the whole read;
  manual retry and the web view's periodic poll call this same endpoint, the
  former with `refresh=true`, and nothing is persisted on the y-agent side.
  Responses omit internal integer ids and never fabricate a current value after
  a failed read: missing or malformed data stays null and visibly unavailable.

### Web views

- **Placement.** Usage lives on the bot page as a second view next to the bot
  config table, since models and bots are adjacent concepts, with a Live |
  Over-time mode toggle inside it. Presentation is per model, never per bot:
  bot-to-model is a lossy many-to-one free-text match and per-bot rows would
  duplicate shared-model usage. The expanded bot detail card may show the
  matching model's usage, clearly labeled as model-level.
- **Limit status placement.** A compact subscription-status section sits at
  the top of the Live tab, before its spend charts, because it answers an
  immediate routing/capacity question rather than an analytics question. It
  is not rendered or fetched for the Over-time tab, which remains a
  historical-spend-only view.
  Claude, GPT (Codex), and Grok share one card structure that renders whichever
  windows the provider reported (progress bar, used/remaining percentages,
  reset time, observed time, and a fresh/stale/unavailable badge), with a
  dedicated "no windows reported" state rather than empty rows. A
  `reauth_required` provider renders an actionable card naming the vendor login
  to re-run, distinct from plain unavailable and from `vm_unreachable`. Cards
  are classified from stable `backend`/`provider` identifiers, never from
  display text. Provider failures are isolated, the envelope's error list shows
  as a partial-read badge, and the limit refresh control is visually and
  behaviorally separate from spend refresh.
- **Metric selector.** One metric at a time (Tokens default, Cost, Requests),
  shared by the donut, heatmap, over-time chart, and tables' default sort.
  Tokens means total tokens including cache.
- **Top-N convention: two folds that coexist.** The *series* fold is top seven
  models by the selected metric over the range, descending, remainder into
  "Other". It is the one the donut, the over-time stack, and every table use, so
  chart and table totals always reconcile. The over-time **legend** applies a
  second, coarser top-five-plus-Other fold *on top of* that same seven-element
  array. Both conventions are live and neither replaces the other, because they
  answer different questions: seven segments is the amount of detail a chart can
  carry before the tail is noise, while a legend is a scannable index and a row
  of click targets, and five entries plus Other stay readable in one wrapped row
  inside a narrow resizable panel where eight would crowd or wrap awkwardly. The
  legend fold is *derived from* the series fold (it takes the first five named
  models of the existing rank order rather than re-deriving totals), so legend
  order can never disagree with stack order, and an unfiltered stack renders
  exactly as it did before the legend existed. The cost of the second fold is
  that the two "Other" buckets do not denote the same set, which is deliberate
  and covered in the next two bullets.
- **Over-time legend and click-to-filter.** A legend row sits under the chart,
  one button per legend entry, dot swatch plus model name, styled like the Live
  donut's dot-legend so the two panels read as one system. Swatch color comes
  from the same rank-to-palette formula the tooltip already uses, so swatch,
  bar, and tooltip colors always agree. The one exception is the legend's own
  "Other" entry, whose swatch is pinned to the neutral color unconditionally
  (see the next-but-one bullet). Clicking an entry filters the chart to that
  model and dims the others; clicking it again clears, and each entry carries a
  pressed state so the toggle is exposed to assistive technology rather than
  conveyed by dimming alone. While filtered, the stacked bars are replaced by a
  single-series bar of that model's per-period values and the caption under the
  chart names the filtered model and the way to clear it; for the "Other" case
  the caption additionally spells out the bucket's scope ("all models outside
  the top 5"), since that is the one filter whose total matches no table row.
  The filter is view state only: it clears itself
  when the model leaves the top five (metric switch) and survives a granularity
  change, since the legend depends on the range, not the bucketing.
- **The legend's "Other" partitions the period; the chart's "Other" is the
  tail.** The legend's Other reads per-period values straight from the raw
  per-period data (every model, no fold) rather than from the chart's folded
  rows, so the six legend entries sum to 100% of every period. That makes a
  filtered Other bar total intentionally match **no** row of the table below:
  the table's Other row is ranks eight and beyond, while the legend's Other is
  ranks six and beyond. The alternative (legend Other = chart Other) was
  rejected because it would leave ranks six and seven represented by no legend
  entry at all, i.e. a legend that silently omits two of the models it is
  drawing. A legend that adds up is worth more than one that is arithmetically
  interchangeable with a table row.
- **The legend "Other" swatch is neutral in every dataset.** Because the two
  Other buckets denote different sets, giving the legend's Other the chart's
  Other color (which the shared rank-to-palette formula would do once more than
  seven models exist) would imply a one-to-one mapping to a single stack segment
  that does not hold, and would flip the same entry between two colors depending
  on how many models the range happens to contain. The swatch is therefore
  pinned to the neutral color unconditionally. The shared color function itself
  is deliberately left alone, so the filtered bar and the tooltip keep the color
  semantics they had; only the legend swatch differs.
- **The chart filter does not filter the table.** Filtering is scoped to the
  chart; the per-model-by-period table under it always shows every model. This
  is what the requesting todo asked for ("filter the chart") and it keeps the
  table as the complete record of the range, but it is surprising enough to be
  worth stating: a user may reasonably expect the table to follow. It is
  recorded here as delivered behavior, not as an oversight; extending the filter
  to the table stays out of scope until asked for.
- **Donut presentation** follows the relay dashboard's distribution chart:
  no on-slice labels, a bottom dot-legend (wrapped a few items per centered
  row, sorted by share descending to match slice order), hover tooltip with
  model, value, and percent. The three range totals render in the donut hole
  as an HTML overlay pinned to the chart center (a chart-library center label
  drifts when the legend reserves space), with explicit stacking order so the
  tooltip renders above the overlay. Solarized palette throughout, not the
  relay's raw hex palette: the adopted element is the layout, not the colors.
- **Live table.** Percent column relative to the active numeric sort column's
  total; metric-first column order; sticky header and sticky Total row over an
  internal scroll area sized to about five data rows; progressive column
  reveal driven by container (panel) width, not viewport width.
- **Cache-hit share is a first-class column.** The one number that makes
  bridged-model caching diagnosable (`cache_read / all_tokens`, already on
  every row) is rendered as a per-model percentage alongside the tokens/cost
  columns. Because cache hit is already a percentage, sorting by it excludes
  the separate share-of-active-column `%` calculation used by the other numeric
  metrics; the `%` column then falls back to each model's share of total tokens,
  exactly as it does when sorting by Model. A bridged model like `gpt-5.6-sol`
  reads ~2% while a native `claude-opus-5` reads ~94%, so the gap is visible
  without manual arithmetic. The percentage is derived client-side from the two
  ingested counters; nothing new is stored.
- **Notional cost is not presented as spend.** A row whose `cost_basis` is
  `notional` (a subscription-backed key charged a flat fee, see Storage) shows
  its dollar figure as notional list-price, for example with a marker, italics,
  or a "notional" badge, rather than as a dollar amount implying money was
  charged. A multi-day model row is labelled `notional` only when every daily
  row in the selected window is `notional`. Because historical backfill defaults
  new rows to `real` and go-forward sync writes only the current day, windows
  containing pre-feature history remain unlabelled until they contain only
  post-feature notional days; historical figures such as the original $316/mo
  and $149 observations remain conservatively presented as spend. This turns
  future all-notional windows from a spend anomaly into the efficiency fact they
  actually are without retroactively asserting attribution the source lacks.
- **Heatmap.** GitHub contribution semantics: week columns left to right,
  Monday to Sunday top to bottom, month labels on the column containing each
  month's first day, Mon/Wed/Fri gutter labels, five-bucket sequential
  Solarized-green scale where bucket boundaries are absolute per-metric
  thresholds (100M tokens / $100 cost / 1,000 requests per step, five steps to
  a `5x` ceiling), hover tooltip with date and exact metric value, and a
  legend of numeric-labeled swatches (0 plus the five step values) rather than
  a Less-to-More row. Days above the ceiling leave the discrete scale for a
  linear ramp interpolated toward the window's maximum, with the legend
  showing an extra ramp swatch only when that maximum exceeds the ceiling.
  Colors are opaque greens sampled off one gradient per theme mode rather than
  alpha-over-card steps, since alpha flips direction with the theme and cannot
  continue past `alpha=1`. Because the thresholds are absolute, a quiet window
  no longer self-normalizes: an idle month renders uniformly pale instead of
  spreading across the full scale, which is intended. The grid scales to the
  panel width (never scrolls horizontally; scales up to a cap on wide panels)
  with the wrapper height set explicitly since CSS transforms do not shrink
  layout boxes. The Daily tokens widget belongs in the Over-time tab, alongside
  the stacked chart and period table; it is absent from Live.
- **Over-time.** Client-side bucketing of the fetched daily rows into daily /
  weekly (Monday-start) / monthly periods; stacked chart plus a
  model-by-period table with a range-sum column and a totals row; the table
  opens scrolled to the most recent columns and re-applies that scroll on
  metric switch; monthly period headers show the full year. Chart helpers
  (palette, period labels, tooltip) are small local copies rather than a
  refactor of the finance viewer; extracting a shared chart library is an
  acknowledged follow-up.
- **State persistence.** View toggle, mode, granularity, and the two
  independent time inputs (Live and Over-time) persist in local storage under
  stable keys; renames keep old key strings so persisted values survive.
- **Formatting.** Tokens compact to one decimal K / M / B above a thousand;
  cost as dollars with two decimals; requests as locale-formatted integers;
  tabular numerals everywhere.

## Testing Decisions

- **Idempotency is the storage contract to test:** upserting the same
  (user, date, source, scope, model) row twice yields one row with the second
  write's values; re-running sync or backfill leaves row counts unchanged.
- **Completeness and no-double-count are the sync contracts:** with multiple
  relay keys configured, the sync queries each distinct key once (shared keys
  deduplicated) and per-model sums match the relay dashboard's totals for the
  same day; a failing key aborts the run with no rows written.
- **Time grammar behavior is verified at the mapping level:** a table of
  representative inputs (bare year, month, quarter, specific date, explicit
  range, all/empty, day/today aliases) asserting the resolved inclusive date
  window, including the exclusive-to-inclusive end conversion. This caught the
  real off-by-one class once already.
- **Relative-token resolution is asserted under a process timezone
  deliberately different from the configured one.** The grammar table above
  runs with `TZ=UTC`, and the relative-token tests additionally pin
  `Y_AGENT_TIMEZONE` to zones on both sides of UTC (`Pacific/Kiritimati`,
  UTC+14, and `Etc/GMT+12`, UTC-12) so the assertion fails on any regression to
  process-local resolution at any hour of the day, not only during the
  reported 00:00-08:00 Asia/Shanghai bug window (todo 2953).
- **API responses are checked for the ID convention** (no internal integer
  ids) and for the default-today behavior when no range is supplied.
- **Provider mapping is contract-tested per reader** against captured live
  responses (not reverse-engineered shapes): Codex windows normalize by their
  own reported duration rather than array position, xAI's billing payload
  yields one `billing_period` window with the period end as its reset, the
  Anthropic pane parser is pinned by fixture, reset strings become absolute
  timestamps, optional extra windows never displace primary ones, and
  missing/malformed values become unavailable rather than 0%.
- **The CLI↔backend envelope is pinned from both sides:** the exact argv
  (`y usage limits --json`, plus `--refresh` only when requested) and timeout
  are asserted through a mocked command runner, and the normalizer is tested
  against envelopes in exactly the shape the CLI emits.
- **Degradation paths are driven end to end, not read off the diff:** a
  transient SSH/CLI failure degrades an available row to stale while leaving a
  `reauth_required` row's actionable code intact; a stopped instance answers
  `vm_unreachable` with no wake attempt (asserted by the command never being
  run); valid-JSON-wrong-shape yields an explicit `bad_payload` rather than an
  empty-looking success; a Grok-only row is available and fresh; malformed
  percentages normalize to null.
- **Credential write safety is tested on the file, not the code path:** a
  failed refresh leaves the vendor file byte-identical (hash before/after); a
  successful refresh preserves every unrelated field, the file mode, and Grok's
  dynamic nesting key; both the flat and the nested `invalid_grant` error
  shapes map to `reauth_required` without raising; a missing or empty file
  reads as `not_logged_in`.
- **Refresh cannot ride the poll:** every SWR key is swept to assert none
  carries `refresh`, the retry is asserted to be a single one-shot fetch of the
  `?refresh=true` URL that seeds the cache with revalidation suppressed, and
  the backend is asserted to skip its memo only when the flag is set.
- **Failure and freshness behavior is tested externally:** one reader can fail
  while the others succeed; a failed read retains the last successful snapshot
  as stale with an error code; several candidates resolve to one deterministic
  card per backend while origin errors stay separate; an unavailable candidate
  is still returned so a dead-grant card renders at all; no read launches a
  paid model turn solely to obtain status.
- **Raw codes never render as prose:** the UI is asserted not to emit an error
  code as a text node, and unmapped codes fall back to generic copy.
- **Frontend changes gate on typecheck, build, and unit tests.** The honest
  bar is "no new type errors versus HEAD", verified against a detached
  worktree of HEAD rather than asserted, because the project's baseline
  `tsc --noEmit` is not clean. Chart and table consistency is checked by
  construction (unfiltered chart per-period totals equal table column totals
  because both derive from the same seven-plus-Other fold).
- **The two folds are checked by their reconciliation contracts, not their
  internals:** the six legend entries' per-period values sum to that period's
  total (the legend partitions the period), a legend-Other filtered bar equals
  the period total minus the top five and is asserted to be *different* from the
  table's Other row whenever more than seven models exist, and the legend is
  asserted to carry no Other entry at all when five or fewer named models exist.
  Toggling a filter on and off is asserted to restore the original stack, and
  the table is asserted unchanged across both states. The legend's Other swatch
  is asserted neutral on both sides of the seven-model boundary, the caption is
  asserted to state the Other bucket's scope while that filter is active, and
  the legend entries are asserted to expose their pressed state.
- **Tab-scoping visual checks** confirm that Live shows Subscription limits but
  not the Daily tokens widget, while Over-time shows the Daily tokens widget
  but never renders or requests Subscription limits.
- **Limit-status states** cover fresh, stale, never-observed, provider-error,
  re-auth-required, missing-reset-time, zero-windows-reported, and narrow-panel
  layouts across all three backends, with configured-timezone reset labels
  checked against the absolute API timestamps. These are asserted in component
  tests and fixtures; screenshots are taken only on request, per the house
  policy that agent-driven UI runtime checks are opt-in.
- **Post-deploy smoke:** trigger a sync, confirm rows appear for the current
  day, spot-check a date's totals against the relay dashboard, then call the
  deployed limits endpoint and confirm all three providers return with an empty
  error list; cross-check the Claude numbers against `/usage` in an interactive
  Claude Code session and the Grok number against the vendor's own billing
  view, and confirm a relay-backed agent turn running concurrently is
  unaffected.
- Prior art to mirror: the finance test suite's derived-view style and the
  finance price table's upsert tests.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2887 | Stacked bar segments ordered by per-bar descending share | - | - | - | `pages/review-2887-usage-stack-order.md` | shipped |
| 2890 | Daily tokens heatmap weeks start Monday instead of Sunday | - | - | - | - | shipped |
| 2872 | Subscription limit windows read directly from Anthropic / OpenAI / xAI instead of claude-relay-service: three providers, per-provider window kinds, VM-side CLI reads, and read-through of each vendor CLI's own credential file | - | `pages/plan-2872-direct-provider-usage.md` (supersedes `pages/plan-2872-provider-usage-window-ownership.md`) | this PRD | `pages/review-2872-backend-usage-limits.md`, `pages/review-2872-backend-usage-limits-round2.md`, `pages/review-2872-web-usage-cards.md` | shipped (`09df56b` backend, `dfd75a2` web, `0c2c773` CLI, `3acdbc7` read-through) |
| 2953 | Fixed Live-tab day-boundary bug: relative time tokens (`today`, `ytd`, etc.) resolved in the process timezone (UTC) instead of `Y_AGENT_TIMEZONE`, showing yesterday's usage for the first 8 hours of each local day | - | `pages/plan-2953.md` | this PRD | - | in progress |
| 2970 | Frontend migrated off the built-in `BotList.tsx`/`BotViewer.tsx` onto the dynamic `bot` UI artifact (see `docs/prd/ui-dynamic-artifacts.md`); the built-in components and their vitest coverage were deleted, with no in-bundle fallback | - | `pages/plan-2970-bot-dynamic-ui.md` | - | `pages/review-2970-bot-dynamic-ui.md`, `pages/review-2970-rm-builtin-bot.md` | shipped |
| 2980 | Daily-tokens heatmap: the no-usage level was `SOL.base02`, the same value as the card border and table header, so empty cells vanished into the chrome under solarized-light. Level 0 is now a neutral gray derived per theme (`mix(base01, base03, 0.3)`), GitHub-style — a green tint was tried first and rejected for reading as "has usage". Colors moved from a module-level `HEATMAP_COLORS` const to `heatmapColors(colors)` called under `useThemeColors()`, since the const froze at import and would not repaint on a live theme toggle | - | - | - | - | shipped (`bot` artifact v5, `dbd2393185ff…`) |
| 2981 | "Tokens over time" gained a legend row: the top 5 models by usage plus an `Other` bucket, each with a color swatch, and clicking one filters the chart to that model (clicking again clears). The legend fold (top-5+`Other`) is derived from the existing series fold (top-7+`Other`) rather than computed independently, so legend order can never disagree with stack order. Legend `Other` reads per-period values straight from the raw per-period data, so the six entries partition 100% of every period; the consequence is that a filtered `Other` total intentionally reconciles with no single table row (table `Other` is ranks 8+, legend `Other` is ranks 6+). The table below the chart is deliberately not filtered. Nit pass in the same delivery pinned the legend `Other` swatch to the neutral ink in every dataset, disclosed the `Other` filter's scope in the caption, and added `aria-pressed` to the legend toggles | - | - | this PRD | `pages/review-2981-usage-over-time-legend.md` | shipped (`bot` artifact v6, `ee1136139151…`) |
| 2982 | Daily-tokens heatmap rebucketed from share-of-window-max to absolute per-metric thresholds (100M tokens / `$`100 cost / 1000 requests, five steps to a `5x` ceiling), with values above the ceiling leaving the discrete scale on a linear ramp interpolated to the window max. Six visual states: the todo-2980 empty gray plus five steps plus the ramp. The color model changed with it: alpha-over-card `rgba` steps were replaced by opaque greens sampled off one gradient per theme *mode* (`lum(base03)` picks light `#7bd992`→`#126329` or dark `#126329`→`#7bd992`), because alpha steps flip direction with the theme as a compositing side effect and cannot continue past `alpha=1`, which would have reversed the scale on one mode. `#9be9a8` (GitHub's) was rejected for landing within 0.005 luminance of the 2980 empty gray on light. Ramp position floors its denominator at `max(windowMax - ceiling, ceiling)` so a lone 505M day does not paint full depth. Absolute thresholds mean a quiet window no longer self-normalizes and renders uniformly pale — confirmed intended | `pages/design-2982.html` | - | this PRD | `pages/review-2982-heatmap-absolute-buckets.md` | shipped (`bot` artifact v9, `f617a3d5c617…`; v7 shipped the ramp painting black — `mix()` returns an `rgb()` string that `hexToRgb()` could not parse — fixed forward by making the ramp one expression on the same gradient rather than a precomputed endpoint two color representations had to agree on) |
| 2988 | Removed the small explanatory captions beside dashboard titles across Subscription limits, the daily heatmap, the over-time chart, and the history table | - | - | - | - | shipped (`bot` artifact v8, `1ba893108ee3…`) |
| 3001 | Grok card went `parse_failed` when xAI's `?format=credits` view stopped carrying `creditUsagePercent` (2026-08-03). Fixed by making the xAI reader plain-view-first: derive `used_percent` from `config.used.val` / `config.monthlyLimit.val` on `GET /v1/billing`, falling back to the legacy `creditUsagePercent` shape on `?format=credits` only if the plain view yields no window. No API/web/DB change — same `billing_period` window kind, same envelope contract, same `bot` artifact. Whether `creditUsagePercent` is gone for good or merely zero-omitted, and end-to-end confirmation via `y usage limits --json` on the VM, are unverified from this sandboxed impl session (no VM/SSH access); pending a run from an environment with VM access | - | `pages/plan-3001-grok-usage-parse.md` | this PRD | - | implemented, pending VM verification |
| 3025 | Distinguished subscription-backed notional token cost from real spend for go-forward daily usage and surfaced window-level cache-hit percentage; historical backfill preserves known basis but remains conservatively `real` where relay stats cannot attribute models to keys | - | `pages/plan-3025-bridged-model-prompt-caching.md` | this PRD | `pages/review-3025-track-b-notional-cost-r3.md`, `pages/review-3025-usage-panel-cleanup.md` | shipped (`c3de992` backend, `bot` artifact v10, `91728b28336b…`) |
| 3031 | Rolled forward from unsafe bot v10, hardened Usage against malformed top-level API payloads, surfaced refresh failures, and restored the prior Live cost presentation without notional annotations | - | - | - | `pages/review-3031-usage-payload-guards.md` | shipped (`bot` artifact v14, `6c44a56752b2…`; source `6fbf696`, `1b31f85`) |
| 3111 | Live Usage run-rate strip backed by CRS's five-minute dashboard RPM/TPM through a VM-only admin CLI and SSH API; unavailable, historical, stale, and VM-asleep states stay explicit | - | `pages/plan-3111-usage-run-rate.md` | this PRD | `pages/review-3111-bot-usage-run-rate-ui.md`, `pages/review-3111-usage-run-rate-backend.md` | shipped (`da3289a` backend, bot artifact v17, `ab050ed3a956…`; live VM response verified) |

## Out of Scope

- **Per-key, per-account, or per-bot usage attribution.** Only the global
  per-model daily aggregate is stored; per-bot display is a loose model-name
  match for presentation only.
- **Spend sources other than the relay.** Perplexity, Gemini CLI, and any
  tool's internal accounting are not ingested; a future non-relay pipe would
  add a new `source` value to the same table. The relay stays the meter for
  relayed spend even though it is no longer the source of limit windows.
- **Streaming usage capture** in the relay's chat-completions path (extend
  the relay's stream parser before any in-scope bot switches to streaming).
- **History older than the relay's ~32-day daily retention** (expired in
  Redis, unrecoverable) and the lifetime cumulative anchor (rejected design).
- **Server-side over-time aggregation** (revisit only if client payloads grow
  large) and a shared web chart-helper library extraction (follow-up).
- **Filtering the over-time table from the chart legend**, and multi-select
  legend filtering (only one model at a time, click again to clear). Both are
  deferred rather than rejected: the legend filter is a chart-reading aid, and
  neither has been asked for.
- **Relay admin credentials in Lambda, the database, or deployed worker.** The VM-only `[crs]` credential is the narrow exception for `y usage rate` and remains inaccessible to every deployed service. Backfill may still use invocation-time credentials.
- **A CLI listing/reporting surface** for spend rows (only sync and backfill
  commands exist; no consumer has asked for a terminal view). The limit-window
  side does have one, `y usage limits`, because the backend is built on it.
- **Rated / list-price cost reporting** (only real billed cost is stored and
  shown).
- **Historical limit-window analytics, alerts, or forecasting.** The feature
  retains the latest successful snapshot for display; notification thresholds
  remain owned by specialized monitoring skills, and predicting exhaustion is
  not part of the bot page.
- **Combining providers' percentages into one quota.** Their subscription
  limits are provider-account-specific, and Grok's is a billing period rather
  than a rolling window; the three are displayed side by side, never summed,
  averaged, or treated as interchangeable capacity.
- **A y-agent-owned credential store or login command.** Deliberately deleted,
  not deferred (see the credential-lifecycle rationale). Also out: encryption
  at rest for the vendor credential files (already 0600 on a single-user box),
  and automating Anthropic's monthly re-authorization via a stored browser
  cookie.
- **Waking the VM to serve a status poll**, and rendering the xAI `extra` map
  (prepaid balance, on-demand cap/used) in the card, which is carried as a
  contract field only.
- **A Grok rate-limit (429) badge.** The billing-period row is the better
  signal.

### Known follow-ups (recorded, not fixed here)

- **Refresh-window race.** y-agent holds its lock across the refresh network
  call, then `os.replace`s a snapshot taken before that call, so a `codex
  login` completing during the round trip can be overwritten. The fix is to
  re-read the on-disk `refresh_token` under the lock immediately before
  writing.
- **Missing byte-identity test for a transport exception out of the refresh
  function.** The failure path is covered for a rejected grant, not for a
  connection error raised mid-refresh.
- **`y usage credentials` raises an httpx traceback on a network blip** where
  it should print a status line like every other outcome.
- **The filtered chart's tooltip prints the same number twice** ("Total: X"
  then "<model>: X"), because with a single series the range total and the
  model's value are the same figure. Harmless and cosmetic; dropping the Total
  line while a filter is active is the fix.
- **Unresolved probe:** whether a cheap vendor command could make the vendor
  CLI refresh its own credential file, so y-agent would only ever read it and
  never write at all. That would retire the entire write-safety surface above.
