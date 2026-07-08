# Usage Tracking and Analytics: Per-Model LLM Spend Sync, API, and Bot-Page Views

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
given day was heavy or idle, without the numbers silently rolling off.

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

### Usage API

16. As an API consumer, I want per-model daily rows filtered by source and date
    range, so that any client (web, future CLI) can build its own views from
    the raw grain.
17. As an API consumer, I want to pass a single free-text time expression using
    the same grammar as the finance views (day, week, month, year, 2024-05,
    2024-q2, a specific date, "day-7 to day", ytd/mtd/all), so that one
    authoritative parser serves both subsystems and the usage view is not stuck
    with a weaker dialect.
18. As an API consumer, I want the default query (no range given) to return
    today's snapshot, so that the common "what is happening now" case needs no
    parameters.
19. As an API consumer, I want a per-day totals endpoint (tokens, cost,
    requests summed across models) over a rolling 12-month or single-calendar-
    year window, so that the contribution heatmap renders its full window
    independently of the Live time filter.
20. As an API consumer, I want responses to carry only public fields (no
    internal integer ids), so that the ID convention holds on this surface like
    every other.

### Live view

21. As a web user, I want a donut chart of each model's share of the selected
    metric over the selected time range, top seven models plus an "Other"
    slice, sorted by share descending, so that I can see at a glance which
    models dominate.
22. As a web user, I want the range totals for tokens, cost, and requests
    displayed inside the donut's center hole, so that headline numbers and the
    breakdown share one compact card.
23. As a web user, I want a clean donut with a bottom dot-legend (no on-slice
    labels) and hover tooltips showing model, value, and percent share, with
    the tooltip rendering above the center overlay, so that the chart reads
    like the relay dashboard's distribution chart the user prefers.
24. As a web user, I want a per-model table with a percent column computed
    against whichever numeric column is the active sort column, so that
    "share of tokens" and "share of cost" are one click apart.
25. As a web user, I want the table columns ordered metric-first (Tokens, Cost,
    Requests, then Input, Output, Cache), clickable-sortable, with a sticky
    header and a sticky bottom Total row, and about five rows visible before
    internal scrolling, so that the table stays compact inside the panel.
26. As a web user on a narrow panel, I want less-important table columns
    (input/output, then cache) to hide progressively based on the panel's own
    width, so that the layout adapts to the resizable panel rather than the
    viewport.
27. As a web user, I want a GitHub-style daily contribution heatmap (one cell
    per day, weeks as columns left to right, Sunday at top, a five-bucket
    sequential color scale, month labels, weekday gutter, hover tooltip with
    date and exact value, and a Less-to-More legend), so that heavy and idle
    days are visible over a year at a glance.
28. As a web user, I want the heatmap driven by the same selected metric as the
    donut and table, so that switching Tokens / Cost / Requests re-colors
    everything consistently.
29. As a web user, I want the heatmap window decoupled from the Live time
    filter: a rolling month-aligned past 12 months by default, or a whole
    calendar year when the time input is a bare four-digit year, so that
    narrowing the donut to "today" never blanks the heatmap.
30. As a web user, I want the heatmap to scale to the panel width (down to fit,
    up to a cap on wide panels) without horizontal scrolling, so that the full
    12-month grid is always visible.

### Over-time view

31. As a web user, I want a Live | Over-time mode toggle on the usage view
    styled after the finance viewer's mode toggle, so that the two analytics
    panels feel like one system.
32. As a web user, I want an over-time stacked chart of the selected metric per
    period, top seven models plus "Other", with daily / weekly / monthly
    granularity bucketed client-side, so that trends are visible at the grain I
    choose (the finance views stop at weekly; usage goes down to daily).
33. As a web user, I want one metric charted at a time via a Tokens | Cost |
    Requests toggle, so that the axis and stacking stay meaningful.
34. As a web user, I want a per-model-by-period table under the chart with a
    range-sum column and a per-column totals row consistent with the chart's
    per-period totals, so that chart and table never disagree.
35. As a web user, I want the over-time table to open scrolled to the most
    recent periods (and re-apply that on metric switch), with monthly headers
    rendered as month-plus-full-year, so that current data is what I see first.

### Controls and state

36. As a web user, I want a free-text time input accepting the shared grammar,
    with independent per-mode values (Live defaults to today, Over-time
    defaults to the current month) persisted across sessions, so that each mode
    remembers its own natural window.
37. As a web user, I want the usage view's mode, view toggle, granularity, and
    time inputs persisted in local storage, so that the panel reopens the way I
    left it.
