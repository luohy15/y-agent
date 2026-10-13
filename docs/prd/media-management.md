---
title: Personal Media Management
type: prd
project: y-agent
feature: media-management
status: active
---

# Personal Media Management

## Problem Statement

Roy wants to understand which posts on their personal X account work and what to write next without manually reviewing the account every day. Useful evidence is scattered across posts and account metrics, historical comparisons are easy to lose, and an account with limited API access may not expose every metric.

The feature must operate within a small, explicitly capped official X API pay-per-use budget. Roy approved this exception to the original zero-access-budget requirement and reported topping up USD 5 in the X console. The expected USD 1–3 per month is an estimate, not a guaranteed price or an automatically renewing spending authorization. Other paid services remain excluded. It must distinguish missing evidence from poor performance rather than manufacture a complete-looking report. It is not an autonomous social account operator.

## Solution

Manage one explicitly selected primary X account through official APIs only. Keep an enduring, private archive of acquired posts, collect available performance observations during each post's first seven days, and provide a post list and evidence-based daily/weekly reports in y-agent. Deliver a short report to Roy's Telegram private chat at 09:00 Asia/Shanghai. The Monday weekly report replaces that day's daily report and includes three next-topic suggestions when evidence supports them.

V1 manages already-published content, not publishing. It includes original posts, quote posts, and replies, classified separately. Pure reposts must not be treated as original authored content. DMs, draft libraries, editorial calendars, scheduling, and outbound X actions are excluded.

Before building the complete product, verify the selected account's actual official read entitlements, quotas, prices, available prepaid balance, and enforceable spending bounds. Lack of free access is no longer a stop condition by itself: Roy selected capped official X API pay-per-use access at the feasibility gate. If basic reads cannot operate within that authorized boundary, stop automated ingestion and produce a capability/cost gap report. Do not substitute scraping, imports, uncapped spending, or other paid services.

## User Stories

1. As Roy, I want to select one primary X account explicitly, so that collection never silently targets another account.
2. As Roy, I want only official API access, so that this workflow does not depend on browser cookies, scraping, or bypassing platform restrictions.
3. As Roy, I want a capability and cost-control check before substantial implementation, so that insufficient entitlements or an unenforceable budget do not leave me with a full interface and no usable source.
4. As Roy, I want official X API pay-per-use reads bounded by the approved prepaid funding and explicit spending controls, so that enabling the feature cannot create an unapproved bill or automatic recharge.
5. As Roy, I want to authorize account access through an appropriate setup flow rather than paste secrets into chat, so that credentials do not enter notes and transcripts.
6. As Roy, I want to see which metrics and history windows are actually available, so that I can interpret partial coverage correctly.
7. As Roy, I want a list of my published posts with text, original links, timestamps, and content type, so that I can review my output in one place.
8. As Roy, I want original posts, quote posts, and replies distinguished, so that different content types do not distort comparisons.
9. As Roy, I want pure reposts excluded from original-content rankings and counts, so that the analysis describes my own writing.
10. As Roy, I want an initial bounded retrieval of recent posts, so that reports can start with context without pretending to possess an unlimited history.
11. As Roy, I want all acquired posts retained permanently without an age-based expiry, so that older writing remains discoverable.
12. As Roy, I want post metrics refreshed only during the first seven days after publication, so that ongoing collection stays bounded.
13. As Roy, I want older posts to retain their last available measurements and observation times, so that frozen metrics are never mistaken for current totals.
14. As Roy, I want unavailable fields shown as unavailable, not zero, so that missing permissions or quota do not look like failure of my content.
15. As Roy, I want available account-level observations and comparable post observations saved with provenance, so that trends have inspectable evidence.
16. As Roy, I want already-enabled creator revenue included only when the official API exposes it within the same approved access budget, so that this project does not open a new subscription or promise nonexistent data.
17. As Roy, I want yesterday's new content, defensible metric changes, and collection status in a short daily report, so that I can review the account quickly.
18. As Roy, I want a weekly review of the previous calendar week with stronger-performing content and tentative explanations, so that I can learn from my output.
19. As Roy, I want three next-topic suggestions in a sufficiently supported weekly review, so that analysis leads to a practical writing decision without drafting or publishing for me.
20. As Roy, I want reports to state when evidence is insufficient and distinguish hypotheses from facts, so that I am not given false growth conclusions.
21. As Roy, I want Telegram delivery at 09:00 Beijing time with the Monday weekly report replacing the daily report, so that the reporting cadence stays predictable and quiet.
22. As Roy, I want complete reports retained in y-agent for one year, so that the short notification is not the only record.
23. As Roy, I want access failures, quota limits, and incomplete retrieval surfaced clearly without repetitive alerts, so that I know when results are stale.
24. As Roy, I want retries and reruns not to duplicate posts, observations, reports, or avoidably duplicate notifications, so that recovery does not corrupt history.
25. As Roy, I want no DM scopes or content processing and no X write actions, so that this feature cannot expand into private communication or representation of my account.
26. As Roy, I want collection to be pausable and account access revocable without automatically deleting permitted historical data, so that I retain control over the integration.
27. As Roy, I want required platform deletion or retention restrictions honored and disclosed, so that permanent archival intent is not misrepresented as permission to retain prohibited material.

