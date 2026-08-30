---
title: English Vocabulary (v1 scan-and-mark)
type: prd
project: y-agent
feature: english-vocabulary
status: active
---

# English Vocabulary (v1 scan-and-mark)

## Problem Statement

The user is growing his English vocabulary toward two concrete goals:
understanding colleagues by ear in meetings and expressing himself without
vocabulary limits. He does not currently know where his gaps are within the
core English vocabulary — which of the most common few thousand words he
actually doesn't know. Without that baseline inventory, any later study work
(drills, spaced repetition, proficiency tracking) has nothing to aim at, and
an ad-hoc markdown word list would die from hand-editing friction and could
not support the data-backed features planned on top of it.

## Solution

v1 is the simplest possible baseline inventory: seed the must-know top-3k /
top-5k / top-10k English words into the existing `y english` product, let the
user read through them in frequency order in short sittings, and mark the
ones he does not know. Everything he scans past without marking is recorded
as known. The output is a durable per-word known/unknown map over the core
vocabulary: progress percentages per tier, and a concrete list of unknown
words that becomes the study queue for later features. It lives inside the
existing English panel and `y english` CLI namespace — one English-learning
product, not a second silo and not a markdown tracker.

## User Stories

1. As the user, I want the top-3k / top-5k / top-10k must-know English words
   seeded into the system from a single frequency-ranked source, so that the
   scan covers exactly the core vocabulary worth auditing.
2. As the user, I want seeding to be idempotent (re-running it never
   duplicates words or resets my existing marks), so the list can be
   refreshed or extended safely.
3. As the user, I want to scan words in frequency order (most common first),
   so the early sessions cover the highest-value words and the easy known
   words go quickly.
4. As the user, I want to mark a word as unknown with a single tap/click
   while scanning, so a scan sitting stays fast and low-friction.
5. As the user, I want to un-mark a word in the same sitting if I tapped it
   by mistake, so marking mistakes are cheap to fix.
6. As the user, I want to confirm a scanned batch so every word in it I did
   not mark unknown is recorded as known, so "read past it silently" is
   enough to register knowledge and I never have to tap thousands of known
   words individually.
7. As the user, I want the scan to resume exactly where I left off (first
   unreviewed word in rank order) across sessions and devices, so I can chip
   away at 10k words in short idle gaps without tracking my place manually.
8. As the user, I want progress visible per tier (3k / 5k / 10k: how many
   reviewed, how many unknown, percent complete), so I can see the baseline
   forming and know how far there is to go.
9. As the user, I want a view of all my unknown words, so the scan's output
   is a usable study queue rather than a buried flag.
10. As the user, I want to flip an unknown word to known later (after I've
    learned it), so the map stays current as I improve.
11. As the user, I want all of this inside the existing English panel as a
    sibling to the corrections view, so English learning stays one product
    with one home.
12. As the user, I want CLI parity under the `y english` namespace (seed,
    list, mark, stats), so scripts and agent sessions share the same data
    path as the panel, mirroring every other y-agent entity.
13. As the user, I want the word state stored in the database (not a
    markdown page), so per-word state survives, is queryable, and can back
    the deferred proficiency/exercise/SRS features without a redesign.
14. As the user, I want the v1 schema shaped so the deferred features
    (know-vs-use proficiency, exercises, SRS, auto-capture) can extend it
    rather than replace it, so the scan effort is never thrown away.

## Implementation Decisions

- **Data-backed inside `y english`, not markdown**: settled by Roy on
  2026-08-30 (resolving the open scope question in todo 2903). Per-word state
  across 10k rows is data that wants a real store; the feature joins the
  existing English product (host-owned entity → repository → service →
  controller → CLI → English panel slices, same stack as
  `english_correction`), not a new module and not a pages/ tracker.
- **One ranked source, tiers derived**: seed from a single open-licensed,
  frequency-ranked English word list (recommendation: derive from the
  MIT-licensed `wordfreq` dataset), cleaned to lowercase alphabetic lemma
  entries. Each word stores its frequency `rank`; tier membership (3k / 5k /
  10k) is computed from rank (`rank <= 3000` etc.), not stored, since the
  tiers are cumulative bands of one ranking. The exact generation script and
  cleaning rules are plan-time details; the requirement is a reproducible,
  redistributable ranked list of 10k lemmas.
