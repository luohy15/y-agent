---
title: Bot Usage
type: prd
project: y-agent
feature: bot-usage
status: active
---

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
starting another long agent turn: how much of each retained paid subscription
(GPT (Codex) and Grok) is still available, and when it recovers. Claude
subscription limits are not part of that status. Those
provider-native limits need a current status surface of their own rather than
being inferred from token or dollar totals. They also should not depend on a
relay: routing limit status through claude-relay-service made the numbers a
function of a separate service staying deployed, configured, and in sync, and
it structurally could not answer for a provider the relay had no usage concept
for at all.

Totals also do not explain *why* a session was expensive. A y-agent chat
re-sends its whole context on every request: the system prompt, AGENTS.md /
CLAUDE.md rules, the skill listing and any loaded skill or reference bodies,
tool and MCP schemas, every tool result (large file reads, chat transcript
dumps), and the growing conversation. The user can see that a trace burned many
input tokens but not which of those contributors filled the context, when it
grew, whether the same file was read three times, or how much of each request
was served from the prompt cache. Without that breakdown there is nothing
concrete to trim (todo 3844).

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
subscription-limit status section for GPT (Codex) and Grok, read **directly
from each provider** rather than through any relay. Claude subscription limits
are not read or shown. Codex still reports rolling windows, `five_hour` /
`one_week`, in the fetched payload; the Live card draws the weekly window.
Grok reports its current billing period. Each drawn window shows percent used,
percent remaining, reset time, freshness, and explicit unavailable / stale /
re-auth states. The two reads run in the `y` CLI **on the user's VM** (stable
source IP, already known to these vendors), behind one `y usage limits --json`
envelope. A 30-minute worker
schedule SSH-execs that command per user, normalizes the result, and persists
the latest snapshot in `user_preference` (key `usage_limits_latest`, todo
3226); ordinary `GET /api/usage/limits` polls read only that persisted
snapshot and never touch VM, SSH, or CLI. No Codex/Grok subscription request
originates from Lambda: those live reads always run on the VM, and only the
resulting envelope is persisted. A manual `?refresh=true` still performs one bounded live read
through the same refresh function the schedule uses. Refresh is independent
from spend sync because the two datasets have different sources, cadence, and
failure modes.

Live also shows **Account balances** immediately above Subscription limits:
one OpenRouter tile and one DeepSeek tile, with each reported currency kept
separate. These are account credits, not subscription limits, per-key allowances,
or inferred spend totals. Their official API-key-authenticated reads run
server-side in the API Lambda, independently of the VM-only subscription path.

Subscription credentials are not y-agent's to own. For OpenAI and xAI the **vendor CLI's own
credential file** (`~/.codex/auth.json`, `~/.grok/auth.json`) is the single
source of truth: y-agent reads it live and, when the access token has expired,
refreshes it at the provider's OAuth endpoint and writes the rotated grant back
into that same vendor file, in that file's exact original shape: precisely
what the vendor CLI would have done itself. There is no y-agent credential
store and no y-agent login command. Subscription-limit refresh handles no
Anthropic grant: it does not scrape `/usage` and it does not exchange an
Anthropic token. Claude API spend stays on the relay. Re-authentication for a
limits card is a **vendor** action (`codex login` / `grok login`), which is
exactly what the expired-login card tells the user to run.

Session context analysis (todo 3844) explains a single chat's context
request by request. After a run, the VM analyses that chat's attributed Claude
Code transcript locally and uploads only bounded derived metadata: per request,
the observed cache counters plus an approximate breakdown of what the context
contained by category (system prompt, rules / memory, skills and references,
tool / MCP schemas, tool results, conversation history), with sizes, owner-only
relative source labels and content hashes, never bodies. A Context view on the
chat detail and `y chat context <chat_id>` show per-request prompt size and
growth, cache reuse, the largest contributors, repeated reads and compaction
events, plus deterministic suggestions. Everything not provable from the
transcript is shown as unknown rather than filled in. Cost stays unavailable.
Trace views link into each chat's Context; a Bot Usage session ranking is a
later delivery.

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
14. As a user, I want the backfill (and the direct run-rate path) to authenticate
    with relay admin credentials resolved DB-first from the `user_preference`
    key `crs_admin` (shape `{username, password, session_token,
    token_expires_at}`), falling back to env / the local `[crs]` config block so
    one-shot local runs still work without a prior `y usage crs-creds set`. The
    previous "never persist admin secrets" rule was deliberately revised under
    todo 3121 so the API Lambda can call the Relay admin API directly; the
    blast-radius escalation (admin creds > per-key API keys already stored in
    `bot_config.api_key`) is accepted, and no secret-encryption layer is added
    here (see Out of Scope).
15. As a user, I want re-running the backfill to be a no-op-equivalent upsert,
    so that a flaky run can simply be retried.

### Subscription limit-window status

16. As a web user, I want the Live tab of the bot Usage view to show
    subscription-limit status for GPT (Codex) and Grok, and not a Claude
    subscription card, so that I can choose a retained backend with enough
    available capacity before starting work without adding operational status
    to the historical Over-time tab. Claude API spend, models, and stored
    limit history stay.
17. As a user, I want each provider's numbers read straight from that provider,
    so that limit status does not depend on a relay service staying deployed,
    configured, and in sync, and so that a provider the relay has no usage
    concept for can still be shown.
18. As a web user, I want the Live card to show the weekly window for GPT
    (Codex) and the current billing period for Grok. Codex's 5-hour window
    stays in the fetched payload and is not drawn. A provider is not given an
    empty row for a window it does not have.
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
26. As a user, I want subscription status limited to each retained provider's
    primary windows, with no model-specific extra window collected or shown.
27. As a user, I want a status read to never spend model tokens, so that
    looking at my remaining allowance never consumes it.
27a. As a user, I want a usage refresh to leave the named `fable` bot's
    enabled bit unchanged. Removing the old quota gate does not enable or
    disable it, does not create a config, and does not change routing. I still
    enable or disable that bot by hand.
28. As a user, I want every limit refresh, including the ones that fail or
    find a provider missing, kept as history I can read back by hour next to
    that hour's token and cost totals, so that a window resetting inside the
    hour does not erase the peak and a failed probe is not mistaken for "no
    usage".

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
    naming the **vendor** command to re-run (`codex login` or `grok login`),
    so that I can fix it without knowing y-agent's internals.
32. As a user, I want a CLI command that reports each provider's credential
    state without ever printing token material, so that I can diagnose a dark
    card from a terminal safely.
33. As a user, I want subscription-limit refresh to perform no Anthropic token
    handling, so that Claude API spend can keep using the relay without a
    subscription login path in this feature.

### Read cost and availability

34. As a user, I want the Codex/Grok subscription calls made from my own VM rather than from
    Lambda, so that requests come from a stable source IP these vendors already
    know instead of shared cloud egress.
35. As a user, I want a stopped VM to answer the status poll immediately with
    an explicit unreachable state instead of being started, so that opening a
    panel never boots an instance.
36. As a user, I want both subscription reads (Codex and Grok) to run fresh on
    each limits command, so that a poll does not replay a cached scrape and
    freshness never lies about a stale observation.

### Hourly grain

