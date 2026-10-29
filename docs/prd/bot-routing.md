---
title: Bot Dispatch and Tier Routing
type: prd
project: y-agent
feature: bot-routing
status: active
---

# Bot Dispatch and Tier Routing

## Problem Statement

Every chat in the session tree runs on some bot: a named configuration binding
a model, backend, and endpoint. The system has many bots of wildly different
capability and cost (frontier models, mid-range models, cheap or free CLI
backends, a web-search model). Before this feature, choosing which bot ran
which session was ad hoc: a dispatching agent either hardcoded a bot name into
instructions ("manager/plan/dev default to fable"), or let everything fall to
the single global default. Static topic-to-bot bindings ignore task shape: the
same topic handles both judgment-heavy planning and mechanical follow-up work.
Worse, the routing semantics lived half in prose and half in code, and drifted:
at one point every bot was labeled the same tier, so requesting a tier silently
fell through to the default bot and nobody noticed until a high-priority bug.
Users and dispatching agents need routing that is predictable, inspectable as
data, and principled about where the expensive models go.

## Solution

Bots carry a nonempty set of capability tiers as data: a four-level ladder from tier0
(strongest, most expensive) to tier3 (baseline). Bot targeting on a dispatch
is a set of filters: bot name, backend, and tier, all of the same kind.
Resolution is one simple rule: intersect the given filters over the pool of
runnable bot configs to get candidates; exactly one candidate is used directly;
multiple-candidate tier pools use smooth weighted round-robin, while other
multiple-candidate pools use weighted random selection; no filters at all, or
filters that produce an empty set, fall back to tier2,
the system default. Skills are never statically bound to tiers. An empty
tier2 fallback pool falls back to the global default bot with a warning
rather than failing.

Which tier to request is governed by a documented dispatch policy, not code.
Tier1 and tier2 are the daily workhorses: tier2 is the default that
unfiltered dispatches inherit, and judgment-heavy dispatches (planning,
review, complex coding) explicitly request tier1. Tier0 is explicit user
escalation only: an agent never chooses it on its own; it is used when the
user asks for it, typically after tier1 underperforms on a task. Tier3
serves cheap high-volume, low-stakes work such as scheduled routines and
simple one-shot queries. New bots are graded
into the ladder empirically via a
standardized onboarding exam, not by intuition. Tier membership stays data:
inspectable and editable through the bot CLI, never memorized in instructions.

## Resume context limit

`bot_config.resume_context_limit` is nullable: NULL inherits the Opus global
limit (`Y_AGENT_OPUS_RESUME_CONTEXT_LIMIT`, default 100000); 0 disables the gate
for that bot; a positive value opts any model into the limit. Non-Opus bots
without an explicit limit are unaffected. This does not change routing weights
or tiers. The derived read-only state, warning band and continuation contract
are defined in `pages/feature-y-agent-chat-resume-gate.md`. Admission checks the
persisted bot first: a requested bot switch cannot unlock an already gated
chat. Continue via the offered new-chat handoff. Only complete measured main
request usage can trigger the gate; launch averages remain display-only.

## User Stories

1. As a dispatching agent, I want to request a capability tier instead of a
   bot name, so that my dispatch keeps working when the bot roster changes.
2. As a user, I want naming a bot to narrow the candidates to exactly that
   bot, so that my explicit pick is used whenever it is runnable.
3. As a user, I want a backend filter (for example perplexity) to narrow
   candidates to enabled configs with that effective backend, so that I can
   choose the runtime family without knowing config names. Since todo 2930 the
   only agentic backend is claude_code, so this filter is vestigial for agentic
   bots and only meaningfully separates them from the inline query backends
   (`perplexity`, `openai`, `xai_web`, `xai_x`).
4. As a user, I want a chat with no bot, backend, or tier specified to
   resolve as a tier2 request, so that unspecified dispatches land on a
   capable mid-range bot by default without any routing knowledge.
5. As a dispatching agent, I want multiple filters to intersect (for
   example backend plus tier), so that targeting signals compose instead of
   one silently overriding another.
6. As an admin, I want each bot's tier stored on its config and visible in
   the bot list, so that tier membership is queryable data rather than
   something agents memorize.
7. As an admin, I want unlabeled bots to default to the lowest tier, so that
   the majority of bots need no explicit tier configuration.
8. As an admin, I want to reset a bot's tiers to the singleton tier3 default,
   keeping the legacy clear-tier command without allowing an empty set.