- **Word state machine**: each seeded word is `unseen` by default. Marking
  transitions it to `unknown` (explicit tap) or `known` (batch confirm of
  the words left unmarked in a reviewed batch). Both marks are reversible;
  `unknown → known` is the expected long-term transition as words are
  learned. `marked_at` records when the state last changed.
- **Resume point is derived, not stored**: because batch confirm flips every
  reviewed word out of `unseen`, the scan position is simply the first
  `unseen` word in rank order. No cursor/watermark state is needed, and
  resume works across devices for free because state lives server-side.
- **New entity** `english_word`: integer PK internal, public string
  `word_id`, `user_id` FK, `word` (unique per user), `rank`, `status`
  (`unseen` / `known` / `unknown`), `marked_at`, `created_at`. Rows are
  per-user (seeding runs as the CLI user), per the repo-wide ID and
  ownership conventions.
- **Seeding is a CLI action, not a migration**: `y english vocab seed`
  inserts the ranked list for the invoking user, skipping words that already
  exist (idempotent, mark-preserving). The hand-applied SQL migration
  creates only the table.
- **CLI**: a `y english vocab` subgroup — `seed`, `list` (filter by status /
  tier, standard time-filter flags), `mark <word...> --unknown|--known|--unseen`,
  `stats` (per-tier totals / reviewed / unknown / percent). Batch confirm is
  a bulk mark (the API accepts a list of word ids → status; the CLI accepts
  multiple words).
- **API**: vocabulary routes join the existing host english controller
  surface (list / bulk-mark / stats), consumed by the panel.
- **Web**: a `vocabulary` sub-tab in the existing English panel beside
  `corrections` / `patterns`, with two views: the scan view (a batch of
  words from the resume point in rank order, tap-to-toggle unknown, one
  confirm action that marks the rest known and advances) and the unknown-
  words list (with per-word flip back to known). Tier progress renders as
  compact per-tier counts/bars above the scan view.

## Testing Decisions

- Service-layer tests mirroring the existing `english_correction` patterns:
  seed idempotency (re-seed preserves marks, adds only missing words), mark
  transitions (unseen → unknown / known, reversals, bulk mark), stats math
  (cumulative tier bands, unknown counts, reviewed percentages), and the
  derived resume point (first unseen by rank) after partial batch confirms.
- Test external behavior through the service/CLI surface, not repository
  internals.
- No LLM involvement in v1, so no non-deterministic paths to exclude.
- Panel: component-level coverage for scan toggle + batch confirm consistent
  with existing English panel coverage; no new test pattern.

## Out of Scope

Deferred by Roy's 2026-08-30 v1 narrowing (the full-system interview in chat
2f35e0 is obsolete and must not be resumed as a requirements source):

- **Know-vs-use proficiency** — v1 tracks binary known/unknown only; the
  passive-recognition vs active-production distinction is a later extension
  (the `status` field can widen without discarding v1 marks).
- **Spare-time exercise items** — no drills attached to words in v1; the
  unknown list is the raw study queue.
- **Spaced repetition** — no scheduling, review intervals, or due dates.
- **Auto-capture** — words do not flow in from the correction loop
  (todo 2871 / [english-correction](english-correction.md)) or the study
  plan (todo 2523); the seeded frequency list is the only v1 source, and
  there is no manual single-word add either.
- **Definitions / translations / example sentences** — the scan shows bare
  words; looking up an unknown word happens outside the tool in v1.
- **Phrases, collocations, multi-word entries** — single-word lemmas only.
- **Grammar-correction history** — message-level corrections, categories,
  and dismissals are owned by [english-correction](english-correction.md);
  this feature owns word-level vocabulary state. The two share the English
  panel and `y english` namespace but no tables.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2903 | v1 scan-and-mark PRD settled; design + implementation pending | - | - | - | - | planned |
