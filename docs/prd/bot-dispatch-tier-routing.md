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
(strongest, most expensive) to tier3 (baseline). A dispatcher can request a
tier instead of naming a bot, and the system picks a bot from that tier's pool
by weighted random selection. Explicit pins always win: naming a bot or a
backend bypasses tier routing entirely. Bot targeting on a dispatch is
expressed as either a bot name or a tier; when both are empty the dispatch
resolves as a tier2 request, the system default. Skills are never statically
bound to tiers. An empty tier pool falls back to the global default bot with
a warning rather than failing.

Which tier to request is governed by a documented dispatch policy, not code:
strong models go where judgment concentrates in a trace (planning, review,
verdicts, root-cause analysis), mechanical execution under an approved plan
inherits the default, and tasks that are hard on every turn get the strong
model throughout. New bots are graded into the ladder empirically via a
standardized onboarding exam, not by intuition. Tier membership stays data:
inspectable and editable through the bot CLI, never memorized in instructions.

## User Stories

1. As a dispatching agent, I want to request a capability tier instead of a
   bot name, so that my dispatch keeps working when the bot roster changes.
2. As a user, I want an explicitly named bot to always win over backend and
   tier heuristics, so that my pick is never second-guessed by routing.
3. As a user, I want a backend pin (for example codex) to resolve to a
   matching enabled bot config, so that I can choose the runtime family
   without knowing config names.
4. As a user, I want a chat with no bot, backend, or tier specified to
   resolve as a tier2 request, so that unspecified dispatches land on a
   capable mid-range bot by default without any routing knowledge.
5. As an admin, I want each bot's tier stored on its config and visible in
   the bot list, so that tier membership is queryable data rather than
   something agents memorize.
6. As an admin, I want unlabeled bots to default to the lowest tier, so that
   the majority of bots need no explicit tier configuration.
7. As an admin, I want to clear a bot's explicit tier back to unset, so that
   redundant labels matching the bot-side default can be removed.
8. As an admin, I want to weight bots within a tier, so that I control the
   probability split when a tier has multiple members.
9. As an admin, I want a bot with no positive route weight kept out of tier
   pools, so that adding a bot config never silently opts it into
   auto-routing; joining a pool is an explicit act.
10. As an admin, I want disabled bots, pointer bots, model-type entries, and
    the web-search bot excluded from tier pools, so that auto-routing only
    ever lands on a real, runnable agent backend.
11. As a dispatching agent, I want skills never statically bound to tiers,
    so that tier choice reflects each dispatch's task shape instead of a
    stale per-skill label.
12. As a dispatching agent, I want the top tier reachable only by explicit
    opt-in (bot pin or tier request), so that the most expensive model is
    never chosen by a default.
13. As a dispatching agent, I want an explicit tier request to override the
    tier2 default, so that I can escalate or downgrade any dispatch
    per-instance.
14. As a user, I want an empty tier pool to fall back to the default bot with
    a logged warning, so that a data gap degrades service quality instead of
    breaking the chat.
15. As a user, I want an existing chat to keep the bot it started with, so
    that a conversation's model identity is stable across turns.
16. As an examiner, I want to grade a new bot through a standardized exam
    before placing it on the ladder, so that tier assignment reflects
    measured behavior in this system rather than reputation.
17. As a dispatching agent, I want a documented policy for when to request
    the top tier versus inheriting the default, so that dispatch decisions
    follow where judgment concentrates instead of static topic bindings.
18. As a dispatching agent, I want one-shot web fact-checks pinned to the
    web-search bot with a synchronous wait, so that grounded single-turn
    queries bypass tier routing and return their answer inline.
19. As an admin, I want pointer bots that alias another config, so that the
    global default can be re-aimed at any bot by updating one reference.
20. As an admin, I want pointer resolution protected against cycles and
    unbounded depth, so that a misconfigured alias chain fails loudly instead
    of hanging resolution.
21. As a secondary user without my own bot configs, I want backend pins and
    default resolution to fall back to the system default user's configs, so
    that a fresh account can chat before configuring anything.

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
- **Resolution priority chain**, most specific wins, evaluated in order:
  1. Bot-name pin: exact config lookup for the user; no cross-user fallback.
     A named bot beats every other signal, including a backend pin on the
     same request.
  2. Backend pin: find an enabled config with a matching effective backend,
     preferring a config named after the backend itself or `default`, with
     cross-user fallback to the system default user, and a synthetic
     backend-only config as last resort.
  3. Tier request: only consulted when neither pin matched; weighted random
     pick from the tier's pool. When no tier was requested either, the
     effective tier is tier2 (the system default), so an unspecified
     dispatch is equivalent to an explicit tier2 request.
  4. Default: the user's default config, then the system default user's, then
     a hard error if nothing exists. Reached only when the effective tier's
     pool is empty (the empty-pool fallback), never as a primary path.