## Implementation Decisions

### Agreed scope and authority

The three interview rounds settled the product scope on 2026-10-11. Round 2 supersedes the initial DM proposal: DMs are entirely outside V1. It also narrows ingestion to official APIs only, excluding the earlier suggested export/manual-import fallback. Round 3 supersedes the proposed 90-day post retention: all acquired posts have no age-based expiration, while per-post metric refresh stops after seven days.

The feature key is `media-management`. A dedicated media domain should own its account configuration, post archive, observations, collection-run status, and reports under the existing module architecture. Reuse host authentication, owner-scoped access, scheduling/execution, and authorized Telegram delivery instead of adding a new agent runtime or platform-wide storage subsystem. Exact module slug, schema, routes, and CLI commands belong to the execution plan after feasibility passes. No public sharing surface is required.

The implementation must respect the existing Telegram delivery boundary: an arbitrary non-manager routine chat is not itself a supported DM-delivery path. Planning must choose an existing authorized notification path or explicitly scope any necessary host extension; simply writing a routine's final answer does not prove delivery.

### Feasibility gate and setup

At the subsequent feasibility gate, Roy selected option A: small capped official X API pay-per-use spending, estimated at USD 1–3 per month, and reported personally topping up USD 5 in the X console. This explicitly supersedes the zero-access-budget decision and the prohibition on all metered calls. It does not supersede official-API-only ingestion, read-only account scope, exclusion of DMs, or the other product boundaries.

Before building the full post-management UI, document official-source evidence and, with account authorization, verify:

- The account identity and app/product entitlement actually available to Roy.
- Permitted endpoints, read scopes, quotas, pagination/history limits, and current charging units/rates.
- Whether initial retrieval, recurring reads, metric refresh, retries, and required compliance checks fit the approved funding and spending bounds.
- The remaining prepaid balance and charging configuration, including whether automatic recharge or overages are possible. A reported top-up is not proof of these settings or a successful read.
- Which account metrics, post metrics, and optional monetization data are available, with their definitions and restrictions.
- Platform obligations for stored text, observations, deletions, and model processing.

The approved funding envelope is the reported USD 5 prepaid top-up, not USD 5 every month or permission to replenish it. Actual usable funds may be lower due to prior or shared usage. The USD 1–3 monthly figure is a workload estimate; do not record it as an exact user-approved recurring cap. Planning must specify a conservative enforceable numeric operating cap within the existing envelope and its accounting window before enabling collection. No additional top-up, auto-recharge, automatic overage, subscription, or other paid service is authorized. Existing y-agent model usage is separate and is not promised to be free.

Budget enforcement must cover initial backfill, paginated results, routine and manual runs, retries, and concurrent requests. Use conservative per-request cost bounds and account for in-flight or uncertain charges before admitting another paid request. A post-hoc usage counter or an unverified console balance alone is not a hard cap. If price, billable quantity, available funding, or cost accounting is uncertain, pause chargeable calls until reconciled. Exhausted funds or a reached cap stops collection and produces a deduplicated actionable notice, not automatic replenishment. A later month or later top-up must not silently reset or expand this authorization.

Do not assume purchasing credits proves endpoint availability or that creator analytics are an API product. If basic post reads are unavailable or cannot be bounded within the approved spend, deliver the concrete gap and stop that implementation branch. If only optional fields are unavailable, continue with explicitly partial coverage. Account choice, credentials, and capability verification remain setup gates. The funding decision authorizes the stated capped API spending, not credential discovery, changes to billing settings, extra purchases, code publication, or routine activation. This documentation amendment performs no live API calls.