9. As an admin, I want to weight bots within a candidate pool, so that I
   control the long-run new-chat draw split when filters leave multiple members.
10. As an admin, I want a bot with no positive route weight to never win a
    draw against weighted peers, so that adding a bot config never silently
    takes traffic from explicitly weighted bots.
11. As an admin, I want disabled bots and pointer bots excluded from
    candidacy, and model-type entries excluded from tier-based candidacy, so
    that auto-routing only ever lands on a real, runnable agent backend while
    explicit pins can reach inline models.
12. As a dispatching agent, I want skills never statically bound to tiers,
    so that tier choice reflects each dispatch's task shape instead of a
    stale per-skill label.
13. As a user, I want the top tier reachable only when I explicitly escalate
    to it (bot pin or tier request), so that the most expensive model is
    never chosen by a default or by an agent's own judgment call.
14. As a dispatching agent, I want an explicit tier request to override the
    tier2 default, so that I can escalate or downgrade any dispatch
    per-instance.
15. As a user, I want filters that produce no candidates to fall back to
    tier2, and an empty tier2 to fall back to the default bot, each with a
    logged warning, so that a data gap degrades service quality instead of
    breaking the chat.
16. As a user, I want an existing chat to keep the bot it started with when
    no bot is named on a later message, so that a conversation's model
    identity is stable across turns and changing the global default never
    moves a live conversation.
17. As an examiner, I want to grade a new bot through a standardized exam
    before placing it on the ladder, so that tier assignment reflects
    measured behavior in this system rather than reputation.
18. As a dispatching agent, I want a documented policy assigning each tier a
    role (tier2 default, tier1 judgment work, tier0 user escalation, tier3
    cheap volume), so that dispatch decisions follow one shared model
    instead of static topic bindings or per-agent intuition.
19. As a dispatching agent, I want one-shot web fact-checks pinned to the
    web-search bot with a synchronous wait, so that grounded single-turn
    queries bypass tier routing and return their answer inline.
20. As an admin, I want pointer bots that alias another config, so that the
    global default can be re-aimed at any bot by updating one reference.
21. As an admin, I want pointer resolution protected against cycles and
    unbounded depth, so that a misconfigured alias chain fails loudly instead
    of hanging resolution.
22. As a secondary user without my own bot configs, I want resolution to
    fall back to the system default user's configs, so that a fresh account
    can chat before configuring anything.
23. As a user, I want to name a different bot on an existing chat and have
    the rest of the conversation continue on it, so that I can move a live
    session up to a stronger model (or down to a cheaper one) without
    starting over and losing its context.
24. As a user, I want a bot change that would move a chat onto a different
    backend refused with the chat left on its current bot, so that an
    agentic conversation is never stranded on an inline query backend that
    has no session to resume.
25. As a user, I want a bot change naming something that does not resolve to
    a runnable bot (mistyped, disabled, or outside the tier I asked for) to
    leave the chat on its current bot rather than land it on whatever the
    fallback pool returns, so that a stale bot name can never silently and
    permanently downgrade a live conversation.

## Implementation Decisions

- **Tiers are a nonempty set on the bot config**, drawn from `tier0`
  (strongest) through `tier3` (baseline). `tiers` is a key-sorted JSON object
  mapping each member to its independent nonnegative finite weight or null
  (unset). Every full config write mirrors the strongest key into legacy `tier`
  and its weight into `route_weight`. Empty maps, unknown keys, booleans,
  negative/non-finite and non-number weights are rejected. Omitted `tiers`
  accepts legacy `tier` and `route_weight`; omitted or cleared tier means tier3.
  CLI repeatable/comma-separated `--tier` replaces membership, preserving weights
  of retained members and giving new members unset weight. Repeatable
  `--tier-weight tierN=W` patches a member only. The bot UI gives each checked
  tier its own weight field. Legacy `route_weight` alone is accepted only for a
  singleton; on a multi-tier bot the API returns 422 and the CLI reports a usage
  error. Legacy `tier` explicitly collapses membership to that singleton.
- **Singleton migration and rollback compatibility.** Add nullable `tiers`
  before host deployment, then run the separately authorized singleton
  backfill after deployment and before publishing the bot module. Existing
  NULL tiers become explicit tier3, preserving each row's existing weight in
  its singleton map. The column stays nullable for old hosts. Reads use a valid
  map only when both its strongest key and corresponding weight match legacy
  `tier` and `route_weight`; otherwise they use the legacy singleton. Malformed
  maps fall back without raising, and unknown legacy tiers read as tier3. This
  detects old writers changing either mirror. An older module's full single-tier
  write collapses a map. No automatic migration runs.