- **Tier pool membership** requires all of: enabled, not a pointer (ref)
  config, not a model-type entry, not the web-search backend, tier matches
  (with unset counting as tier3), and an explicitly positive route weight.
- **Unset route weight excludes a bot from pools.** This is a deliberate
  contract, decided after trying the opposite: an earlier fix defaulted unset
  weight to 1.0 in code, and was reverted in favor of setting the weight
  explicitly in config data. Rationale: pool membership should be an explicit
  per-bot opt-in, and the fix belongs in data, not in a code default that
  opts in every config retroactively.
- **Weighted selection** within a pool: probability equals the bot's weight
  divided by the pool's total weight. Setting weight to zero pauses a bot
  from auto-routing without disabling it.
- **No skill-to-tier mapping.** Skills are never statically bound to tiers.
  This reverses the phase-0 design (a hard-coded static allowlist mapping
  cheap-safe routine skills to tier2, everything else to tier3), which is
  removed entirely: a per-skill label ignores task shape, the same reason
  static topic-to-bot bindings were rejected. Bot targeting on a dispatch is
  expressed as exactly two signals: a bot name or a tier.
- **Tier2 is the dispatch-side default.** When a dispatch carries neither a
  bot name nor a tier, it resolves as `--tier tier2`. Note the asymmetry
  with the bot-side default: an unlabeled bot config still counts as tier3
  (bottom of the ladder), while an unlabeled dispatch requests tier2
  (capable mid-range). Nothing defaults to tier0: the top tier is explicit
  opt-in only.
- **Empty-pool fallback**: when a requested tier has no qualified bots,
  resolution logs a warning and proceeds down the chain to the default bot.
  Routing must never fail a chat over a data gap.
- **Pointer (ref) bots** resolve recursively to their target with a maximum
  depth and cycle detection, both raising errors. Pointers are excluded from
  tier pools; the conventional use is the `default` config aiming at whichever
  bot is the current global default.
- **Chats are sticky to their bot.** Once a chat has a persisted bot name, a
  different bot on a later message is ignored with a log; tier resolution
  happens per run but cannot re-bot an existing chat.
- **The tier request travels the whole dispatch path**: CLI flag, API
  payloads on chat creation, message send, and cross-skill notify, through
  the queue message, to the worker where the effective tier (explicit
  request, else the tier2 default) feeds resolution.
- **Dispatch policy lives in agent instructions, not code.** The framework,
  derived from Anthropic's advisor-tool guidance ("judgment concentrates in
  a few moments while most turns are mechanical"):
  - Judgment-concentrated sessions (planning, review, architecture verdicts,
    root-cause analysis, multi-stage coordination) request tier0; their
    artifacts are the quality lever for the whole trace.
  - Mechanical execution under an approved upstream plan omits the flag and
    inherits the tier2 default; quality is carried by the plan artifact.
  - Every-turn-hard tasks with no clean plan/execute split (deep debugging)
    run tier0 throughout.
  - Nothing-to-plan one-shots skip tiers: web fact-checks pin the web-search
    bot with a synchronous wait; ordinary one-off Q&A takes the tier2
    default.
  - The user's explicit bot pick always wins; when difficulty is uncertain,
    treat as tier0 (a weak bot failing a hard task costs more than a strong
    bot doing an easy one).
  - Static topic-to-bot bindings are rejected as a pass-through anti-pattern:
    the binding ignores task shape.
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
- Pool eligibility is the highest-value target, because the production bug
  lived there: unset weight excluded, zero weight excluded, disabled
  excluded, pointer and model-type and web-search excluded, unset tier
  counted as tier3.
- Test the precedence rules: a bot-name pin beating a backend pin on the
  same request, pins beating tier requests, explicit tier beating the tier2
  default, and the empty-pool fallback reaching the default bot rather than
  erroring.
- Test pointer dereference limits: cycle detection and max depth both raise.
- For weighted selection, test eligibility and single-member determinism,
  not the random distribution.
- Worker-side: tier defaulting (no bot, no tier resolves as tier2; skill
  presence is irrelevant to the derived tier) and the explicit-tier
  override.
- Prior art: the agent package has dedicated config tests covering weight
  exclusion, tier defaulting, and pool membership; the worker package covers
  resolution fallback. Extend those rather than inventing a new harness.
- Data-dependent behavior (which bots are actually in a tier live) is
  verified operationally after config changes by resolving against the real
  database, not by unit tests.

## Out of Scope

- Per-topic or per-skill bot bindings: explicitly rejected as the
  pass-through anti-pattern this feature replaces.
- Populating the tier3 pool: most baseline bots are currently disabled, so
  an explicit tier3 request falls through to the default bot. Known data
  follow-up, not a routing defect (the no-flag path defaults to tier2, so
  this gap no longer sits on the default path).
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
- Re-botting an existing chat mid-conversation.