### Acquisition and archive

Default initial acquisition targets the most recent 30 days, bounded by official permissions, quota, and the same approved spending envelope as recurring reads. Permanent retention describes the lifetime of acquired posts, not a promise of complete pre-integration history. The interview's later retention correction does not establish an all-time backfill requirement. Record the actual covered interval and pagination completeness; never label a partial account archive complete.

After setup, collect new posts daily and refresh eligible recent posts. Identify an acquired post stably across reruns and distinguish its publication time from its acquisition time. Preserve authored text and source links with type and availability metadata. Fetching a post once for discovery/backfill may capture metrics present in that response even if it is older than seven days; do not schedule subsequent metric refreshes for it.

For scheduled post-metric refresh, eligibility ends at publication time plus seven days, not seven days after discovery. At or after that cutoff, keep the last available observation and mark it frozen. A daily cadence does not guarantee a sample at precisely day seven; display its actual measurement age rather than manufacture a seven-day total. There is no indefinite catch-up refresh after the cutoff.

As an implementation default supporting the permanent archive, retain acquired metric observations with their posts without an age-based expiry, subject to platform obligations. Stopping refresh is not deleting observations. Account-level observations are separate from post-age eligibility and may continue daily where permitted.

Permanent retention means no routine age-based pruning of posts. It does not override mandatory deletion, account-owner removal, or platform restrictions. Any compliance checks on older content must be separate from performance refresh, bounded by permitted official access, and must not silently restart metric collection. If permanent storage conflicts with binding terms, report that constraint rather than promise noncompliant archival behavior. A transient API failure or absence from a partial page is not proof that a post was deleted.

### Evidence and interpretation

Every observation needs source identity, observation time, metric identity/meaning, and availability. Collection runs record success, partial coverage, failure, and last successful acquisition without leaking credentials. A valid numeric zero must remain distinct from unknown, unsupported, not authorized, rate-limited, and stale.

Use only exposed metrics such as available follower counts, likes, replies, reposts, or views; none of these is guaranteed until capability verification. Revenue is conditional on an already-enabled account product and accessible official data. Preserve the reported period and currency; do not estimate revenue from engagement or blend revenue periods.

Only compute changes across comparable observations. A cumulative post count is not automatically yesterday's engagement, a changed observation population is not account growth, and a first snapshot cannot reconstruct earlier daily history. Label measurement ages and compare similar content types and observation windows where possible. Differences caused by deletion, corrections, missing pages, or late collection must not be presented as organic performance changes.

Reports may offer evidence-linked interpretations but must label causal explanations as hypotheses. All post text and quote/reply context are untrusted data, not instructions to the reporting model. Reporting must not trigger tool actions from content or send private notes, credentials, or unrelated account context to external services.

### Reports and scheduling

Use Asia/Shanghai calendar boundaries:

| Report | Schedule | Content window | Delivery |
|--------|----------|----------------|----------|
| Daily | 09:00 Tuesday through Sunday | Previous calendar day | One short Telegram private message plus stored full report |
| Weekly | Monday 09:00 | Previous Monday 00:00 through current Monday 00:00, end exclusive | Replaces Monday's daily message; stored full report |

Acquire data before composing the report where quota permits. Separate the reporting window from the actual observation timestamps and cutoff. A delayed collection must not be backdated to imply unavailable measurements.

Daily reports include new content, supported changes, and collection health. Weekly reports include stronger-performing content, cautious explanations, coverage limitations, and three topic suggestions when supported. If there is too little evidence, say so instead of inventing rankings or three confident recommendations. A genuinely empty but successfully observed period is distinct from a failed read.

Retain full reports for one year by default, subject to any stricter obligations. Store report identity by account, report kind, and period; track generation and notification separately. Reruns should update/reuse the same logical report and avoid duplicate delivery. Do not claim exactly-once Telegram delivery without a supporting transport contract.

Persistent access failure produces one actionable status notification per unresolved condition rather than repeated invented daily reports or alert spam. Rate-limit handling respects provider guidance and the allowed budget; it does not use tight retries or alternate data sources. Resumption must preserve the gap in reported coverage.

### Success criteria