- **Pool viability is guarded by bot management.** Create, update, delete and
  disable refuse a previously viable tier becoming non-viable (409), unless
  `allow_empty_tier` / `--allow-empty-tier` is explicit. A viable pool has an
  enabled, agent-type, non-pointer member and either one candidate or a
  positive-weight candidate. Existing empty pools do not block unrelated
  edits. The host's usage-driven enable/disable primitive bypasses this guard.
  Host contract v29 exposes pure `bot_tier_pools(configs)` with the names that
  can win each tier's draw, including weightless sole candidates.
- **Chat tier stays singular.** On first routing or accepted re-bot, record the
  requested tier if the bot serves it, otherwise tier2 if served, otherwise
  its strongest tier. Existing chats retain their persisted tier. A multi-tier
  bot can therefore serve tier1 without mislabeling its default tier2 chats.
- **The reference ladder** (as of adoption): tier0 = frontier flagship,
  tier1 = strong general model, tier2 = capable mid-range (multiple members),
  tier3 = everything else. The ladder is per-user data maintained via the bot
  CLI; the PRD fixes the ladder's semantics, not its membership.
- **Unified filter resolution.** All targeting signals are filters of the
  same kind over one candidate universe; there is no precedence chain. This
  replaces the earlier most-specific-wins chain (bot-name pin beating a
  backend pin beating a tier request), including the backend pin's special
  preference order (a config named after the backend, then `default`) and
  its synthetic backend-only last resort, all removed for the simplest
  possible logic. Resolution:
  1. Candidate universe: the user's enabled bot configs (a user with no
     configs of their own resolves against the system default user's),
     excluding pointer (ref) configs.
  2. The given filters (bot name, backend, tier) intersect over the
     universe. Tier-filter candidacy additionally excludes model-type
     entries, and matches set membership, with legacy unset tier counting as tier3. Explicit name
     and backend pins can therefore reach model-type configs without allowing
     them into automatic routing pools. Type is the whole rule: no backend
     value is special-cased, so every inline query bot is kept out of the
     pools by being model-type.
  3. Exactly one candidate: used directly; weight is not consulted.
  4. Multiple candidates: a tier-filtered pool uses smooth weighted round-robin
     by route weight. Its route state is owner-scoped and persisted between
     draws, so integer-equivalent weights converge deterministically without
     clustering from random chance. A non-tier pool uses weighted random
     selection by route weight.
  5. No filters given, or an empty intersection: resolve again as a tier2
     filter (the system default) through the same selection logic, with a
     logged warning when filters produced an empty set.
  6. An empty tier2 fallback pool falls back to the global default bot
     (the user's default config, then the system default user's, then a
     hard error if nothing exists). Routing never fails a chat over a mere
     data gap.
- **Each tier membership has an independent weight.** A tier draw, viability
  check and effort preflight use only that tier's weights. Smooth weighted
  round-robin state is isolated by owner, tier and the hash of that tier's
  sorted name/weight tuples. Editing tier1 weights cannot change tier2's pool
  key, weights or sequence; concurrent tier2 traffic still advances its counters.
  Backend-only multi-candidate draws use the legacy strongest-tier weight mirror.
  Weights describe new-chat shares, not token or cost shares; adding a tier
  does not change provider prices, subscriptions or quota limits.
- **Route weight gates the draw, not membership.** Weight is consulted only
  when the filters produce multiple candidates: smooth weighted round-robin in
  a tier pool, weighted random selection in any other pool. Both allocate
  *new-chat draws* in proportion to positive route weights; unset weight counts
  as zero, and a zero-weight bot never wins a draw against weighted peers (a
  pool whose total weight is zero counts as empty). A sole
  candidate is used regardless of weight. A draw happens when a new chat is
  resolved; later turns reuse that chat's persisted bot unless explicitly
  re-botted. Weight therefore does not equalize turns, relay requests, tokens,
  or cost, and old or explicitly pinned chats do not consume a pool draw. This
  supersedes the earlier contract where unset
  weight excluded a bot from tier pools entirely (itself decided after
  reverting a code default of 1.0); the opt-in spirit survives as "a
  weightless bot never wins a multi-candidate draw", while single-candidate
  resolution stays trivially simple.