38. As a web user, I want wide ranges ("all", a full year) to return complete
    data rather than silently truncating at a small row limit, so that
    long-window charts are trustworthy.
39. As a web user, I want tokens formatted compactly (K / M / B), costs as
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
  tokens; request count; USD cost with a `cost_basis` marker (always `real`:
  the relay's stored real cost on the go-forward path, its recomputed cost on
  the backfill path; both are official pricing).
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
  retention), writes rows in exactly the go-forward shape, and discards the
  session. Credentials and tokens never reach the database, logs, or the
  deployed Lambda.
- **Yesterday cap.** The backfill never writes today, so the recurring sync
  owns the in-progress day and the two paths cannot fight.
- **Lifetime anchor rejected.** A design for storing the relay's all-time
  cumulative total as a sentinel row (distinct scope, epoch date) was cut
  before implementation: a cumulative lump and an additive daily series in one
  table create a standing double-count hazard for every consumer, and the
  dated window covers the actual charting need. History older than the relay's
  retention is acknowledged as unrecoverable.

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
- **Heatmap totals endpoint.** A separate daily-totals endpoint returns
  per-day sums (tokens, cost, requests) across all models over the heatmap
  window: a given calendar year, or the month-aligned past 12 months (the
  first of the month 11 months back through today). This decoupling exists so
  the heatmap always renders its full window regardless of the Live filter.
- **Generous default limit.** The default row limit is high (100k) so wide
  ranges never truncate; per-model daily rows are small enough that this is
  safe.

### Web views

- **Placement.** Usage lives on the bot page as a second view next to the bot
  config table, since models and bots are adjacent concepts, with a Live |
  Over-time mode toggle inside it. Presentation is per model, never per bot:
  bot-to-model is a lossy many-to-one free-text match and per-bot rows would
  duplicate shared-model usage. The expanded bot detail card may show the
  matching model's usage, clearly labeled as model-level.
- **Metric selector.** One metric at a time (Tokens default, Cost, Requests),
  shared by the donut, heatmap, over-time chart, and tables' default sort.
  Tokens means total tokens including cache.
- **Top-N convention.** Charts show the top seven models by the selected
  metric over the range, descending, with the remainder folded into "Other";
  chart and table use the same fold so totals always reconcile.
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
- **Heatmap.** GitHub contribution semantics: week columns left to right,
  Sunday to Saturday top to bottom, month labels on the column containing each
  month's first day, Mon/Wed/Fri gutter labels, five-bucket sequential
  Solarized-green scale where bucket boundaries are ratios of the window
  maximum (0 empty, then quartile-style thresholds at 25/50/75 percent), hover
  tooltip with date and exact metric value, Less-to-More legend. The grid
  scales to the panel width (never scrolls horizontally; scales up to a cap on
  wide panels) with the wrapper height set explicitly since CSS transforms do
  not shrink layout boxes.
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
- **API responses are checked for the ID convention** (no internal integer
  ids) and for the default-today behavior when no range is supplied.
- **Frontend changes gate on the strict TypeScript build**, with chart and
  table consistency checked by construction (chart per-period totals equal
  table column totals because both derive from the same fold), and visual
  states (donut center overlay, tooltip stacking, heatmap fit, scroll
  positions) verified via headless-browser screenshots against real data,
  stored under the shared screenshots directory.
- **Post-deploy smoke:** trigger a sync, confirm rows appear for the current
  day, and spot-check a date's totals against the relay dashboard.
- Prior art to mirror: the finance test suite's derived-view style and the
  finance price table's upsert tests.

## Out of Scope

- **Per-key, per-account, or per-bot usage attribution.** Only the global
  per-model daily aggregate is stored; per-bot display is a loose model-name
  match for presentation only.
- **Sources other than the relay.** Perplexity, Gemini CLI, and any tool's
  internal accounting are not ingested; a future non-relay pipe would add a
  new `source` value to the same table.
- **Streaming usage capture** in the relay's chat-completions path (extend
  the relay's stream parser before any in-scope bot switches to streaming).
- **History older than the relay's ~32-day daily retention** (expired in
  Redis, unrecoverable) and the lifetime cumulative anchor (rejected design).
- **Server-side over-time aggregation** (revisit only if client payloads grow
  large) and a shared web chart-helper library extraction (follow-up).
- **Relay admin credentials in the deployed system** (backfill stays a manual
  one-shot with invocation-time credentials).
- **A CLI listing/reporting surface** for usage rows (only sync and backfill
  commands exist; no consumer has asked for a terminal view).
- **Rated / list-price cost reporting** (only real billed cost is stored and
  shown).
