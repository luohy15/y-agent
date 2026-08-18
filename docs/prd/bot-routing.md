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

Bots carry a capability tier as data: a four-level ladder from tier0
(strongest, most expensive) to tier3 (baseline). Bot targeting on a dispatch
is a set of filters: bot name, backend, and tier, all of the same kind.
Resolution is one simple rule: intersect the given filters over the pool of
runnable bot configs to get candidates; exactly one candidate is used
directly; multiple candidates are picked among by weighted random selection;
no filters at all, or filters that produce an empty set, fall back to tier2,
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

## User Stories

1. As a dispatching agent, I want to request a capability tier instead of a
   bot name, so that my dispatch keeps working when the bot roster changes.
2. As a user, I want naming a bot to narrow the candidates to exactly that
   bot, so that my explicit pick is used whenever it is runnable.
3. As a user, I want a backend filter (for example perplexity) to narrow
   candidates to enabled configs with that effective backend, so that I can
   choose the runtime family without knowing config names. Since todo 2930 the
   only agentic backend is claude_code, so this filter is vestigial for agentic
   bots and only meaningfully separates them from the inline perplexity /
   openai query backends.
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
8. As an admin, I want to clear a bot's explicit tier back to unset, so that
   redundant labels matching the bot-side default can be removed.
9. As an admin, I want to weight bots within a candidate pool, so that I
   control the probability split when the filters leave multiple members.
10. As an admin, I want a bot with no positive route weight to never win a
    draw against weighted peers, so that adding a bot config never silently
    takes traffic from explicitly weighted bots.
11. As an admin, I want disabled bots and pointer bots excluded from
    candidacy, and model-type entries plus the web-search bot excluded from
    tier-based candidacy, so that auto-routing only ever lands on a real,
    runnable agent backend while explicit pins can reach inline models.
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

- **Tier is a nullable field on the bot config**, one of `tier0` (strongest)
  through `tier3` (baseline). Unset means tier3: the bot-side default tier
  is the bottom of the ladder, chosen because most bots are baseline and
  should need no label. The default was originally tier1 and was deliberately
  moved to tier3; explicit tier3 labels were then cleared as redundant.
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
     entries and the web-search bot, and matches with unset tier counting as
     tier3. Explicit name and backend pins can therefore reach model-type
     configs without allowing them into automatic routing pools.
  3. Exactly one candidate: used directly; weight is not consulted.
  4. Multiple candidates: weighted random selection by route weight.
  5. No filters given, or an empty intersection: resolve again as a tier2
     filter (the system default) through the same selection logic, with a
     logged warning when filters produced an empty set.
  6. An empty tier2 fallback pool falls back to the global default bot
     (the user's default config, then the system default user's, then a
     hard error if nothing exists). Routing never fails a chat over a mere
     data gap.
- **Route weight gates the draw, not membership.** Weight is consulted only
  when the filters produce multiple candidates: probability equals the
  bot's weight divided by the pool's total, unset weight counts as zero,
  and a zero-weight bot never wins a draw against weighted peers (a pool
  whose total weight is zero counts as empty). A sole candidate is used
  regardless of weight. This supersedes the earlier contract where unset
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
  because `perplexity` and `openai` are inline query backends with no
  session at all; among agentic bots it is trivially always true, since
  claude_code is the only one left (todo 2930).
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
  configs stay out of the universe; model-type and web-search configs stay
  out of tier candidacy; explicit model-type name/backend pins resolve; and
  unset tier counts as tier3.
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
- A context-window guard on re-bot: nothing stops re-botting a long chat
  onto a smaller-context model.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2930 | Collapse the agentic backends to claude_code only, then lift the sticky-bot rule: naming a different bot on an existing chat re-bots it (bot_name + tier persisted, `external_id` kept so the Claude session resumes), while a cross-backend change is refused and the chat keeps its bot; surfaced via `y chat --chat-id ... --bot` and the web bot picker | - | `pages/plan-2930-single-backend.md` | - | `pages/review-2930-single-backend.md` (Track A), `pages/review-2930-track-c-rebot.md` (Track C) | in progress |
| 3206 | Make model-type inline search bots explicitly pin-reachable while excluding them from tier routing, preparing px to be reclassified as `type=model` without disrupting `--bot px` or `--backend perplexity` | - | `pages/plan-3206-grok-search-bots.md` | - | `pages/review-3206-model-pin-routing.md` | reviewed (Deploy A) |