- **No skill-to-tier mapping.** Skills are never statically bound to tiers.
  This reverses the phase-0 design (a hard-coded static allowlist mapping
  cheap-safe routine skills to tier2, everything else to tier3), which is
  removed entirely: a per-skill label ignores task shape, the same reason
  static topic-to-bot bindings were rejected. Bot targeting on a dispatch is
  expressed only as filters (bot name, backend, tier), never derived from
  the skill.
- **Tier2 is the dispatch-side default.** When a dispatch carries no
  filters, or its filters produce no candidates, it resolves as
  `--tier tier2`. Note the asymmetry with the bot-side default: an
  unlabeled bot config still counts as tier3 (bottom of the ladder), while
  an unfiltered dispatch requests tier2 (capable mid-range). Nothing
  defaults to tier0: the top tier is explicit user escalation only.
- **Tier roles.** Tier1 and tier2 are the daily workhorses: tier2 is the
  default, tier1 the explicit request for judgment-heavy dispatches
  (planning, review, complex coding). Tier0 and tier3 are low-frequency.
  Tier0 is used only when the user explicitly requests it (typically
  escalating after tier1 underperforms on a task); a dispatching agent
  never selects tier0 on its own judgment. This demotes tier0 from its
  earlier role as the tier judgment-heavy dispatches self-selected. Tier3
  serves cheap high-volume, low-stakes work: scheduled routines and simple
  one-shot queries.
- **Pointer (ref) bots** resolve recursively to their target with a maximum
  depth and cycle detection, both raising errors. Pointers are excluded from
  candidacy; the conventional use is the `default` config aiming at
  whichever bot is the current global default.
- **A chat keeps its bot by default, but can be re-botted within its
  backend.** With no bot named on a later message the chat's persisted bot
  is reused. Naming a different bot switches the chat: the new bot's name
  and tier are persisted and the rest of the conversation runs on it. The
  chat's `backend` stays fixed, so a bot whose effective backend differs is
  refused with a log and the chat keeps its current bot. The refusal exists
  because the inline query backends (`perplexity`, `openai`, `xai_web`,
  `xai_x`) have no session at all; among agentic bots it is trivially always
  true, since claude_code is the only one left (todo 2930).
- **A bot change takes effect on the chat's next run.** Bot resolution
  happens when a message enqueues a worker task, so a message sent into a
  chat that is already running steers the turn in flight instead
  (chat-core), and that turn stays on the bot it started with. The change
  applies to the following run. Both user-facing surfaces say so: the
  `y chat --bot` help text and the web bot picker's tooltip.
- **A re-bot requires an affirmative pin; anything else is a no-op.** The
  normal resolver cannot fail a request (an unknown name, a disabled bot, or
  a name outside the requested tier all fall back to the tier2 pool with a
  warning), which is right for a new chat and wrong for an existing one:
  the fallback bot is `claude_code` too, so it would pass the backend check
  and silently move a conversation onto a bot nobody asked for, permanently.
  A re-bot therefore resolves the name pin on its own, without the tier2
  fallback, and only a pin that resolves to a runnable config counts. Every
  other outcome (no such runnable bot, wrong backend, resolution raising on
  a broken alias chain) keeps the chat on its current bot and logs. The
  asymmetry is deliberate: for a live conversation a silent permanent
  downgrade is worse than ignoring the request, which is exactly the
  pre-2930 behavior.
- **Usage-driven Fable admission (todo 3573, owned by bot-usage).** The
  owner's named `fable` bot is enabled or disabled by the subscription
  refresh success path when Claude usage crosses 95% (see
  [`bot-usage.md`](bot-usage.md)). This feature still owns routing:
  `_universe` filters `cfg.enabled` before tier or name selection, so a
  disabled Fable is out of normal tier pools and is not an affirmative name
  pin (the pin falls back to tier2; `resolve_pinned_bot_config` returns
  none). Alias dereference (`_resolve_filters`) and `_global_default` still
  do not re-check the final target's enabled bit; that remaining bypass is
  an admission boundary, not a 3573 fix.