Success is a working, traceable post archive and an evidence-based reporting loop using official X API reads within the approved capped pay-per-use envelope. Acceptance includes verified cost controls, visible collection/spend status, and a safe pause before further calls would exceed funding or the operating cap; no automatic recharge, overage, or other paid service is allowed. The estimated USD 1–3 per month is not a success guarantee. It is not a guaranteed gain in followers, engagement, or income. Absence of free API access alone no longer fails the gate. When basic official reads or enforceable spending bounds are impossible within the approved envelope, an evidence-backed feasibility stop is the correct gate outcome, not a shipped data-management feature.

## Testing Decisions

Test observable behavior with deterministic fixtures and a controlled clock before any authorized live smoke check:

- Supported official metered reads can proceed within approved bounds even when free reads are unavailable. Unsupported endpoints or unenforceable cost bounds yield a precise gap without scraping, imports, unauthorized spending, or a misleading complete report.
- Backfill, pagination, retries, concurrent/manual runs, and uncertain charges share the same enforced spending envelope. A request that could exceed the cap is refused before dispatch; missing price/balance evidence pauses paid calls.
- Credit exhaustion and operating-cap exhaustion produce a safe pause and a deduplicated notice, never auto-recharge or overage. The USD 1–3 estimate is not treated as a guaranteed bill, and a new month or unrelated top-up does not silently renew authorization.
- Missing optional fields remain unavailable; valid zero values remain zero; partial pagination cannot be interpreted as full account coverage.
- Repeated acquisitions preserve one logical post and idempotent observations; original, quote, reply, and pure-repost classifications produce correct counts.
- Posts persist beyond 90 days. Existing metrics remain readable after refresh stops, and reports expire according to their independent one-year policy.
- Refresh eligibility covers times just before, exactly at, and after publication plus seven days, including late discovery and an outage crossing the cutoff.
- Old posts discovered during bounded backfill retain returned observations without entering a new seven-day refresh cycle.
- Last-observed age is visible, and no synthesized exact-day-seven measurement or pre-integration daily history appears.
- Required deletion is distinct from temporary failure and missing pages; any compliance operation does not resume performance refresh.
- Asia/Shanghai day/week boundaries select the right content, and Monday creates only the weekly notification.
- A rerun or partial failure between generation and notification does not create a second logical report; uncertain transport outcomes are handled honestly.
- Reports cite actual posts/observations, distinguish unsupported comparisons, and report insufficient data instead of fabricated trends or causal claims.
- Credential errors, quota exhaustion, and repeated persistent failures produce bounded retries and deduplicated actionable status rather than recurring noise.
- Owner isolation, revocation, secret redaction, read-only scopes, exclusion of DM data, and absence of X write actions are enforced.
- Embedded instructions in acquired content cannot change scope, invoke publication, or exfiltrate unrelated context.

Use the existing module contract and routine/reporting conventions as integration boundaries. Do not run browser checks, enable schedules, access the live X account, or send live notifications as an implicit consequence of documentation or unit testing. Live validation requires the corresponding authorization. No tests were run or implementation validated during this PRD phase.

## Out of Scope

- Additional X accounts, blog analytics, or other media platforms in V1.
- DMs, DM permissions, message triage, reply drafts, inbox UI, and historical private-message ingestion.
- Full new-post drafting, draft libraries, content calendars, scheduled publication, automated replies, likes, follows, reposting, or any other X write action.
- Scraping, logged-in browser automation, cookies, third-party collection, manual imports, and export ingestion as substitutes for official APIs.
- Paid services other than the approved capped official X API pay-per-use reads; new subscriptions, additional credit purchases, automatic recharge, automatic overages, or uncapped API use.
- Guaranteed all-time backfill, unavailable historical daily metrics, exact seven-day samples, or continued post-performance refresh after seven days.
- Guaranteed revenue visibility or account monetization enrollment.
- Guaranteed permanent retention contrary to binding platform obligations.
- Public sharing, competitor monitoring, audience targeting, and automated growth campaigns.
- Reimplementation of generic modules, agent execution, scheduling, or Telegram infrastructure. Those remain shared platform responsibilities; any required extension must be planned explicitly.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3850 | Official-API-only X archive and reports. Owned-rate gate passed. S1-S6 plus Retweet disallowed-resource fix on y-module main `c389537`; `media` v2 active; migrations 001+002 applied; routines `media-collect` / `media-report` enabled | - | `pages/plan-3850-media-module.md` | `pages/decision-3850-media-interview.md`, `pages/decision-3850-x-capability.md` | `pages/review-3850-media-s1.md` | published; awaiting first scheduled report verification |