37a. As a user, I want each model's hourly token counts, request count, and
    real USD cost persisted in y-agent's database for the recoverable window
    (about 7 days, matching the relay's hourly Redis TTL), so that today's
    activity can be charted by hour and, for every complete local day after
    the zero-cost authority ships, hourly totals reconcile with the daily
    aggregate for that Asia/Shanghai date.
37b. As a user, I want the same go-forward sync that refreshes today's daily
    rows to also pull hourly counters for yesterday and today across every
    distinct relay key, so that the previous day's final hour is repaired
    after midnight and the in-progress hour converges without a separate job.
37c. As a user, I want the scheduled sync to run every hour at minute 50 local
    (preserving the last run of a local day at 23:50), so that both grains
    stay fresh without me remembering to trigger them.
37d. As a user, I want a one-shot hourly backfill limited to at most 7 local
    days (the relay's hourly TTL), so that the recoverable window can be
    seeded without pretending older hours exist.
37e. As an API consumer, I want per-model hourly rows filtered by source and
    date range, defaulting to today, with a server-computed `partial` flag on
    the row whose (date, hour) equals the server's current configured-timezone
    hour, so that the Live "today by hour" strip can mark the in-progress bar
    without trusting the browser clock.
37f. As a web user, I want Live's run rate in the header metadata, with a wide
    panel's left column showing Account balances above Subscription limits
    (GPT weekly and Grok billing-period rows) above Today by hour, and Model
    share (donut with the shared metric toggle) in the right column. Below the
    720px container width, I want Model share → Account balances → Subscription
    limits → Today by hour → Models, with the per-model table full width below
    both columns on wide panels, and Over-time to
    offer an `H` granularity clamped to 7 days, so that short-horizon activity
    stays visible and daily / weekly / monthly views stay unchanged.
37g. As a web user, I want the Over-time `H` granularity to replace the daily
    contribution card with a seven-day grid of the last seven local calendar
    dates (oldest at top, today at bottom) by 24 hour columns, driven by the
    same selected metric, summed across every model when the Filter models
    query is empty and across the matching models when it is not (story 66e),
    so that the short hourly window is readable hour by hour instead of as a
    year of day cells.
37h. As a web user, I want each hourly cell to distinguish a recorded zero from
    an hour with no stored row and from an hour that has not happened yet, and
    to mark the in-progress hour from the server's `partial` flag, so that a
    gap in ingestion is never displayed as a quiet hour.
37i. As a web user, I want the hourly grid readable without relying on color:
    every hour label, seven unambiguous date labels, a state legend, and a
    hover/focus readout carrying the full date, hour range, timezone, value or
    state, and any partial marker, so that keyboard and assistive-technology
    use reads the same facts as hovering.
37j. As a web user, I want an empty but successful hourly response to still
    render the seven-day window as no-data / future cells rather than hiding
    the view, and loading and error states to stay visibly distinct from it,
    so that "nothing recorded" is never confused with "nothing fetched".
37k. As a web user in Hangzhou or anywhere else, I want the hourly grid's
    dates, hour columns, and zone label to follow my browser timezone exactly
    like the rest of Over-time, so that one panel never mixes two calendars.

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

41a. As a web user, I want each model row to show distinct y-agent chat sessions
    with attributed assistant output in the selected period, so that route
    allocation is visible separately from relay workload.
41b. As a web user, I want each model row to show answered prompt groups (turns),
    so that a long agent loop is not mistaken for many user turns.
41c. As a web user, I want each model row to show average relay requests per
    attributed answered turn (`Requests / Turns`) for the same period, with
    unavailable shown when Turns is zero or activity is unavailable, so that
    agent-loop depth is visible without dividing by zero or implying matched
    per-prompt request telemetry.

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
    per day, weeks as columns left to right, Monday at top, a sequential color
    scale whose occupied bins are nice-rounded quintiles of the non-empty cells
    in the currently rendered window, month labels, weekday gutter, hover
    tooltip with date and exact value, and a legend of numeric boundary swatches
    that states the scale is relative to this window), so that heavy and idle
    days stay distinguishable as usage grows and as the hourly grid uses a
    different magnitude.
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
    range-sum column and a per-column totals row consistent with the chart's
    per-period totals for the same model set, so that chart and table never
    disagree. An empty model query uses the unfiltered top-seven-plus-Other
    fold (see story 61 for the legend "Other" exception, and story 66: any
    legend click changes only the chart). A non-empty query lists every match
    in global rank order, with no Other row and no cap, and each column total
    equals that period's matched
    chart total (story 66e).
56. As a web user, I want the over-time table to open scrolled to the most
    recent periods (and re-apply that on metric switch), with monthly headers
    rendered as month-plus-full-year, so that current data is what I see first.
57. As a web user, I want the Daily tokens contribution widget to appear in
    the Over-time tab rather than the Live tab at daily / weekly / monthly
    granularity (story 37g replaces it with the hourly grid at `H`), so that
    all day-by-day trend analysis is grouped with the other historical
    analytics.
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
65. As a web user, I want the legend filter to survive a granularity change
    and to clear itself automatically when the filtered model is no longer in
    the top five (for example after switching metric), so that the chart never
    renders a stale or empty filter. This applies to the default chart (empty
    model query). A non-empty model query replaces that legend, and story 66b
    governs it instead.
66. As a web user, I want a legend click (stories 60-65) to change only the
    chart, so that the table, the heatmap or hourly grid, and the averages row
    stay on the model set the query already selected. That click is a transient
    chart-reading aid. It is not the section-wide model query: a non-empty
    Filter models query narrows every one of those surfaces together (story
    66e). An empty query still leaves them as the complete record of the range.
66a. As a web user, I want a search beside the Tokens / Cost / Requests metric
    tabs (one centered controls row above the Over-time surfaces, labelled
    Filter models, placeholder Search models, not on the chart card and not in
    the global filter row) whose text defines one model set for
    the whole Over-time section, so that typing a substring such as claude
    charts every matching model as its own series and the same set drives the
    averages, the heatmap or hourly grid, and the history table (story 66e).
    Matching is a case-insensitive substring on the model name, over models
    with non-zero usage for the selected metric in the current range, kept in
    global rank order. An empty query leaves the default chart (the
    top-seven-plus-Other stack and the top-five-plus-Other legend) and leaves
    every other Over-time surface unfiltered. A non-empty query with matches
    stacks every match, with no Other slice and no cap, and the legend lists
    every match. Suggestions in the dropdown are those ranked model names
    only, so the open list previews the charted set. Rank, color, and
    suggestions stay on the unfiltered rows (story 66d).
66b. As a web user, I want a non-empty query that matches nothing, once data
    has loaded, to show an empty chart that says no models match that query in
    this range, so that a miss is never mistaken for all models. The chart
    frame stays, the legend hides, and the query stays as typed. The history
    table body is replaced by the same no-match line and has no Total row. The
    averages strip shows 0 for the selected metric over the same recorded days
    the unfiltered range would have used. The heatmap or hourly grid renders
    all-zero cells for slots that still have coverage, and captions that no
    models match. Nothing clears the query except emptying the field. Clicking
    a legend entry only isolates that one series on the chart until I click it
    again or edit the query, and that isolation is not saved and does not
    change the other surfaces. The legend's Other isolation exists only when
    the query is empty.
66c. As a web user, I want the raw model-query text persisted in local storage
    under botUsageOverTimeModelQuery, one value across metric, granularity,
    and time, so that Over-time reopens on the same set. An empty query
    removes the key. Loading, a metric or range change, and a query that
    currently matches nothing never rewrite or clear the stored text.
66d. As a web user, I want each model's color to depend only on its global
    rank for the current range and metric, so that editing the query never
    repaints a model. Ranks 1 through 7 keep the default stack colors, rank 8
    uses the default Other color, and rank 9 and beyond are neutral base0 with
    a base03 segment stroke. No new hue is invented, and the legend Other
    swatch stays base01. More than eight matches stay separate segments. None
    are folded into Other.
66e. As a web user, I want a non-empty Filter models query to narrow every
    Over-time surface to the same model set, and an empty query to leave them
    unchanged, so that the chart, the averages strip, the Daily heatmap or
    Hourly grid, and the Tokens history table (rows and Total) cannot disagree.
    Matching stays the case-insensitive substring in story 66a. One query
    string drives every surface. Non-matching models are masked, not dropped:
    their tokens, cost, and requests count as zero, while their dates, hours,
    and partial flags stay, so recorded-day counts, unknown dates, today and
    partial exclusions, and hourly missing-versus-zero stay based on coverage
    rather than on which models matched. The history table then lists each
    match as its own row in global rank order, with no Other row and no cap,
    and each column Total is the sum of those rows. The heatmap applies that
    same substring to its own window, including models absent from the current
    Over-time range. An empty query still paints from daily totals. An active
    query reads model-daily for the heatmap window once; editing the query
    does not refetch. Until that read arrives the card shows a loading line and
    no cell values, never the unfiltered daily totals. While a query is active,
    the heatmap or hourly header, the history header, and the averages title
    each say Filtered to models matching "<q>", in plain text and without a new
    color. Rank, color, and suggestions stay on the unfiltered rows. A miss is
    story 66b. A legend click still changes only the chart (story 66). Usage
    Live is outside this filter.

### Controls and state

67. As a web user, I want a free-text time input accepting the shared grammar,
    with independent per-mode values (Live defaults to today, Over-time
    defaults to the current month) persisted across sessions, so that each mode
    remembers its own natural window.
68. As a web user, I want the usage view's mode, view toggle, granularity,
    time inputs, and the Over-time model query (story 66c) persisted in local
    storage, so that the panel reopens the way I left it.
69. As a web user, I want wide ranges ("all", a full year) to return complete
    data rather than silently truncating at a small row limit, so that
    long-window charts are trustworthy.
70. As a web user, I want tokens formatted compactly (K / M / B), costs as
    dollars with cents, and requests as plain numbers, consistently across
    cards, charts, tooltips, and tables, so that numbers are readable at every
    scale.

### Over-time averages (todo 3571)

71. As a web user, I want Avg daily, Avg weekly (x7) and Avg monthly (x30.44)
    summaries of the selected metric on the Over-time chart card, so that I can
    read a typical day's usage without averaging the heatmap by eye.
72. As a web user, I want those figures to be a mean per recorded day (distinct
    dates present in the already-clipped rows after excluding browser-today and
    any date with a server `partial` hour), so that unknown missing dates and
    an in-progress day are never treated as observed zeros.
73. As a web user, I want weekly and monthly values disclosed as the daily rate
    times 7 and 30.4375 for every window, with a `~` when the unit is longer
    than the recorded span, so that I do not read them as calendar-week or
    calendar-month means.
74. As a web user, I want the caption to name the recorded-day count, date
    span, any dates in that span without rows, that recorded days may be
    partial, that ingestion coverage is unknown, and which models the strip
    covers, without hovering, so that I can judge how far the figure may sit
    from a calendar-day mean. An empty query says the strip is all models. A
    non-empty query says it is the models matching that query, using the same
    Filtered to models matching "<q>" line the other filtered surfaces use
    (story 66e). Today-excluded and partial-dates-excluded copy appear only
    when those exclusions actually happened.

### Per-trace usage (todo 3729)

75. As a user, I want `y todo usage <todo_id>` to show every chat that ran on
    that todo's trace, with its skill, bot and tier, so that I can see which
    sessions a piece of work actually took.
76. As a user, I want each chat and the trace as a whole to show turns, inbound
    messages, observed requests and the four token counters, so that I can tell
    a long conversation apart from one that spent heavily.
77. As a user, I want a counter that the transcript did not record to be shown
    as missing rather than as zero, so that an absent number is never mistaken
    for no usage.
78. As a user, I want the report to say when usage was last scanned and what
    that scan could not attribute, so that I can judge how current the numbers
    are.
79. As a user, I want cost shown as unavailable, so that I am not given a dollar
    figure the transcript never recorded.
80. As a user, I want historical completeness reported as unknown, so that a
    scan of the transcripts present at one moment is not read as a complete
    history.

### Session context analysis (todo 3844)

81. As a user, I want to open a Context view from a chat's detail and see that
    chat's requests in order, so that I can follow how its context grew.
82. As a user, I want `y chat context <chat_id>` (with `--json`) to return the
    same analysis the web view shows, so that I can inspect or script it from a
    terminal.
83. As a user, I want each participant row in a trace view to link to that
    chat's Context, so that I can go from an expensive trace to the session
    that made it expensive.
84. As a user, I want each request to show its observed prompt size (uncached
    input + cache creation + cache read) and its growth versus the previous
    request, so that I can spot the turn where the context jumped.
85. As a user, I want each request's context broken down into system prompt,
    rules / memory, skills and references, tool / MCP schemas, tool results
    and conversation history, so that I can see what actually fills it.
86. As a user, I want everything the transcript cannot attribute shown as an
    explicit unknown share, so that the breakdown never pretends to cover 100%
    when it does not.
87. As a user, I want every figure labelled as observed (provider counters),
    estimated (derived sizes or token estimates) or unavailable, so that I
    never read an approximation as a measurement.
88. As a user, I want the session summary to show startup, peak and latest
    prompt size separately from the cumulative input across all requests, so
    that context occupancy and billed volume are not confused.
89. As a user, I want the largest contributors ranked both by size when first
    introduced and by estimated repeated exposure across later requests, so
    that I can tell a big one-off read from a medium item that rode along for
    fifty turns.
90. As a user, I want contributors named by owner-only relative labels (a rules
    file, a skill, a tool, a relative file path), so that I can recognise what
    to trim.
91. As a user, I want repeated identical reads of the same content flagged,
    while genuinely separate reads stay separate occurrences, so that real
    duplication is visible and nothing is double counted.
92. As a user, I want compaction shown as an event that starts a new context
    epoch, so that I do not see pre-compaction history summed into later
    requests.
93. As a user, I want a per-request and per-session input-only cache reuse
    ratio (cache read over prompt size) labelled distinctly from the existing
    Bot Usage cache-hit percentage, so that the two metrics are not mixed up.
94. As a user, I want the ratio disabled when any counter on a request is
    missing, and coverage disclosed on the session aggregate, so that a missing
    counter never skews it.
95. As a user, I want a short list of deterministic suggestions (repeated
    identical read, very large tool result, heavy startup rules or schemas,
    frequent prefix change), worded as correlations rather than guaranteed
    savings, so that I get actionable hints without false promises.
96. As a user, I want cost shown as unavailable in the Context view, so that I
    am not given a price the analysis cannot back.
97. As a user, I want the analysis to appear after a run without waking the VM
    when I open it, so that looking at a chat never costs a VM boot.
98. As a user, I want a chat with no analysis yet, an analysis in progress and
    an analysis that failed or was unsupported to read differently, so that
    "nothing uploaded" is not mistaken for "empty context".
99. As a user, I want to trigger an explicit, bounded backfill over transcripts
    still retained on the VM, so that recent past sessions can be analysed,
    with historical completeness still reported as unknown.
100. As a user, I want the analysis version shown and re-analysis to replace an
     older version's rows for the same request, so that a parser improvement
     never mixes two methods in one view.
101. As a user, I want context detail visible only to me and never on public
     trace or chat shares, so that labels and hashes do not leak.
102. As a user, I want detailed per-request analysis kept for 30 days while
     session totals live longer, so that storage stays bounded without losing
     the session-level picture.

### Account balances

103. As a web user, I want Account balances above Subscription limits in Live,
     with OpenRouter and DeepSeek shown separately, so I can see remaining
     account credit without confusing it with subscription or per-key limits.
104. As a user, I want each balance in its provider-reported currency, with no
     conversion or combined total, so CNY and USD never become one number.
105. As a user, I want a compact amounts-only balance display with provider
     names, separate currency amounts and a placeholder when no amount is
     available, so a missing value never becomes a fabricated zero. Detailed
     freshness, errors and observation times remain API state, not extra UI
     rows or balance retry controls.
106. As a user, I want a provider failure to leave the other provider usable,
     and API keys to remain server-side, so opening Live neither leaks a key
     nor depends on both providers succeeding.

## Implementation Decisions

### Account balances

- **Separate current account status.** The Bot module owns
  `GET /api/module/bot/balances[?refresh=true]`, behind its authenticated
  configured-maintainer gate. It returns OpenRouter then DeepSeek in a
  `providers` envelope. No spend sync, subscription refresh, model turn,
  database write or VM wake is part of this read.
- **Official account semantics.** OpenRouter's
  `GET https://openrouter.ai/api/v1/credits` reports `data.total_credits` and
  `data.total_usage`; remaining USD is `total_credits - total_usage`. The
  per-key `/api/v1/key` allowance (`limit_remaining`) is different and is not
  displayed. DeepSeek's `GET https://api.deepseek.com/user/balance` reports
  `is_available` and `balance_infos` with `currency`, `total_balance`,
  `granted_balance` and `topped_up_balance`. Remaining is `total_balance`,
  which already includes granted and topped-up credit. Never add those
  components again. Preserve each currency row, including real zero, without
  summing providers or currencies or converting them.
- **API-process credentials.** Both official endpoints use Bearer keys from
  `OPENROUTER_API_KEY` and `DEEPSEEK_API_KEY` in the API process environment.
  SAM's optional `OpenRouterApiKey` and `DeepSeekApiKey` parameters have
  `NoEcho: true` and empty defaults, and map only into the API function.
  GitHub deployment reads these variables from its existing `CONFIG` secret;
  manual deployment uses the existing environment / `.env` path. Missing or
  empty keys yield `not_configured` without a network attempt, not a zero
  balance. No key is returned to the browser or included in logs, notes or
  fixtures. Deployment wiring does not provision a missing provider key.
- **Scoped Lambda exception.** These API-key balance reads originate from the
  API Lambda. The stable-source-IP VM requirement applies to Codex/Grok CLI
  subscription reads, not these balance APIs; their existing execution,
  refresh cadence and credential ownership remain unchanged.
- **Bounded reads and cache.** Providers run concurrently with an 8-second
  per-provider timeout and isolated failures. A process-local 60-second TTL
  matches Live's polling cadence; `refresh=true` bypasses it. This is not a
  durable history or shared cross-Lambda cache. A failed read retains that
  process's last successful provider value as `stale` with its original
  `observed_at`; without a previous success it returns `error`. A missing key
  remains `not_configured`, never stale success. Successful values use `ok`.
  Closed error codes are `auth_failed` for 401, `http_error` for other non-2xx,
  `transport_error` for network failures, and `parse_failed` for invalid
  payloads. Never expose raw response bodies or exception text.
- **Compact Live-only display (todos 4151 / 4152).** Account balances precedes
  Subscription limits in the left column, and follows Model share on narrow
  panels. OpenRouter then DeepSeek appear as provider label/amount rows directly
  on the canvas, with a two-column split at 380px section width and hairline
  rows below it. Remaining amounts use `text-base font-semibold tabular-nums`;
  separate currency rows and screen-reader currency names remain. There are no
  used/purchased or granted/topped-up details, observation-time rows, freshness
  badges or balance retry controls. Loading or missing amounts use a placeholder,
  never an invented zero; retained amounts remain displayable without a visible
  stale badge. Detailed state and forced refresh remain API capabilities.
  Polling stays at 60 seconds. Over-time neither mounts nor polls balances.

### Storage

- **Two tables, two grains.** A daily-keyed table holds the durable usage time
  series; a separate hourly-keyed table holds the short-horizon series. Mixing
  grains in one table is the double-count hazard already rejected for the
  lifetime anchor. Token counters use 64-bit integers in both.
- **Daily grain.** Each daily row is unique on `(user, usage_date, source,
  scope_id, model)`; writes are idempotent upserts on that key (the same
  pattern as the finance price table).
- **Hourly grain (todo 3165).** Each hourly row is unique on
  `(user, usage_date, usage_hour, source, scope_id, model)`. The local
  wall-clock pair (DATE + SMALLINT 0–23) is stored rather than a UTC instant so
  `SUM(hourly WHERE usage_date=d)` compares directly to the daily row for `d`
  with no timezone conversion. Asia/Shanghai has no DST, so wall-clock hours
  are unambiguous under the current configured zone.
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
  worker-Lambda action on an hourly cron at minute 50 (so the last local run of
  a day remains 23:50 Asia/Shanghai while also refreshing the current hour); a
  CLI sync command; and an authenticated API sync endpoint used by the web
  refresh button, which returns the sync result envelope so the panel can
  revalidate afterward. Each run pulls daily for today and hourly for
  `[yesterday, today]`; the envelope reports both grains (`crs` and
  `crs-hourly`).
- **Streaming caveat.** The relay records usage for non-streaming
  chat-completions only, and all in-scope bots are non-streaming. If a bot ever
  switches to streaming, the relay's streaming usage parser must be extended
  first or that bot's usage is silently lost.

### Backfill (one-shot)

- **Admin dated window, manual only.** A CLI backfill command logs into the
  relay's admin session with credentials resolved DB-first from the
  `user_preference` key `crs_admin` (same row the direct run-rate path uses),
  falling back to environment or the local `[crs]` config block so one-shot
  local runs still work without a prior `y usage crs-creds set`. It fetches
  per-model per-day stats for each day in `[today - N, yesterday]` (N
  defaulting to the relay's ~32-day daily-bucket retention) and writes rows at
  the same daily aggregate grain as go-forward sync. The admin endpoint has no
  per-key breakdown, so the backfill does not supply `cost_basis`: a newly
  inserted row defaults conservatively to `real`, while an existing row keeps
  the label previously established by go-forward sync. Backfill therefore
  refreshes counters and cost without inferring historical per-model
  attribution from the current key topology or downgrading known attribution.
  Session tokens minted during a backfill are not the durable store; the
  durable admin credential row is the intentional todo-3121 exception (see
  user story 14 and Realtime run rate), not a silent leak into logs.
- **Yesterday cap.** The daily backfill never writes today, so the recurring
  sync owns the in-progress day and the two paths cannot fight.
- **Hourly backfill is the per-key path, capped at 7 days.** Hourly history
  lives only on the per-key counters (TTL ~7 days), not the admin dated window,
  so `y usage backfill --hourly-days N` replays the same go-forward hourly
  endpoint for the last `min(N, 7)` local days including today. Wider requests
  are silently clamped; history older than the TTL is unrecoverable.
- **Lifetime anchor rejected.** A design for storing the relay's all-time
  cumulative total as a sentinel row (distinct scope, epoch date) was cut
  before implementation: a cumulative lump and an additive daily series in one
  table create a standing double-count hazard for every consumer, and the
  dated window covers the actual charting need. History older than the relay's
  retention is acknowledged as unrecoverable.

### Hourly grain decisions (todo 3165)

- **Extend the per-key endpoint, not the admin one.** CRS already writes
  `usage:{keyId}:model:hourly:{model}:{date}:{HH}` with real-cost counters.
  y-agent consumes `POST /apiStats/api/user-model-stats` with `period=hourly`
  and optional `date=YYYY-MM-DD`, reusing the same counters the daily sync
  already consumes. No admin credentials and no second aggregation authority.
  Per-request usage records are never read (the "no sensitive request data"
  requirement).
- **Stored real cost is authoritative (including zero).** CRS must write
  `realCostMicro` / `ratedCostMicro` on both daily and hourly model counters
  whenever a request is recorded, **including when the cost is zero**. The
  reader prefers those stored micro fields for `costs.real` / `costs.rated`.
  The list-price `CostCalculator` fallback (`isLegacy: true`) remains only as a
  compatibility path for Redis rows written before this authority ships; it is
  not the go-forward source of truth. y-agent does **not** persist `isLegacy`
  (or any other legacy marker): post-deploy rows carry stored real cost, and a
  transient `isLegacy` flag on the wire is not a durable grain dimension.
- **Reconciliation acceptance and the legacy-window caveat.** Tokens and
  requests always reconcile across grains because both are incremented from the
  same per-request pipeline. Exact cost reconciliation
  (`SUM(hourly WHERE usage_date=d) == daily(d)` within float display precision)
  is required starting with the **first complete Asia/Shanghai day after the
  zero-cost write authority is deployed**. Days that still contain pre-deploy
  Redis counters may mix stored-micro and list-price fallback rows and are
  **not** the acceptance bar; that legacy window is temporary and ends when
  those Redis keys expire or are overwritten by post-deploy traffic. Sub-task
  14's live check is therefore scoped to a post-deploy complete local day, not
  to the partial overlap window.
- **Separate table, local wall-clock key.** See Storage. Incomplete current
  hour is a server-computed per-row `partial` flag on
  `GET /api/usage/model-hourly`, never a browser-clock decision.
- **One sync, hourly cadence.** Daily and hourly share the minute-50 EventBridge
  schedule and the same CLI/API entry points; the result envelope carries both.
- **Presentation.** The todo 4152 Live layout supersedes todo 3261's full-width
  status rows: run rate is header metadata; at `@min-[720px]`, balances,
  subscription limits and Today by hour sit left of the Model share donut.
  The donut stays on the right even when hourly activity is absent; Models
  spans both columns below. Narrow DOM order is Model share, Account balances,
  Subscription limits, Today by hour, Models. Sections use canvas hairlines,
  not enclosing cards. Over-time gains an `H`
  granularity that fetches `model-hourly` and clamps the range to 7 days; what
  `H` renders below the stacked chart was later superseded by todo 3566 (next
  section). Active-hours analytics and per-key/per-bot hourly attribution stay
  out of scope; todo 3165's broader exclusion of any hourly grid holds except
  for the single surface todo 3566 reopened.

### Seven-day hourly grid decisions (todo 3566)

- **`H` swaps the card, it does not add one.** At `H` granularity the Over-time
  tab mounts an hourly card of seven calendar-date rows by 24 hour columns
  (00-23) *instead of* the daily contribution card, never both. Daily / weekly /
  monthly keep the daily card unchanged, and `H` neither fetches daily totals
  nor mounts the year-window heatmap.
- **One fetch, no synthesis.** The grid consumes the hourly rows the `H`
  granularity already fetches and re-buckets (the `day-6 to day` window resolved
  through `GET /api/usage/range`, with the existing one-date fetch padding).
  Hourly values are never derived from daily rows, and already-converted rows
  are not re-bucketed a second time.
- **Seven local dates including today**, oldest at top and today at bottom, with
  all 168 slots generated from the resolved window rather than from the dates
  that happen to appear in the data.
- **All models, unless a model query is active.** With an empty Filter models
  query the grid sums the selected metric across every returned model, and the
  daily card does the same. The over-time legend's model / "Other" toggles
  still narrow only the stacked chart. A non-empty query masks non-matching
  models' usage to zero and keeps row presence, so a missing hour stays missing
  and a recorded zero stays a recorded zero; the history table follows the same
  query (story 66e). Per-bot and per-key attribution remain excluded.
- **Absence is not zero.** A present row whose summed metric is 0 is a recorded
  zero and keeps the existing filled neutral cell. A slot with no row reads as
  missing (unfilled cell plus a dash), a slot after the current instant reads as
  future (unfilled cell plus a distinct dot), and the in-progress state comes
  only from the server's `partial` flag. The browser clock may distinguish an
  unobserved future slot; it never invents, clears, or overrides `partial`, and
  the grid never claims ingestion failed.
- **Window-derived magnitude scale, per card (todo 3571).** The theme-derived
  neutral-zero/green ramp is shared with the daily card rather than copied. Bin
  boundaries are nice-rounded quintiles of that card's own non-empty cells
  (drop `<= 0`, 0.2/0.4/0.6/0.8 linear quantiles, round each up to `1/2/5 x
  10^k`, keep a candidate only when it opens an occupied bin below the window
  max). Daily and hourly each bin independently and are never on screen
  together; colors are comparable within a card, not across granularity, metric
  or time filter, which is why the legend prints real boundaries and states
  that the scale is relative to this window. This is not share-of-window-max
  normalization: an idle window stays pale when its own distribution is low,
  and a single outlier moves a quantile rather than the whole ramp. The former
  absolute 100M / $100 / 1,000 steps, 5x ceiling and above-ceiling ramp are
  gone. Value 0 keeps the todo-2980 gray and stays out of the quantile domain;
  missing / future / `partial` marks are unchanged.
- **Readable without color.** Title is `Hourly tokens` / `Hourly cost` /
  `Hourly requests`; every hour column and all seven dates are labelled, the
  state legend names recorded zero, missing and future, and focus exposes the
  same full readout as hover on a semantic grid with row and column headers.
- **Compact, not redesigned.** Existing card tokens, rounded cells, quiet gaps
  and the fit-to-panel approach are retained with a wider date gutter; no new
  chart library, palette or dashboard control is introduced.
- **Empty stays a seven-day window.** A successful but empty hourly response
  renders the full 168-slot no-data / future grid (lower content keeps its empty
  state) instead of hiding the view; loading and error states remain distinct
  from it.

### Subscription limit-window status

- **Separate operational dataset; one persisted latest snapshot (revised
  todo 3226), plus a limit-window history (todo 3717).** Subscription limit
  windows are current provider-account status, not spend: they do not share
  the daily per-model table, relay sync, or spend aggregation. The latest
  snapshot still lives in `user_preference` and needs no migration. Todo 3717
  adds a second, append-only history of the same refreshes (see "Limit-window
  history" below) so the latest card and the hourly record answer different
  questions. The original "every read is live, nothing is persisted"
  design was replaced because `GET /api/usage/limits` was consistently one of
  the three slowest y-agent routes (24h baseline p50 3.63s / p95 12.30s / p99
  15.46s, VM/SSH/CLI on every request): a 30-minute worker schedule now
  writes the one latest normalized snapshot per user into the existing
  `user_preference` table (key `usage_limits_latest`, no new table), and an
  ordinary poll reads only that row. The live VM/SSH/CLI path still exists —
  it moved from every poll's request path to the schedule (and to the
  explicit manual retry) — so the underlying reads, their VM execution, and
  their error vocabulary are unchanged; see "Persisted snapshot" below for
  the read/refresh/failure/lock contract this introduced.
- **Two providers, two readers, one envelope (todo 4138).** `codex_usage_api`
  for openai/codex (authenticated GET of the Codex usage endpoint) and
  `xai_billing_credits` for xai (authenticated GET of the xAI CLI's billing
  endpoint, tried in two shapes; see below). The two run concurrently; one
  reader's failure is isolated into the envelope's `errors[]` and cannot take
  the other down. There is no provider-selector flag: callers take the whole
  envelope or nothing. The Claude subscription reader, its on-VM scrape cache,
  and `y claude usage` are removed. `normalize_envelope`, `merge_providers`,
  and `read_snapshot` drop `claude_code` rows and errors whose origin is the
  removed Claude reader, `claude_code`, or `anthropic`. That filter does not
  rewrite the stored preference by itself; the next successful refresh stops
  carrying those rows forward. Stored limit-history rows are not deleted.
- **claude-relay-service is not in this path at all.** The earlier design read
  both providers through a CRS self-service endpoint backed by CRS's Redis
  snapshots. That was removed, not wrapped: CRS's per-key fan-out, its
  passive Codex response-header snapshot, its relay-account scoping, and the
  `no_stable_account_scope` result no longer exist here. The daily **spend**
  sync still runs on CRS and is untouched. CRS remains the meter for relayed
  traffic; it is simply no longer the source of subscription status.
- **Window kinds are per provider, not a fixed pair.** Contract kinds are
  `five_hour`, `one_week`, and `billing_period`. Codex reports its rolling
  rate-limit windows, keyed on each window's own reported duration and
  **never** on primary/secondary position (a live sample returned the one-week
  window as "primary" with the secondary null); xAI reports one
  `billing_period` usage row with the period end as its reset. A row is usable
  when **any** window carries a real percentage. Demanding the 5-hour/1-week
  pair would leave Grok permanently unavailable. The Live card draws Codex's
  weekly window and Grok's billing-period window; Codex's 5-hour window stays
  in the payload. Model-specific extra windows are not collected or served. A
  provider-specific `extra` map (xAI's `used`/`monthlyLimit`, prepaid balance,
  on-demand cap/used, unified-billing flag) may still ride on the window.
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
- **Execution on the VM, not in Lambda.** Both provider HTTP reads live
  in `y usage limits [--json] [--refresh]`, which runs on the user's VM. Two
  callers SSH-exec it and normalize the returned envelope: the 30-minute
  worker schedule (`refresh_and_persist_snapshot`, unforced) and
  `GET /api/usage/limits?refresh=true` (the same function, forced). The
  reason for VM execution is source IP: shared cloud egress already drew a
  rate-limit response from one vendor on an unauthenticated probe and another
  vendor is Cloudflare-fronted, while the VM's address is stable and already
  known to both. The CLI emits exactly the envelope shape the normalizer
  consumes, so the envelope *is* the boundary contract, pinned from both
  sides.
- **Layering: transport in `agent`, normalization and the persisted snapshot
  in `storage`.** SSH orchestration, the per-user refresh lock, and the
  VM-asleep guard live in `agent.usage_limits`; `storage.service.model_usage_
  limits` keeps normalization (`normalize_envelope(raw, ttl_seconds,
  origin)`, dict in, dict out, no transport vocabulary) plus the snapshot's
  read/merge/persist functions (`read_snapshot`, `record_refresh_success`,
  `record_refresh_failure`, `merge_providers`), all pure functions over a
  `user_preference` row with no transport vocabulary either. Putting the SSH
  call in `storage` was infeasible rather than merely inelegant: `storage`
  declares no dependency on `agent`, the dependency runs the other way, and
  CI resolves each package's environment separately, so a `storage` import of
  `agent` would fail its own test job.
- **Error vocabulary is a closed set of codes, never free text.** The CLI's
  provider-level codes are exactly `not_logged_in`, `reauth_required`,
  `parse_failed`, `transport_error`. The backend wrapper adds transport-level
  codes `vm_unreachable`, `cli_failed`, `bad_payload`, plus `malformed_item` at
  envelope level, and the persisted snapshot adds two more: the startup-only
  `snapshot_unavailable` (todo 3226: no successful refresh has completed for
  this user yet) and `no_usage_vm` (this user owns no VM config, so there is
  nowhere to run the read; see "Refresh is owner-scoped" below). Availability
  is `available`, `unavailable`, or `reauth_required`. Raw exception text
  (which can carry a private IP or hostname) reaches logs only, never a
  caller-visible field, and the web maps every code to human copy with a
  generic fallback for anything unmapped.
- **Malformed data is never a number.** Missing, non-numeric, NaN, or infinite
  percentages normalize to null and render as unavailable; an unrecognized
  provider response shape becomes `parse_failed`. A vendor changing its schema
  must produce a dark card, never a fabricated 0%.
- **Degradation rules.** Any non-`available` availability collapses to
  `unavailable` freshness. A stopped EC2 instance answers `vm_unreachable`
  immediately and is never started to serve a refresh; the last good snapshot
  is returned intact on the next successful read. Within one attempt, a
  per-provider row whose *read* failed this run (CLI codes `parse_failed` /
  `transport_error`) falls back to that backend's previous persisted row
  rather than blanking it — see "Persisted snapshot" below for exactly which
  codes fall back versus overwrite, and why a durable state like
  `reauth_required` must always overwrite.
- **Persisted snapshot: refresh cadence, locking, staleness, and startup
  (todo 3226).** One normalized snapshot per user lives in `user_preference`
  key `usage_limits_latest`: `providers` (merged per backend), the latest
  attempt's `errors[]`, and `last_attempt_at` / `last_success_at` /
  `last_attempt_status` / `last_attempt_error`. A worker schedule calls
  `agent.usage_limits.refresh_and_persist_snapshot` every 30 minutes for
  every *eligible* user (see "Refresh is owner-scoped" below); `?refresh=true`
  calls the identical function, forced, so the schedule and a manual retry
  share exactly one refresh path rather than two implementations that could
  drift. Each call first acquires a per-user pipeline lock
  (`refresh_usage_limits:<user_id>`); if the lock is already
  held (the schedule still running, or a concurrent manual retry), the
  schedule simply skips that user for this tick and a manual request returns
  the stored snapshot immediately with `refresh_in_progress: true` rather
  than queuing a second overlapping CLI run. A **failed** attempt (VM asleep,
  SSH/CLI error, or a structurally invalid payload) only updates
  `last_attempt_at` / `last_attempt_status` / `last_attempt_error` and never
  discards the last successful `providers`; a **successful** attempt (a
  structurally valid envelope, even one carrying isolated per-provider
  errors) merges its providers with the previous snapshot one backend at a
  time (`merge_providers`): a backend whose read failed *this* attempt keeps
  its previous row, while a durable provider-reported state (`reauth_required`
  / `not_logged_in`) or a normal available reading always overwrites, so a
  real re-auth requirement can never be hidden behind stale good data
  indefinitely. A backend **absent from the new attempt entirely** also keeps
  its previous row unchanged (there is nothing new to overwrite it with).
  `observed_at` is never restamped; freshness is instead
  **recomputed on every read** from each row's own `observed_at` against a
  ten-minute read TTL (`READ_FRESH_SECONDS`, now narrower than the
  30-minute cadence, so a successful snapshot deliberately reads `stale`
  between refreshes and `observed_at` is never restamped). Before the first
  successful refresh for a user, reads
  return a bounded `{"providers": [], "errors": [{"origin": "snapshot",
  "error": "snapshot_unavailable"}]}` envelope — startup is fail-fast and
  never wakes or probes the VM from an ordinary poll.
- **Refresh cadence is 30 minutes so the sweep cannot keep the VM awake
  (todo 3564).** Each awake refresh still opens two short SSH sessions and
  renews `/tmp/ec2-ssh-last-seen`. The host idle threshold is 900s, so the
  original 5-minute cadence (todo 3226) never let `auto-hibernate.sh`
  fire. The schedule is now `rate(30 minutes)` / `_SCHEDULE_INTERVAL_SECONDS
  = 1800`, strictly longer than that threshold. An asleep VM still records
  `vm_unreachable` and is not woken. Under an isolated idle window the
  awake tail after the last genuine activity is typically 15-30 minutes;
  scheduler jitter, a stalled process, or other SSH work can stretch that
  tail, and the remaining sub-second probe race is not closed. Once asleep
  the VM stays asleep until a genuine interactive wake. Freshness
  consequence: `READ_FRESH_SECONDS` stays 600, so provider rows read `fresh`
  for 10 minutes after each refresh and `stale` for the other 20, and they
  read `stale` with a `vm_unreachable` attempt error while the VM sleeps.
- **No subscription quota gate (todo 4138).** `record_refresh_success` does
  not read or write any bot's enabled bit. The old 95% gate on the named
  `fable` bot is removed. That bit stays at whatever value it already has
  (manual enable and disable still work). There is no replacement gate and no
  automatic enable. Routing still observes `enabled` through
  `agent.config._universe`. Alias dereference and the global-default fallback
  still do not re-check the final target's enabled bit; that boundary stays
  in [`bot-routing.md`](bot-routing.md).
- **Limit-window history (todo 3717).** The 30-minute sweep and a manual
  `?refresh=true` already share `refresh_and_persist_snapshot`. That function
  now also writes history, after the snapshot write, and a
  history failure only logs a warning: the returned snapshot is unchanged.
  Cadence stays "every 30 minutes while the VM is awake, plus manual
  refreshes". The hour is the query grain, not a promise that a collection
  happened. A lock-skipped call is not an attempt and is not recorded.
  Two tables: `model_usage_limit_attempt` (one row per attempt, with the
  local date and hour of `attempted_at`) and `model_usage_limit_observation`
  (one row per window, cascading on attempt delete). A failed attempt
  (`vm_unreachable`, `no_usage_vm`, `cli_failed`, `bad_payload`, or a
  providers-less envelope) writes the attempt only. A successful attempt
  records the incoming normalized envelope, never the merged-snapshot
  fallback. Each non-null window is a row (`five_hour`, `one_week`,
  `billing_period`); a provider that reports an error or no
  windows gets one provider-level row with an empty `window_key`; an expected
  backend absent from the envelope gets `state=missing`, with its error taken
  from `errors[]` by origin. NaN, bool, and non-numeric percents are stored
  NULL. `attempted_at` (collection) and `observed_at` (source) are never
  substituted. Freshness is derived at read. `attempted_at` is the attempt's
  start. 60 seconds is an allowance chosen above the sweep's 45-second
  per-user cap and the 30-second CLI timeout. It is not a measured completion
  time and not a bound on a manual retry, whose probe and SSH connect run
  outside the CLI timeout. A source time past the allowance is labelled
  `future`. A slow manual attempt therefore reads `future`, never falsely
  `fresh`. A null source time is `unknown`, an age within 300 seconds is
  `fresh`, otherwise
  `stale`, and any state other than `available` is `unavailable`. This
  describes the source against the attempt stamp, not how fresh the row is
  now.
  `attempt_id` is a full uuid minted once per attempt (a 6-character id
  collides often enough, across all users, that a real attempt would be
  dropped as a replay). The attempt plus its observations commit in one
  transaction. A replay is detected by an empty `RETURNING`, not by
  `rowcount`, which psycopg reports as -1 for `ON CONFLICT DO NOTHING`; the
  observations are then not written, so they cannot attach to the attempt
  that already owns the id. History is not written when the snapshot write
  itself raises, or when the sweep cancels the attempt before it returns.
  Two attempts that captured the same source reading are both kept, and the
  read reports them as one `distinct_observations`. Reset identity is the
  exact `reset_at`; a null reset is its own group and is never merged with a
  known reset or inferred from the window length, so a reset inside an hour
  yields two entries and the pre-reset peak survives in `max_used_percent`.
  A null reset is never inferred, so `max_used_percent` for a null-reset
  group is only an upper bound across whatever resets the source did not
  report.
  Two different `reset_at` values are kept apart rather than fuzzy-merged. Codex
  `plan_type` and `rate_limit.limit_reached` are account-wide: they are copied
  onto every Codex row of that attempt and never read as a per-window fact.
  `rate_limit.allowed` is a different field and is not stored. xAI
  leaves both NULL. The public Codex payload model
  (`RateLimitStatusPayload` / `RateLimitStatusDetails` in
  openai/codex `codex-rs/codex-backend-openapi-models`, read 2026-09-28)
  defines both fields; no authenticated response was probed, so a live body
  that diverges stays NULL rather than being guessed.
- **Refresh is owner-scoped, and the sweep is bounded (todo 3226 defect
  fix).** A subscription-limit read reports the provider logins of whatever
  machine it runs on, so it runs only on the user's *own* `default` VM config
  (`agent.usage_limits.resolve_usage_vm_config`), never on the global default
  user's VM that `agent.config.resolve_vm_config` would otherwise inherit for
  interactive dispatch; a user with no config of their own answers
  `no_usage_vm` immediately instead of reading someone else's subscription
  status. The schedule's eligible set is exactly the owners of such a config
  (`list_refresh_user_ids`, one query). This replaced a serial walk over every
  active user, which in production spent ~15s per user on an SSH connect
  timeout against the inherited dead host, never reached the one real user
  (position 111 of 124) inside the 900s Lambda timeout, and therefore left
  overlapping 5-minute invocations that advanced no snapshot at all
  (diagnosis: `pages/plan-3226-usage-limits-refresh-production-defect.md`).
  Execution is bounded on three axes so one slow user can never starve another
  and invocations can never accumulate: eligible users are attempted
  concurrently up to a fixed ceiling, each attempt is capped well above the
  CLI's own 30s timeout, and no attempt starts once less than one such cap
  remains of the attempt budget, which together with the eligibility and
  overhead allowances sits inside the run budget, which sits inside the
  30-minute cadence.
- **What the sweep does and does not guarantee about coverage (todo 3226).**
  One run attempts *every* eligible user within the schedule interval as long
  as the eligible set fits one run's guaranteed capacity — concurrency ceiling
  × the number of full per-user caps that fit in the **attempt budget** (32
  today, against two eligible users in production) — and that floor holds even
  in the worst case where every attempt burns its whole cap. The attempt
  budget is deliberately not the whole run budget: the eligibility allowance
  and a conservative overhead allowance are charged up front, and the attempt
  deadline is established after the eligibility query returns, so the
  *handler's* total stays inside the run budget however long that query
  actually took. Above that capacity
  there is deliberately **no** same-interval guarantee: the run attempts as
  many users as fit, reports the remainder with the `deadline` outcome, and
  logs a warning that the guarantee no longer holds; the per-tick rotation of
  the starting offset then makes coverage merely *eventual* (about
  `ceil(N / capacity)` ticks). That regime is a signal to raise the capacity,
  not a mode the sweep is designed to run in.
- **The wall-clock bounds only hold because nothing blocks the event loop
  (todo 3226).** `asyncio.wait_for` can cancel an attempt only when control
  returns to the loop, so every synchronous dependency on the refresh path —
  the owner lookup, the pipeline-lock acquire/release, the EC2 state probe,
  snapshot persistence, `ssh_exec`'s own wake/touch prelude, and the sweep's
  eligibility query — is dispatched to a thread, and the eligibility query
  carries its own timeout because it runs before any per-user bound exists.
  Otherwise a single stalled dependency would freeze every concurrent attempt
  *and* the run deadline, and could reproduce the same 900s Lambda timeout by
  a different route. The dispatch target is a module-owned executor, never
  `asyncio.to_thread` / the loop's default one: `asyncio.run`'s teardown
  awaits `loop.shutdown_default_executor()`, so a default-executor thread
  would put its full runtime straight back onto the scheduled handler and
  could hold the invocation to the 900s Lambda limit while the sweep reported
  a tidy timeout.
- **An executor is event-loop isolation, never a bound; the bound belongs to
  each operation (todo 3226, review round 3).** A running thread cannot be
  cancelled: a call whose awaiter timed out keeps going, still holding a
  pooled DB connection and its transaction, an already-acquired lock, or a
  socket, and a graceful interpreter exit still joins it
  (`concurrent.futures.thread` joins non-daemon workers at exit; only killing
  the process outright reclaims them). So the sweep does not rely on the pool for
  liveness. Every operation those threads run ends by itself: libpq
  `connect_timeout`, TCP keepalives and a bounded pool checkout in
  `storage.database.base`, plus a `statement_timeout` the refresh path opts
  into per call; botocore connect/read timeouts and capped retries in
  `agent.ec2_wake`; paramiko connect/banner/auth and channel timeouts in
  `ssh_exec`, whose client is force-closed both on its own timeout and when
  its caller is cancelled. Every one of those bounds is well under one
  schedule interval, so abandoned work drains between ticks instead of
  accumulating across warm invocations. Waking a stopped instance is the one
  operation with a much longer envelope, and it is deliberately left that way
  for the interactive paths that need a cold boot to succeed: the sweep never
  enters it, answering `vm_unreachable` on the sleep check instead.
- **Statement duration is bounded per workload, not per engine (todo 3226,
  review round 4).** The refresh path's DB calls run in threads nothing can
  cancel, so they opt into `storage.database.base.statement_timeout`, which
  applies `SET LOCAL statement_timeout` as each transaction begins: it
  reverts at commit/rollback, so it can never leak to the next user of a
  pooled connection, and it is re-applied per transaction, so a caller that
  commits mid-session stays bounded. It is scoped to the caller's context
  (the executor thread), and the claim it encodes is about these statements
  only — single-row reads and writes keyed by user plus one indexed
  eligibility query. It is deliberately *not* an engine-wide setting: that
  would also cancel valid long work elsewhere (bulk writes, rollup window
  replacement, `init_tables` DDL, a transaction waiting on a row lock), which
  nothing here has measured. The engine-wide settings are limited to the two
  that cannot cancel healthy work: `connect_timeout` and TCP keepalives. Two executors, not one:
  the usage-limit bookkeeping pool is separate from `ssh_exec`'s, so a stuck
  SSH session and the scheduled sweep's DB work cannot starve each other.
  Callers therefore do not need a timeout of their own for the pools to stay
  healthy, and none is claimed for them.
- **Lock release is shielded and bounded (todo 3226).** Shielded so a
  cancelled attempt still releases the user's lock instead of leaving it held
  for the full TTL; bounded so the cancellation path cannot itself hold the
  attempt (and the run) open — the per-user bound has to survive a slow
  release, not depend on it. If that bound fires, the release is abandoned
  and the lock's TTL, which is shorter than one schedule interval, is the
  backstop.
- **Sweep observability is bounded reason codes, never payloads (todo 3226).**
  Each attempted user emits one log line with a closed outcome code — `ok`,
  `partial` (attempt succeeded but a provider read failed), `failed`,
  `locked`, `timeout`, `deadline`, `error` — plus a reason and a duration;
  each run emits one completion summary with the eligible count, the run's
  guaranteed capacity, and the per-outcome tally. The reason is validated
  against the closed error vocabulary above (`ERROR_CODES`) at the logging
  boundary rather than trusted: a snapshot's error strings arrive through
  `normalize_envelope`, which copies the VM CLI's `errors[]` entries
  unchanged, so anything unrecognized collapses to the single code
  `unrecognized`. The scheduled per-user path logs no exception text at all
  (the layer that raised keeps its own diagnostics), so no credential or
  payload can reach an operational line. The run summary is what
  distinguishes "no eligible users" from "reached everyone" from "ran out of
  budget" from "the eligibility query itself timed out".
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
- **Direct Relay proxy (todo 3121 revision).** `GET /api/usage/rate` and
  `y usage rate [--json]` both call the shared
  `storage.service.usage_rate.read_rate(user_id)`, which resolves admin
  credentials (DB-first `user_preference` key `crs_admin`, then env / `[crs]`
  config.toml), reuses a cached admin session token (23h conservative TTL,
  re-login on expiry or on a dashboard 401 with one retry), and
  `GET`s the Relay admin dashboard with ~5s timeouts. Parsing lives only in
  `usage_rate.parse_dashboard`. There is no VM, no SSH, no cron, and no
  stored rate snapshot on the request path. Credential bootstrap is
  `y usage crs-creds set` (copies env/`[crs]` into the DB row without taking
  the secret on argv) and `y usage crs-creds show` (username + `password: set`,
  never the secret or token). Origin stays derived from `bot_config` via
  `_crs_origin()` rather than being copied into the credential row.
- **Closed error envelope.** The public envelope is still
  `{rpm, tpm, window_minutes, is_historical, observed_at, error}`. Error codes
  are `{not_configured, auth_failed, transport_error, parse_failed}`. The
  precompute-era codes (`vm_unreachable`, `cli_failed`, `bad_payload`) and the
  `stale` marker are gone: every response is either a fresh reading or an
  explicit error. A historical CRS fallback (`is_historical: true`, including
  a zero-minute source window) remains unavailable rather than a live rate.
  Malformed source fields are null with a closed error code, never fabricated
  as zero. The UI's 60-second, visibility-gated poll shares the existing
  Usage limits cadence.
- **Latency path (why direct proxy).** The original design (SSH-exec
  `y usage rate --json` per request) measured **3.05 / 3.31 / 3.46s**
  server-side. A first 3121 attempt precomputed on the VM into
  `user_preference` (`usage_rate_latest`) and served a DB read; that shipped
  and is being retired by this revision because Roy approved storing the
  Relay admin credentials in the database so the API can call Relay
  directly. Projected direct-proxy cost from co-region measurements:
  auth + one preference read + one authed dashboard GET ≈ **0.3–0.4s** with
  a cached token, ≈ 0.6s on the request that has to log in first. Losing
  graceful degradation (no last-good `stale` badge on CRS failure) is the
  accepted tradeoff for deleting the storage path. See
  `pages/plan-3121-usage-rate-latency.md` for the measured segments and the
  ship/tear-down order (cron off → merge → `y usage crs-creds set` → deploy
  → measure → drop orphaned `usage_rate_latest` rows → bot module publish).

### Provider credential lifecycle

- **The vendor's own credential file is the single source of truth.**
  `~/.codex/auth.json` (openai) and `~/.grok/auth.json` (xai) are read directly
  and live. y-agent keeps **no credential store of its own** and has **no login
  command**: `y usage login` and `$Y_AGENT_HOME/.credentials/provider-usage.json`
  were built, shipped once, and then deliberately deleted.
- **No Anthropic subscription credential.** Subscription-limit refresh does
  not read Anthropic, does not scrape a CLI view, and does not store or
  refresh an Anthropic grant. Claude API spend stays on the relay.
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
- **Re-auth is always a vendor action.** `codex login` or `grok login`,
  which is exactly what the `reauth_required` card names.
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
  An empty Over-time model query still paints from this endpoint. A non-empty
  query does not: the client reads model-daily for the same window and sums
  only the matching models (story 66e). The endpoint itself stays an all-model
  total.
- **Resolved window labels (todo 3580).** `GET /api/usage/range` is an additive
  superset of `{from_date, to_date}`: it also returns `input` and `recognized`
  from host `describe_time_range`. A malformed literal date (`2026-13-45`) that
  used to 500 is now 200 with `recognized=false` and null bounds. The Usage
  filter label reads this payload; the heatmap card has its own label from
  `heatmapWindowBounds`, because that window ignores the grammar except for a
  bare year. Zone attribution stays tooltip-only next to the existing
  `displayTz` chip. The todo 3346 browser-zone contract is unchanged: relative
  tokens still resolve in the browser timezone the client sends as `tz`.
- **Generous default limit.** The default row limit is high (100k) so wide
  ranges never truncate; per-model daily rows are small enough that this is
  safe.
- **Latest limit status.** A provider-neutral, authenticated endpoint
  (`GET /api/usage/limits[?refresh=true]`) reads the persisted latest snapshot.
  The VM CLI read happens only on the 30-minute sweep and on `?refresh=true`.
  The response normalizes each provider entry (used/remaining percent,
  absolute reset time, observation time, availability, freshness) and selects
  one deterministic best candidate per backend. A single reader's failure is
  isolated into a per-origin error list rather than failing the whole read.
  Responses omit internal integer ids and never fabricate a current value after
  a failed read: missing or malformed data stays null and visibly unavailable.
- **Reset times come from the provider payload.** Codex and Grok supply
  `reset_at` on the window. The old Claude overlay text parser is gone
  (todo 4138). An unparseable reset stays null.
- **Limit-window history (todo 3717).** `GET /api/usage/limit-history` and
  `y usage limit-history` return the same bounded read: every local hour in
  an inclusive range of at most 31 days, up to the current hour, including
  hours with no evidence, plus that hour's provider token, request, and cost
  sums from `model_usage_hourly`. An optional `backend` narrows the entries
  only. Attempt counts and the spend sums stay for the whole hour, so a
  filtered read still shows whether the hour was probed and what it cost.
  A wider range, a reversed range, an
  unbounded `time` token, or a range holding more than 60,000 observations or
  60,000 attempts is a 422 / CLI error (`range_too_large`), never a silently
  truncated payload. The spend side is joined in full too: the hourly
  listing defaults to 1,000 rows, so the history read counts first and asks
  for at least that many. `cost_basis` is returned with the cost, because
  that figure is the stored API-equivalent cost and not measured subscription
  spend. No internal integer id is returned. There is no web view.

### Web views

- **Placement.** Usage lives on the bot page as a second view next to the bot
  config table, since models and bots are adjacent concepts, with a Live |
  Over-time mode toggle inside it. Presentation is per model, never per bot:
  bot-to-model is a lossy many-to-one free-text match and per-bot rows would
  duplicate shared-model usage. The expanded bot detail card may show the
  matching model's usage, clearly labeled as model-level.
- **Limit status placement (todo 4152).** Subscription limits follows Account
  balances in Live, before Today by hour in the wide left column; Model share
  stays right. Narrow panels put Model share first, then balances and limits.
  Limits is not rendered or fetched for Over-time, which remains a
  historical-spend-only view. GPT (Codex) and Grok each use two lines: provider
  name, freshness dot, muted `1 week` or `Billing period`, and right-aligned
  percent used; then a 4px track and full, untruncated reset text. Provider
  letter chips are removed. The fill is `base0` below 60%, yellow at 60%,
  orange at 80%; `limit reached` and `not reported` states remain. The row does
  not draw Codex's 5-hour window. There is no Claude subscription row. A
  provider that reports no drawn window uses a dedicated "no windows reported"
  state rather than empty rows. A
  `reauth_required` provider renders an actionable card naming the vendor login
  to re-run, distinct from plain unavailable and from `vm_unreachable`. Cards
  are classified from stable `backend`/`provider` identifiers, never from
  display text. Provider failures are isolated, the envelope's error list shows
  as a partial-read badge, and the limit refresh control is visually and
  behaviorally separate from spend refresh.
- **Live visual roles (todo 4152).** Follow D10–D15 in
  [Design Language](design-language.md): one canvas, hairline sections with 16px
  gaps and 12px top padding, `text-xs font-medium uppercase tracking-wide`
  section titles, 11px metadata, `text-xs` rows, `.y-field text-sm` input, and
  `text-base font-semibold tabular-nums` balance amounts and donut totals.
  Config/usage/provider use underline tabs; Live/Over-time uses a quiet track
  switch. Run rate is a Live-only dot plus `live`, RPM and TPM, with neutral
  loading/unavailable states and the existing explanatory title. Date or
  resolved range and timezone share a metadata line beside it on wide panels
  and below controls on narrow panels. No decorative LIVE badge remains.
  Model share's quiet Tokens/Cost/Requests toggle sits in its section header;
  the 190px donut uses outer/inner radii 78/60, 9px center keys and an 11px
  wrapping legend. Chart ticks remain 10px. Shared `modelColors()` order is
  blue, cyan, violet, magenta, orange, green, yellow, red for both donut and
  Over-time, with unchanged data and tooltips. Existing Solarized separation
  limitations remain; labels and the table supplement color identity.
- **Models table (todo 4152).** Keep the hand-rolled table and caller-owned
  sorting, five-row scroll, sticky header and total. Headers are 11px,
  keyboard-reachable with `aria-sort`; rows use `text-xs` and numeric columns
  align right with tabular figures. The section header names the active sort.
  Model / % / Tokens / Cost remain visible at every width; Requests / Sessions /
  Turns / Avg / Input / Output appear at 560px; Cache (cr/rd) / Cache Hit appear
  at 700px (container widths). Total cells mirror those reveals. This reuses
  `@y/design` table semantics without adopting its smaller default type scale.
  The shared quiet metric toggle also applies to Over-time, but todo 4146's
  `data-overtime-controls` row, Filter models placement and filtering behavior
  stay unchanged. Provider filtering, polling, limit retention and retry from
  todo 4138 and amounts-only balances from todo 4151 remain intact. The host
  shell, host CSS and other modules are not restyled.
- **Display timezone: ingestion stamps Shanghai, Over-time reads the browser
  zone (todo 3346, shipped).** Storage and the API keep stamping rows in the
  configured `Y_AGENT_TIMEZONE` (`Asia/Shanghai`) as story 8 requires; that is a
  write-path fact, not a display rule. On the client, Live "today by hour",
  the Over-time chart and table, the contribution card and the todo 3566 hourly
  grid all label and bucket in `browserTimeZone()`: hourly rows are reinterpreted
  as instants and re-bucketed into browser days (and browser hours), while a
  Shanghai date with no hourly coverage falls back to its daily row under its own
  label, so every date is sourced from exactly one grain and the boundary between
  the two carries a `mixed` marker. Range bounds for that re-bucketing are
  resolved server-side through `GET /api/usage/range?time=&tz=`, and the panel's
  zone label follows the browser zone; the stored-bucket zone is surfaced only on
  the Shanghai-labelled fallback days. For the user's own browser in Hangzhou
  both zones resolve to `Asia/Shanghai`, so the rule is visible only from another
  zone: it exists so one panel never mixes two calendars.
- **Metric selector.** One metric at a time (Tokens default, Cost, Requests),
  shared by the donut, heatmap, over-time chart, and tables' default sort.
  Tokens means total tokens including cache.
- **Top-N convention: two folds that coexist.** The *series* fold is top seven
  models by the selected metric over the range, descending, remainder into
  "Other". The donut and the Live table always use it. The over-time stack
  and the over-time table use it while the model query is empty, so those
  chart and table totals reconcile on that fold. A non-empty query leaves the
  fold for Over-time only: that chart and table then reconcile on the matched
  set instead (story 66e). The Live surfaces do not. The over-time **legend**
  applies a second, coarser top-five-plus-Other fold *on top of* that same
  seven-element array. Both conventions are live and neither replaces the other, because they
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
- **A legend click does not filter the table.** The legend click is scoped to
  the chart. While it is the only active narrowing, the per-model-by-period
  table still shows every model of the current query (every model, when the
  query is empty). This is what the original chart-filter todo asked for, and
  it keeps a legend click a reading aid. The Filter models query is a different
  control and does narrow the table, the averages, and the heatmap or hourly
  grid together (story 66e). Extending the legend click itself to those
  surfaces stays out of scope until asked for.
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
  reveal driven by container (panel) width, not viewport width. The activity
  columns follow Requests as compact `Sessions`, `Turns`, and `Avg requests`
  headers with reduced horizontal padding so Cache Hit remains readable. They
  carry no partial-coverage asterisks. Loading, unavailable, and partial states
  appear in the shared tooltip and in a status line only while one of those
  states applies; there is no permanent total-scope caption.
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
  month's first day, Mon/Wed/Fri gutter labels, hover tooltip with date and
  exact metric value. The sequential Solarized-green scale (todo 3571) bins
  each rendered card independently: nice-rounded quintiles of that window's
  non-empty cells, every legend swatch occupied, no share-of-window-max
  renormalization, no absolute 100M / $100 / 1,000 steps and no above-ceiling
  ramp. The legend is mandatory because colors are only comparable within the
  card: `0`, one `<=b` swatch per kept bound, an open `>b_last` swatch, a quiet
  `max` readout, and visible copy that the scale is relative to this window.
  Endpoints remain Roy's two greens (`#7bd992` / `#126329`); mode still picks
  the gradient direction; the todo-2980 zero gray is unchanged. Fewer than four
  interior bounds is a normal outcome when the data lacks contrast. The grid
  scales to the panel width (never scrolls horizontally; scales up to a cap on
  wide panels) with the wrapper height set explicitly since CSS transforms do
  not shrink layout boxes. The Daily tokens widget belongs in the Over-time
  tab, alongside the stacked chart and period table; it is absent from Live
  and is replaced by the hourly grid at `H`.
- **Over-time.** Client-side bucketing of the fetched daily rows into daily /
  weekly (Monday-start) / monthly periods; stacked chart plus a
  model-by-period table with a range-sum column and a totals row; the table
  opens scrolled to the most recent columns and re-applies that scroll on
  metric switch; monthly period headers show the full year. Chart helpers
  (palette, period labels, tooltip) are small local copies rather than a
  refactor of the finance viewer; extracting a shared chart library is an
  acknowledged follow-up.
- **Over-time averages (todo 3571).** A compact strip inside the existing
  Over-time chart card, between the title row and the stacked chart: Avg daily,
  Avg weekly (x7), Avg monthly (x30.44). Daily is `total / recordedDays` for
  the selected metric. An empty query sums all models. A non-empty query sums
  only the matched models over those same recorded days, so a query that
  matches nothing reads 0 without shrinking the recorded-day count (story
  66e). Weekly and monthly are that same rate times 7 and 30.4375 (`365.25 / 12`,
  an adopted convention). They are
  normalized estimates, not observed calendar-week or calendar-month means, and
  the multiplier is disclosed for every window. `recordedDays` is distinct
  `usage_date` values in the already range-clipped rows after two
  evidence-based exclusions: the browser-tz current date, and any date holding
  a server `partial` hourly row. Dates without rows are unknown, never scored
  as zero; when the remaining recorded dates do not fill their own calendar
  span the caption shows the gap count. Zone-offset mismatch is not treated as
  truncation. The visible caption always carries `mean per recorded day`, the
  recorded-day count, the span, `recorded days may be partial`, `ingestion
  coverage unknown`, and either `all models` (empty query) or `Filtered to
  models matching "<q>"` (active query); `today excluded` / `partial dates
  excluded` and the gap count appear only when true. A unit longer than the
  recorded span is prefixed `~`. Zero recorded days render `-` with `needs one
  recorded day`. The chart legend click does not apply. The model query does.
  D / W / M print the
  same numbers on one `requestedTime`; H must not, because it clamps to
  `day-6 to day` and has no daily fallback.
- **State persistence.** View toggle, mode, granularity, and the two
  independent time inputs (Live and Over-time) persist in local storage under
  stable keys; renames keep old key strings so persisted values survive.
- **Formatting.** Tokens compact to one decimal K / M / B above a thousand;
  cost as dollars with two decimals; requests as locale-formatted integers;
  tabular numerals everywhere.

### Chat session and answered-turn activity (todo 3569)

- **Two sources stay explicit.** Sessions and Turns come from persisted y-agent
  chat messages. Requests comes from relay usage and can include many model
  calls inside one answered turn, retries, internal calls, and traffic with no
  y-agent chat attribution. `Avg requests` is therefore a descriptive
  model/period aggregate ratio (`relay Requests / attributed Turns`), not exact
  matched API requests for an individual prompt.
- **Activity output clock and ratio boundary.** A session is one distinct chat
  with at least one attributed assistant message from the model in the selected
  local-date period. A pending prompt group opens on the first user message
  after the previous attributed answer and stays open across later user
  messages, tool results, and unattributed assistant messages; the first later
  attributed assistant response closes it and assigns one turn to that
  response's local date and model. A steer that receives its own attributed
  output opens another turn. A trailing unanswered prompt does not count yet.
  Sessions and Turns use the assistant output clock and host `Y_AGENT_TIMEZONE`
  buckets. In the default live-today view, Requests can be rebuilt from
  browser-timezone hourly rows, so
  the two sides of `Avg requests` use identical day boundaries only when the
  browser timezone equals `Y_AGENT_TIMEZONE` (the normal configured case).
- **Multi-model and zero-turn facts are intentional.** A re-botted chat counts
  once in every model row where it produced output, while the Total row counts
  distinct chats across all models, so row sessions need not sum to the total.
  A model that continues producing output on a later date without a new prompt
  contributes a session with zero turns on that date.
- **Attribution is explicit.** Empty model ids and Claude Code's `<synthetic>`
  placeholder are skipped and do not close a pending prompt group. The relay
  records spend under the upstream response model, while the chat client echoes
  the request model, so two chat ids are stored under the relay usage id:
  `grok-4.6` as `grok-4.6-build` and `grok-4.7` as `grok-4.7-build` (todo 3662).
  Already-suffixed ids and every other id pass through unchanged; there is no
  generic suffix rule. Delivery is this y-agent host, not the bot module.
  Relay-only models with no attributed y-agent output correctly read as
  zero sessions and zero Turns, with `Avg requests` unavailable (`-`) because
  its denominator is zero. If the activity request itself is unavailable, all
  three activity cells render `-` rather than fabricated zeros.
- **Persisted fact and aggregation contract.** Host-owned
  `chat_model_activity` stores `(user_id, chat_id, usage_date, model, turns)`
  with one unique row per tuple. Recompute replaces one chat's derived facts in
  one transaction; each incremental pass replaces every changed chat, sweeps
  deleted-chat orphans, and advances its chat-update watermark atomically, with
  an overlap on the next pass. `GET /api/usage/model-activity?time=&tz=` uses
  the same optionally unbounded date-window handling as `model-daily` and
  returns `{from_date, to_date, coverage_from, models, total}`. The UI computes
  row `Avg requests` as that usage row's Requests divided by its attributed
  Turns. The Total cell is the ratio of totals, total Requests divided by the
  endpoint's all-model Turns, never a mean of row ratios. Because the Live table
  is usage-row anchored, endpoint Turns from activity-only models can contribute
  to the Total denominator without creating a visible model row; this and the
  cross-source scope are disclosed in the shared header tooltip.
- **Coverage is declared, never inferred from the oldest incidental fact.** A
  fresh install records incremental activity but returns `coverage_from: null`
  until `y usage backfill-activity --days N` explicitly establishes a historical
  lower bound. A bounded requested window starting before non-null
  `coverage_from` is partial and the UI marks the three columns accordingly.
  An unbounded response preserves null bounds and still exposes
  `coverage_from`; it does not pretend the facts predate that declared bound.
  The migration and historical backfill are maintainer-run actions, never
  automatic deployment mutations.

### Per-request transcript usage (todo 3729)

- **What a trace counts.** `sessions` is the number of chats on the trace.
  `transcripts` is the number of distinct Claude Code session ids among the
  uploaded rows. `requests` counts those rows. `turns` comes from
  `chat_model_activity` and `inbound` counts user-role messages in the chat
  body. The two are different facts: a turn is an answered prompt group, an
  inbound message is one user message.
- **Attribution and privacy.** The source is the transcript JSONL on the VM.
  A request is uploaded only when the server can positively attribute it to one
  of the owner's `claude_code` chats: a dispatch prefix whose chat and trace
  match, or, for requests before the first prefix, the owner's chat whose
  `external_id` is that session. Everything else stays on the VM. The resolve
  call sends ids only, and the upload sends ids and counters, never message
  text or file paths. Personal interactive sessions therefore never leave the
  machine. Todo 3844 widens this, for context analysis only, to relative
  labels, digests and sizes; see Session context analysis below. Subagent transcripts are not uploaded; they are counted as
  unsupported.
- **The cost gap.** No validated per-request price is ingested from the
  transcript, so v1 returns cost as unavailable with the reason
  `no_recorded_per_request_cost`. There is no price table and no estimate.
  (Newer CLI transcripts do carry cumulative `cost-state` estimates; they are
  not per-request charged dollars and are not ingested. See todo 3844.)
- **Relay divergence.** These rows count Claude Code requests observed in a
  transcript. The relay's `model_usage_*` totals are global, billed, and
  include traffic with no y-agent chat. The two are expected to differ and are
  not reconciled here.
- **Completeness is unknown.** A scan covers only the transcript files present
  on the VM at that moment. `historical_completeness` is always `unknown`; the
  report shows scan freshness and the counts of what the scan could not
  attribute instead of inferring coverage.
- **What a scan record discloses.** `y usage ingest-transcripts` keeps a
  per-file checkpoint (size, mtime, what the file still owes) under
  `~/.y-agent/usage-transcripts/`, keyed by API base and owner. Any change in
  size or mtime reopens a settled file. The disclosure counters in a run record
  are the sum over every transcript still on disk, scanned in that run or
  skipped because it is settled or backing off, so a quiet run never turns an
  earlier loss into a clean zero. A file with no validated segment is
  `files_unmatched`, not unattributed requests. The 24h cutoff after mtime
  settles only unmatched or partly unattributed files; a file with rejected
  rows or identity conflicts is retried with backoff and stays disclosed.
  Backoff is 1h doubling (capped at 32h) and counts only consecutive unsettled
  attempts on the same file version, so clean scans of a growing transcript
  never lengthen the first retry. A failed resolve or upload keeps every fact
  it could not remeasure (earlier rejections and conflicts, and on a failed
  resolve the unmatched / unattributed counts); a later successful scan
  replaces them.
  `--dry-run` resolves ids, uploads nothing and writes no checkpoint.
- **Read surface.** `GET /api/trace/usage?trace_id=` returns the totals, per
  model, per chat, the collection state and the cost gap. `y todo usage`
  renders it. Per chat it shows the chat's current skill, bot and tier, which
  describe the chat's configuration now, alongside the historical request and
  token facts.

### Session context analysis (todo 3844)

Plan and audit: `pages/plan-3844-session-context.md`. Roy accepted all five
recommendations of that plan's open set on 2026-10-11; they are recorded here
as decisions.

- **Approximate MVP, no proxy.** Source is the native transcript the existing
  ingest already reads, not a wire proxy or relay change. The analysis
  reconstructs context composition from transcript evidence (prompt snapshots,
  instruction-file attachments, skill listing, tool use / result pairs,
  deferred-tool records, parent links) and states the unknown remainder.
  Wire-exact token attribution is not promised.
- **Placement.** First delivery: a Context view in the chat module's chat
  detail, `y chat context <chat_id> [--json]`, and trace participant links
  into it, all reading one owner-bound host API. Bot Usage session ranking
  and comparison come later and link to the same Chat Context instead of
  duplicating it. Monitor is unchanged.
- **Footer entry (round 2).** As a user inspecting the current chat's context
  usage, I can click or tap its footer percentage badge to open that chat's
  Context analysis directly. Mouse hover retains the usage tooltip with
  "Click for context analysis" guidance; click no longer pins the tooltip.
  Without a selected chat, no badge is shown.
- **Ownership.** Raw transcript parsing stays on the VM inside the existing
  transcript ingest path. Bounded request / category / contributor aggregates
  live in host-owned storage next to `chat_request_usage`, read through the
  usual entity, repository, service and controller layers. Modules consume
  them through owner-bound host reads; no module owns the tables. Migrations
  are maintainer-applied SQL only.
- **Privacy (explicit widening of the todo 3729 rule).** The 3729 upload sends
  ids and counters only. This feature additionally allows, for attributed
  y-agent chats only: owner-only relative source labels (rules file, skill,
  reference, tool name, relative file path), local content digests, byte
  sizes, estimated token sizes and category / event metadata. Never uploaded:
  prompt, output, tool input or tool result bodies; credentials or secret
  values; absolute home paths. The ingest rejects unrecognised fields rather
  than storing them, so a field cannot smuggle raw text. Context detail is
  owner-only and is never exposed on public trace or chat shares.
- **Retention.** Detailed per-request and per-contributor rows are kept 30
  days; per-chat session totals are kept longer, with the same lifetime as
  `chat_request_usage`.
- **Freshness.** Each Claude Code run's normal closeout (completed or
  interrupted), after Telegram delivery and post hooks where applicable,
  launches a best-effort detached session-scoped ingest on the VM without
  waking EC2. The unchanged hourly ingest is the backstop for missed triggers
  and error/continuation paths. Scoped runs preserve other checkpoints and do
  not advance global full-scan freshness; all scans serialize checkpoint
  load/scan/save with a bounded file lock. Ordinary reads use stored rows only
  and never scan files, SSH or wake EC2. No during-run streaming. Backfill is an
  explicit, bounded command over transcripts still retained on the VM;
  `historical_completeness` stays `unknown`. Native subagent transcripts and
  personal non-y-agent sessions are excluded from the MVP, as in todo 3729.
- **Versioning.** Each stored request analysis carries an analysis version.
  Re-analysis under a newer version replaces that request's analysis rows as
  a unit; it never max-merges category estimates the way 3729 merges
  counters. Transcript checkpoints record the analyzer version so a parser
  upgrade can reopen settled files on an explicit backfill. Per-chat state is
  one of `none`, `pending`, `analyzed`, `partial` or `unsupported`.
- **Units are not interchangeable.** Provider billing tokens (U uncached
  input, W cache creation, R cache read, O output), estimated category token
  sizes, emitted transcript bytes, active context occupancy and session
  cumulative input are distinct quantities with their own unit, source and
  confidence. NULL is not zero. Prompt size is P = U + W + R only when all
  three are known.
- **Category contract.** Categories are mutually exclusive by precedence:
  rules / memory, skills and references, file and other tool results, then
  generic results. System prompt comes from the prompt snapshot active at the
  request (unknown when no snapshot exists; today's disk files are never
  reread as historical truth). Tool / MCP schemas count only what a snapshot
  or verified deferred-activation record shows was included; available,
  approved, deferred and included are different states, and the approved MCP
  catalog is never charged to every request. Skill listing is startup
  overhead, distinct from a loaded skill body. Tool results count the
  returned (possibly truncated) text, not the source file's size. Tool inputs
  are conversation history, not schema. Retained history is an age dimension
  on spans, not a second category. Multimodal, opaque reasoning and hidden
  formatting go to unknown overhead.
- **Contributors.** Each span keeps origin kind, introducing request, content
  digest, byte size, occurrence id and an optional safe label. Repeated
  insertions of the same content block id count once; actual repeated reads
  remain separate occurrences and feed the repeated-read suggestion.
- **Compaction.** Reported only from an explicit boundary record whose shape
  has been verified against fixtures. The marker is an event, the summary is
  content, and a boundary starts a new epoch whose earlier spans are not
  summed into later requests. Dropped spans without a marker are not
  compaction, and a y-agent session restart or handoff is a different event.
  Until the boundary shape is verified, post-boundary occupancy is shown as
  unknown.
- **Token estimates.** Category token sizes are estimates from a named,
  versioned counting method chosen before the token-share UI ships; a plain
  chars/4 heuristic must be labelled as such. No private text is sent to a
  token-count API.
- **Cache metric.** The new metric is input-only reuse R / P per request, and
  sum(R) / sum(P) over requests with all counters known, coverage disclosed.
  It is labelled distinctly from the existing Bot Usage cache-hit percentage,
  whose denominator includes output (see todo 3403); the old metric is not
  changed. Aggregate R cannot be attributed to a particular file.
- **Cost.** Observed counters only; cost is `unavailable`, as in 3729. Newer
  transcripts do carry cumulative CLI `cost-state` estimates, so the precise
  reason is that no validated per-request cost is ingested, not that the
  transcript records no cost at all. A notional price estimate would need an
  effective-dated model / provider / cache-TTL price source and an explicit
  notional label; relay daily cost is never allocated pro rata to chats.
- **Suggestions.** Deterministic rules only: repeated identical read, large
  tool result, heavy startup rules or schemas, repeated prefix change. Worded
  as correlation, never as guaranteed savings or cache-miss causality. No
  composite efficiency score, no model-based judgement and no automatic
  trimming or rule editing.

## Testing Decisions

- **Idempotency is the storage contract to test:** upserting the same
  (user, date, source, scope, model) row twice yields one row with the second
  write's values; re-running sync or backfill leaves row counts unchanged.
- **Completeness and no-double-count are the sync contracts:** with multiple
  relay keys configured, the sync queries each distinct key once (shared keys
  deduplicated) and per-model sums match the relay dashboard's totals for the
  same day; a failing key aborts the run with no rows written.
- **Hourly↔daily reconciliation (todo 3165 acceptance bar):** after one full
  Asia/Shanghai day of post-deploy hourly sync (the first complete local day
  after CRS writes zero-cost micro fields on daily and hourly counters),
  per-model `SUM(model_usage_hourly)` must match `model_usage_daily` on tokens
  and requests exactly, and on cost within float display precision. Days that
  still contain pre-deploy Redis counters (legacy list-price fallback) are
  excluded from that bar; no `isLegacy` column is stored to diagnose them.
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
  stopped instance answers `vm_unreachable` with no wake attempt (asserted by
  the command never being run); valid-JSON-wrong-shape yields an explicit
  `bad_payload` failure rather than an empty-looking success; a Grok-only row
  is available and fresh; malformed percentages normalize to null. (Pre-3226:
  a transient SSH/CLI failure degraded an available row straight to `stale`
  at write time; that per-row write-time degradation is superseded by the
  persisted snapshot's read-time freshness recompute below, which leaves a
  `reauth_required` row's actionable code intact the same way.)
- **Persisted snapshot: refresh, merge, lock, and startup contracts (todo
  3226) are asserted directly, not inferred from the API diff:** an ordinary
  read never resolves the VM, probes EC2 asleep-state, or runs the CLI
  (asserted by those calls raising if invoked); a failed attempt persists
  failure metadata (`last_attempt_status`, `last_attempt_error`) while
  leaving the previously persisted `providers` byte-identical; freshness is
  recomputed from `observed_at` at read time (a row inside the ten-minute
  read TTL reads fresh, the same row read again past it reads stale, with
  `observed_at` itself never restamped); `merge_providers` falls back to the
  previous row for a same-attempt read-failure code (`parse_failed` /
  `transport_error`) and, separately, for a backend missing from the new
  attempt entirely (there is nothing new to overwrite it with), while always
  overwriting for a durable state or a normal reading; a lock already held
  makes the sweep skip that user (asserted by the CLI never running) and
  makes a manual retry return the stored snapshot with `refresh_in_progress`
  instead of starting a second CLI run; the manual and scheduled paths are
  asserted to call the identical `refresh_and_persist_snapshot` function with
  only `force` differing; the CLI timeout stays the existing 30s bound; and a
  user with no successful refresh yet reads a bounded `snapshot_unavailable`
  envelope without any VM probe.
- **No quota gate (todo 4138).** A successful refresh does not read or write
  a bot's enabled bit. Codex and Grok rows survive normalize, merge, and
  read; `claude_code` rows and Claude-origin errors do not. History does not
  synthesize a missing Claude backend and does not write extra windows.
  Stored history rows are not deleted. Cadence stays 1800s and read freshness
  600s.
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
  construction (chart per-period totals equal table column totals because both
  derive from the same seven-plus-Other fold when the model query is empty, and
  from the same matched set when it is not).
- **The two folds are checked by their reconciliation contracts, not their
  internals:** the six legend entries' per-period values sum to that period's
  total (the legend partitions the period), a legend-Other filtered bar equals
  the period total minus the top five and is asserted to be *different* from the
  table's Other row whenever more than seven models exist, and the legend is
  asserted to carry no Other entry at all when five or fewer named models exist.
  Toggling a legend filter on and off is asserted to restore the original
  stack, and the table is asserted unchanged across both of those states. A
  non-empty model query is asserted to change the table, averages, and heatmap
  or hourly grid together, and an empty query is asserted to restore the
  unfiltered surfaces. The legend's Other swatch
  is asserted neutral on both sides of the seven-model boundary, the caption is
  asserted to state the Other bucket's scope while that filter is active, and
  the legend entries are asserted to expose their pressed state.
- **Account balances acceptance.** Fixture checks cover OpenRouter account
  remaining as total credits minus usage (never per-key allowance), DeepSeek
  CNY and USD rows without double-counting components, real zero, malformed
  payloads, missing keys with no network call, isolated provider failures,
  cache reuse and forced refresh, and stale fallback with the original
  observation time. Static UI checks assert balances precede limits in Live,
  with Model share first on narrow panels and the donut right on wide panels.
  API fixtures distinguish loading, not configured, error, stale and zero;
  amounts-only UI fixtures preserve real zero, separate currencies and
  placeholders without expecting freshness or retry controls. Layout fixtures
  cover D10–D15 roles, limit fills at 59/60/80%, full reset text, table reveals
  and mirrored totals, keyboard sorting and `aria-sort`. Host checks assert both
  optional NoEcho parameters, API-only environment mappings and both deploy
  paths, with no literal credentials in tracked files. Live provider/UI smoke
  checks require the matching host deployment and module publication first;
  a missing DeepSeek key permits not-configured acceptance but cannot verify
  its live response shape.
- **Tab-scoping visual checks** confirm that Live shows Subscription limits but
  not the Daily tokens widget, while Over-time shows the Daily tokens widget
  but never renders or requests Subscription limits.
- **Limit-status states** cover fresh, stale, never-observed, provider-error,
  re-auth-required, missing-reset-time, zero-windows-reported, and narrow-panel
  layouts across both retained backends, with configured-timezone reset labels
  checked against the absolute API timestamps. These are asserted in component
  tests and fixtures; screenshots are taken only on request, per the house
  policy that agent-driven UI runtime checks are opt-in.
- **Limit-window history (todo 3717).** Unit coverage, no database: an
  attempt failure writes no observation; a provider error with a null source
  time stays, with `freshness=unavailable` (only an `available` row can be
  `unknown`); an absent Grok is `missing` and
  inherits its origin error; a merged fallback row is never recorded; a UTC
  16:30 bucket lands on the next local midnight hour; freshness is
  fresh/stale/future/unknown against the collection time, and a source four
  minutes before the attempt is fresh; a reset inside an hour and a null reset are separate
  groups, and two distinct reset values are not merged; replaying one
  attempt id writes nothing and two attempts sharing a source time count as
  one distinct observation; empty hours are present with zero attempts; 32
  days, too many observations, and too many attempts all refuse; the spend
  join asks for more than the 1,000-row default and keeps the `x-ai` provider
  and its `cost_basis`; NaN and bool percents store NULL. The refresh hook
  records exactly one attempt for each outcome and records nothing when the
  lock is already held, and a raised history error still returns the
  snapshot. Codex `allowed=false` without `limit_reached` stores NULL.
  Owner isolation is asserted by the read asking the repository for that
  user only; the single-transaction idempotency is the `ON CONFLICT DO
  NOTHING` insert, which commits the attempt and its observations together
  and skips both on a replay.
- **Session context analysis (todo 3844).** Local-only sanitized transcript
  fixtures are written before the analyzer, covering both prompt-snapshot
  shapes and a verified compaction boundary. Analyzer: a repeated content
  block id counts once, an actual repeated read stays a separate occurrence,
  branch / resume / compaction exclude discarded spans, a missing snapshot
  yields unknown, malformed / truncated / sidechain records disclose the gap
  instead of fabricating a reconstruction. Storage: owner and trace isolation,
  NULL versus zero, upload replay idempotence, analysis-version replacement,
  bounds and rejections, and an unrecognised field cannot carry raw prompt
  text, a secret or an absolute path. API / CLI: CLI and API parity, stable
  request pagination, no-data versus unavailable, R / P excludes output,
  incomplete counters disable the ratio, reads never invoke the VM, public
  share routes expose no context detail. Web: unknown and estimated states stay
  visible, and repeated exposure is never labelled as billed savings; typecheck
  and build gate the module.
- **Post-deploy smoke:** trigger a sync, confirm rows appear for the current
  day, spot-check a date's totals against the relay dashboard, then call the
  deployed limits endpoint and confirm Codex and Grok return with an empty
  error list and no Claude subscription row; cross-check the Grok number
  against the vendor's own billing view, and confirm a relay-backed agent
  turn running concurrently is unaffected. `y claude` is not a command. The
  named `fable` bot's enabled bit is unchanged by the refresh.
- Prior art to mirror: the finance test suite's derived-view style and the
  finance price table's upsert tests.

## Out of Scope

- **Balance history, top-ups, alerts, currency conversion, per-key allowance
  display and a balance CLI.** Account balances is a current read-only Live
  surface, not another spend-ingestion or subscription-limit pipeline.
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
  deferred rather than rejected: the legend click is a chart-reading aid, and
  neither has been asked for. The Filter models query is a separate control
  and does narrow the table (story 66e). This exclusion is only the legend
  click.
- **Encrypting `crs_admin` / `bot_config.api_key` at rest.** The repo has no
  secret-encryption layer; both already store plaintext secrets, and adding one
  is a separate decision. The approved 3121 change deliberately stores the
  Relay admin credentials in `user_preference` so the API can call Relay
  directly; that is in scope above, encryption is not.
- **A CLI listing/reporting surface** for spend rows (only sync and backfill
  commands exist; no consumer has asked for a terminal view). The limit-window
  side does have one, `y usage limits`, because the backend is built on it.
- **Rated / list-price cost reporting** (only real billed cost is stored and
  shown).
- **Active-hours analytics**, and any hourly grid beyond the seven-day `H`
  card. Todo 3165 excluded hour-of-day presentation outright; todo 3566
  superseded that exclusion for exactly one surface, the seven-day by 24-hour
  grid shown at `H` granularity. The year-window contribution heatmap stays
  daily, and hour-of-day aggregation (busiest hours across the window), longer
  hourly windows and per-bot / per-key hourly attribution remain excluded.
- **Hourly history older than the relay's ~7-day hourly TTL** (expired in Redis,
  unrecoverable) and Postgres-side hourly retention/pruning (row volume does not
  justify a policy yet).
- **Persisting `isLegacy` (or any other legacy-cost marker) on usage rows.**
  Stored real cost is the authority after the zero-cost write ships; the
  temporary pre-deploy Redis window is accepted as non-reconciling for cost
  without a durable flag (todo 3165).
- **Exact cost reconciliation against days that still contain pre-deploy
  Redis counters.** Those mixed legacy/list-price windows are outside the
  acceptance bar; the bar starts at the first complete Asia/Shanghai day after
  CRS writes zero-cost micro fields on daily and hourly counters.
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

- **Context analysis beyond the MVP (todo 3844).** A wire proxy or relay
  change for exact attribution; during-run streaming analysis; native
  subagent transcripts and personal non-y-agent sessions; notional cost
  estimates; a composite efficiency score or model-based scoring; automatic
  rule trimming, tool-output truncation changes or any other
  auto-optimization; public sharing of context detail; sending private text to
  a token-count API. The Bot Usage session ranking is deferred to a later
  delivery, not rejected. MCP input rendering (todo 3807) is a separate
  concern and not a deferred-schema telemetry source.

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