- **Re-bot continuity is free** because for claude_code the model and the
  relay credentials are per-invocation flags/env while the session lives in
  Claude Code's own store keyed by `external_id` + work dir: a re-botted chat
  resumes the same session under a different `--model` and relay key.
  Smoke-tested in todo
  2930 across a three-model chain (Anthropic → a different provider behind
  another relay key → back), with the session id and the full transcript
  preserved. What that test did *not* cover: all three turns used the same
  relay host, because every claude_code bot points at one CRS endpoint, so
  only the auth token and the upstream model varied. Host independence is
  argued rather than measured, and the argument is that resume state is a
  local JSONL on the VM while base-url, token and model are all rebuilt from
  the bot config on every invocation, so a different host can cost at most a
  prompt-cache miss. No context-window guard either: resuming a long session
  on a smaller-context model is a known theoretical footgun judged not worth
  code.
- **The tier request travels the whole dispatch path**: CLI flag, API
  payloads on chat creation, message send, and cross-skill notify, through
  the queue message, to the worker where the effective tier (explicit
  request, else the tier2 default) feeds resolution.
- **Dispatch policy lives in agent instructions, not code.** The framework,
  derived from Anthropic's advisor-tool guidance ("judgment concentrates in
  a few moments while most turns are mechanical"), with tier1 as the
  judgment tier (these dispatches previously self-selected tier0):
  - Judgment-concentrated sessions (planning, review, architecture verdicts,
    root-cause analysis, multi-stage coordination) request tier1; their
    artifacts are the quality lever for the whole trace.
  - Mechanical execution under an approved upstream plan omits the flag and
    inherits the tier2 default; quality is carried by the plan artifact.
  - Every-turn-hard tasks with no clean plan/execute split (deep debugging)
    run tier1 throughout.
  - Tier0 is requested only on explicit user escalation, typically after
    tier1 underperforms on a task; agents never self-select it, so
    uncertainty about difficulty resolves to tier1, never tier0.
  - Cheap high-volume, low-stakes dispatches (scheduled routines, simple
    one-shot queries) request tier3; web fact-checks pin the web-search bot
    with a synchronous wait, bypassing tiers; ordinary one-off Q&A takes
    the tier2 default.
  - The user's explicit bot pick always wins.
  - Static topic-to-bot bindings are rejected as a pass-through anti-pattern:
    the binding ignores task shape.
  The concrete dispatch guidance lands in the shared agent instructions,
  maintained separately from this PRD.
- **Exam-based grading**: a new bot is placed on the ladder only after
  running the onboarding exam (a single end-to-end task with planted
  contradictions and traps, scored on process: context reading, command
  reality, trace addressing, honest reporting, refusing destructive or
  unauthorized actions, surfacing genuine contradictions). Tier assignment
  follows the verdict via a bot config update. Calibrate empirically, never
  by model reputation.
- **Tier data changes are operations, not code changes**: performed through
  the bot CLI against the database, verified by re-resolving live.

## Testing Decisions

- Test at the resolution seam: given a set of bot configs, assert which
  config a (bot name, backend, tier) request resolves to. This is the
  external contract; do not assert on internal helper structure.
- Candidate eligibility is the highest-value target: disabled and pointer
  configs stay out of the universe; model-type configs stay out of tier
  candidacy regardless of backend; explicit model-type name/backend pins
  resolve; and unset tier counts as tier3.
- Test the filter model: single-candidate direct use (including a
  weightless sole candidate), filters intersecting (backend plus tier), a
  filter miss (unknown bot name, empty intersection) falling back to tier2,
  and an empty tier2 reaching the default bot rather than erroring.
- Test pointer dereference limits: cycle detection and max depth both raise.
- For weighted selection, test the boundary semantics rather than the
  random distribution: unset or zero weight never winning against weighted
  peers, and a zero-total-weight pool counting as empty.
- Worker-side: tier defaulting (a dispatch with no filters resolves as
  tier2; skill presence is irrelevant to the derived tier) and the
  explicit-tier override.
- Re-bot is tested on both sides of the seam: the pin resolver for what
  counts as an affirmative pin (enabled name, alias deref, and the three
  non-resolutions: unknown, disabled, outside the requested tier), and
  `run_chat` for what each outcome does to the chat (accepted change
  persists name and tier; cross-backend, unresolvable, and raising requests
  all leave the chat's bot untouched). The refusal cases matter more than
  the accept case: they are the ones that used to be a silent overwrite.
- Prior art: the agent package has dedicated config tests covering weight
  semantics, tier defaulting, and candidate eligibility; the worker package
  covers resolution fallback. Extend those rather than inventing a new
  harness.
- Data-dependent behavior (which bots are actually in a tier live) is
  verified operationally after config changes by resolving against the real
  database, not by unit tests.

## Reasoning effort

Explicit reasoning effort is a per-launch override. It is the newest explicit
value among the inputs of that launch, not a sticky chat setting, and it cannot
change while a process is already running. A message that carries effort into a
running chat (including closeout) is refused before it is appended. The API
returns 409 with "effort applies per launch; resend after the run ends". A
message without effort still steers a running chat. `y chat --at` together with
`--effort` is a CLI usage error, because a wakeup payload does not carry effort.

Effort is gated by a capability declaration on `bot_config`: `effort_levels`,
`effort_evidence`, and `effort_binding`. The binding is the sha256 of
`{backend or api_type or empty}|{stripped model}|{stripped base_url without a
trailing slash}`. It does not include the API key, tier, or route weight.
Declared levels are effective only while the stored binding still matches the
row. A model, base URL, or backend change makes the declaration stale. A name
pin that points at another bot uses the target row's declaration. The only
writer is `set_effort_capability`; a full bot-config update does not touch
these columns. The host contract is v27:
`bot_config_set_effort_capability(user_id, name, levels|None, evidence)`.
Levels are a nonempty subset of low, medium, high, xhigh, and max, and evidence
is required when levels are set. None clears the declaration.

The gate runs only when effort is explicit, and it runs before routing is
persisted. A fresh chat with no bot pin filters the candidate pool by the
level. An empty pool is an error: there is no tier2 or default fallback. An
existing chat bot, a `--bot` pin, or a re-bot target is checked on its own. If
it does not declare the level, or the re-bot target does not resolve, the
launch fails. The chat is not switched to another bot, and the previous bot is
not kept running with the effort. The
failure is a launch error (`running` false, assistant error text) and does not
reach the synthetic fallback bot. No effort leaves candidate selection, weighted
round-robin writes, and argv as they are today. An inline backend that is given
effort still raises the existing "only supported for claude_code" error.

The same check runs at admission, before any message is appended and before
any chat is created. The API answers 422 with the check's detail and writes
nothing. An unsupported level is never mapped onto a nearby level or a
different bot. The worker check stays in place for a declaration that changes
after admission and before launch.

Spawns are not recorded: the `chat_launch` history table was dropped (todo
4086) once nothing read it. Client-applied effort comes from the top-level
transcript `assistant.effort` and fills `chat_request_usage.applied_effort`
only when that column is still null. Trace view shows no per-launch lines.

Seeds are conservative and owner-scoped. They stamp only a row whose model is
still the model observed in the 2026-10-28 client/wire scan. They are not
provider confirmation, and they do not include xhigh, max, or fable. `--effort
xhigh` fails closed until a declaration is recorded with evidence.

Dispatch policy, kept in agent instructions rather than code: re-pass
`--effort medium` on every mechanical leaf launch, including fix resumes.
`xhigh` is only for a reasoning failure on a bot that declares it, one step per
sub-task, inside the review round cap. Tool, credential, and VM errors do not
escalate effort. `max` and `low` are used only when the user asks.

## Out of Scope

- Per-topic or per-skill bot bindings: explicitly rejected as the
  pass-through anti-pattern this feature replaces.
- Populating the tier3 pool: most baseline bots are currently disabled, so
  an explicit tier3 request falls back to tier2. Known data follow-up, not
  a routing defect (the no-flag path defaults to tier2, so this gap does
  not sit on the default path).
- Automatic escalation or retry on a failed run (re-dispatching to a higher
  tier): tier choice is made at dispatch time only.
- Cost- or budget-aware routing and load balancing beyond static per-bot
  weights.
- Any skill-to-tier mapping, static or learned: skills are not routing
  signals; the phase-0 static allowlist was removed, not to be replaced by
  a smarter variant.
- In-code enforcement of the dispatch policy: which tier a dispatcher asks
  for remains an agent-instruction convention; the code only honors the
  request.
- Cross-backend chat continuity: moving a chat between backends (transcript
  handoff or session translation) stays out. A bot change is honored only
  within the chat's own backend.
- xAI web/X request construction, response parsing, citations, retries, and
  inline worker lifecycle. Those belong to [xAI Inline Search Backends](xai-inline-search.md);
  this feature owns only whether those model-type bots can be selected.
- A context-window guard on re-bot: nothing stops re-botting a long chat
  onto a smaller-context model.
