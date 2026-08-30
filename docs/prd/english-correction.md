---
title: Automatic English Correction
type: prd
project: y-agent
feature: english-correction
status: active
---

# Automatic English Correction

## Problem Statement

The user is a non-native English speaker who writes a lot of English prose
through y-agent every day (chat messages across web, Telegram, CLI). Mistakes
repeat silently: the same tense, article, or word-choice error shows up
message after message with no feedback loop, and there's no record of what
patterns are actually recurring versus one-off typos. The existing `refine`
skill only helps when explicitly invoked for a single sentence — it has no
memory across messages and does nothing unless asked.

## Solution

A background process reviews the user's own English prose from chat history
on an hourly cadence, independent of the live chat pipeline, and for each
qualifying message produces a minimal grammar correction, an explanation, and
an error classification. Results accumulate into a personal error history
that surfaces recurring patterns over time. The user can inspect corrections
and dismiss ones that are false positives (informal style, deliberate
phrasing) so they stop polluting the history. Personalized review exercises
generated from that history are a documented future extension, not part of
this delivery.

## User Stories

1. As the user, I want an hourly background job to scan my own English chat
   messages since it last ran, so that corrections don't add latency or
   otherwise touch the live chat pipeline.
2. As the user, I want the job to skip messages that aren't my own free-typed
   prose — assistant replies, cross-skill dispatch/notify messages (identified
   by a leading bracketed meta prefix carrying `trace:` / `from:` / `to:` /
   `from_chat:` / `to_chat:` / `routine:` keys), web UI `<selection>` /
   `<instruction>` wrapper contents, and non-prose content like code blocks,
   shell commands, or file paths — so the correction set stays relevant.
3. As the user, I want the job to skip messages that are majority non-English
   (e.g. mostly Chinese), so I'm not flagged for writing in Chinese.
4. As the user, I want a message that mixes Chinese and English (common in my
   own writing) to still be processed when it's majority English, with only
   the English portions corrected and Chinese segments left alone.
5. As the user, I want each corrected message stored with only my authored
   remainder after web UI wrapper blocks are removed, plus a minimally rewritten
   corrected version, one or more error categories, and a short explanation of
   the grammar rule involved.
6. As the user, I want to see a diff between my original text and the
   corrected version, computed from the stored original/corrected pair (not
   a separately stored diff) so I can quickly see what changed.
7. As the user, I want a standalone panel (like the existing Notes/Entities/
   Routine panels) listing my corrections, independent of the chat view, so
   reviewing corrections never disrupts an ongoing conversation.
8. As the user, I want to see my recurring error patterns (e.g. most frequent
   categories, counts over time) derived from the stored correction history,
   so I know what to focus on.
9. As the user, I want to dismiss a stored correction that's a false positive
   or intentional informal language, so it's excluded from the recurring-
   pattern counts going forward.
10. As the user, I want to enable or disable automatic correction entirely
    using the existing routine on/off mechanism (`y routine`), without a
    separate feature-specific config surface.
11. As the user, I want the job to only process messages once (no duplicate
    corrections for the same message across runs).
12. As the user, I want corrections retained indefinitely with no separate
    purge policy — same retention as the chat messages they're derived from.
13. As the user, I want a CLI to write and inspect corrections
    (`y english ...`), mirroring the pattern of every other y-agent entity
    (note/entity/finance/routine), so the skill and the web panel share one
    data path.
14. As the user, I want personalized review exercises to be explicitly out of
    scope for this delivery, with the schema (error categories, occurrence
    counts) shaped so a later feature can build exercises from this data
    without a redesign.

## Implementation Decisions

- **Trigger**: a new `routine` row (existing `RoutineEntity` /
  `y routine add`) with an hourly cron `schedule`, `target_skill` pointing at
  a new agent skill (e.g. `english-correction`), and the existing `enabled`
  boolean as the on/off switch. No new config table or env var is needed —
  disabling the feature is `y routine disable <routine_id>`.
- **Decoupling from core chat**: the job never hooks into the live message
  pipeline (`worker/runner.py`, post-hooks, streaming). It reads chat history
  after the fact and writes to its own table; the chat/message write path is
  untouched.
- **Read path**: the skill reads new user messages via `y english pending`,
  which returns already-filtered eligible messages so each run only scans
  messages since the previous run — no full-table rescans.
- **Scan watermark**: the scan window is bounded by an explicit watermark in
  `user_preference` (key `english_correction_scan`, value
  `{"scanned_through_unix": <unix ms>}`), advanced by the skill via
  `y english mark-scanned <unix>` after it has written that batch's
  corrections. Neither the correction table nor the routine's `last_run_at`
  can serve as the high-water mark: an eligible message with no errors
  produces no row (so it would be re-sent to the LLM forever), and
  `fire_routine` stamps `last_run_at` to "now" before the session starts, so
  the previous value is already gone by the time the skill runs. The two-phase
  read-then-mark shape means a crashed run re-reads its batch instead of
  skipping it; re-processing stays safe via the
  `UNIQUE(user_id, chat_id, message_id)` dedup constraint. With no watermark
  yet, `pending` looks back one routine period (1 hour) rather than the whole
  chat history, and caps each run at `--limit` (default 50) messages.
- **Message eligibility filter** (deterministic Python in
  `storage/src/storage/service/english_correction.py`, applied by the skill
  via `y english pending` before calling the LLM, so it stays unit-testable):
  - `role == "user"` only (never correct assistant output).
  - Skip messages whose content starts with a bracketed meta prefix
    containing any of the dispatch/routine meta keys `trace:`, `from:`,
    `to:`, `from_chat:`, `to_chat:`, `routine:`, each immediately followed by
    a non-space character (see `api/src/api/controller/chat.py` notify
    path) — these are cross-skill relayed text, not the user's own writing.
    The rule is keyed on those known meta keys, NOT on any leading `[...]`:
    dispatches sent without a trace-id still carry
    `[from:... from_chat:... to_chat:...]` and are skipped, while authored
    prose that opens with a bracket (e.g. `[draft] can you review this`) is
    still scanned. The colon-must-be-followed-by-non-space requirement is
    what keeps genuine prose like `[note to: myself] remember to check the
    worker logs` from being misread as a dispatch prefix, since real
    prefixes are always `from:manager` / `to_chat:17990a`, never
    `from: manager`.
  - Skip pure key=value machine payloads (e.g. a dispatch body
    `ticker=GOOGL repo=/... log_threshold=material`): when every
    whitespace-separated token contains `=`, the message is a relayed
    payload, not prose. Authored text that merely contains `=` (e.g.
    `set DEBUG=true and it worked`) has bare tokens and is kept.
  - Remove complete `<selection>...</selection>` and
    `<instruction>...</instruction>` blocks before applying the remaining
    eligibility rules; persist only the authored remainder. Multiple and nested
    blocks are removed, while malformed or unclosed wrapper markup skips the
    message rather than risking ingestion of quoted content.
  - Skip non-prose messages (code blocks, shell commands, file paths) via a
    cheap heuristic.
  - Skip messages that are not majority-English by word/character count;
    for majority-English mixed messages, correct only the English spans.
- **New entity** `english_correction` (`storage/src/storage/entity/`):
  `id` (PK), `user_id` (FK), `correction_id` (public string ID), `chat_id`
  (public chat id), `message_id` (the source message's own `id` field),
  `message_at` / `message_at_unix` (the source message's own timestamp, ISO
  8601 and unix ms — the watermark math and every time shown in the panel
  refer to when the message was written, not when the hourly run stored it),
  `original_text` (the authored remainder after UI wrapper removal),
  `corrected_text`, `error_categories` (JSON string array, free-form categories
  emitted by the LLM — no fixed enum in v1), `explanation` (text), `dismissed`
  (boolean, default false), `created_at`. The diff itself is computed at read
  time from `original_text`/`corrected_text`, not stored.
  Dedup: a message is only processed once — the skill checks
  `chat_id + message_id` before writing (or relies on the time-bounded scan
  window plus a unique constraint on `(user_id, chat_id, message_id)`).
- **Standard stack**: Repository → Service → Controller → CLI, mirroring
  every other entity in the codebase:
  - `y english add ...` — write path, called by the skill once per corrected
    message.
  - `y english list` / `y english get <correction_id>` — read path, shared by
    manual inspection and the API controller backing the web panel.
  - `y english dismiss <correction_id>` — marks `dismissed=true`.
  - `y english pending [--limit N] [--since <unix|iso>]` — the skill's read
    path: emits the eligible unscanned messages as JSON (machine interface),
    plus the batch's `scan_through_unix`.
  - `y english mark-scanned <unix>` — advances the scan watermark once the
    batch's corrections are written.
  - `list` supports the standard time-filter flag set (`--on` /
    `--from`/`--to` / `--created-on` etc.), canonical field `created_at`.
- **API**: new controller under `api/src/api/controller/` following the
  existing REST conventions (list/get/dismiss), consumed by the web panel.
- **Web**: a new standalone panel (parallel to `NoteList` / `EntityList` /
  `RoutineList`) listing corrections with diff + explanation + categories,
  plus an aggregate recurring-patterns view (category counts over time,
  excluding dismissed rows) computed from the same list data — no separate
  rollup table in v1.
- **ID convention**: `correction_id` is the public string ID exposed via API/
  CLI; the integer PK stays internal, per the repo-wide ID convention.

## Testing Decisions

- Unit-test the message eligibility filter in isolation (dispatch-prefix
  skip, non-prose skip, majority-English threshold, mixed-language English-
  span extraction) since it's pure logic with clear inputs/outputs.
- Unit-test the dedup/high-water-mark logic (a message processed once does
  not get reprocessed on the next hourly run).
- Service-layer tests for `english_correction` CRUD + dismiss, following the
  existing repository/service test patterns used for other entities (e.g.
  `note`, `routine`).
- Do not test LLM correction quality itself (non-deterministic); test that
  the skill's write call produces a well-formed `english_correction` row
  given a mocked/example LLM output.
- Web panel: component-level test for list rendering + dismiss action,
  consistent with existing panel test coverage (if any); no new pattern
  needed here.

## Out of Scope

- **Personalized review exercises** — deferred; the schema (categories,
  counts, dismissed flag) is designed to support building this later without
  migration, but generation/delivery (web section vs. scheduled Telegram
  quiz, etc.) is a separate future feature.
- **Inline chat-bubble annotations** — corrections are not surfaced inside the
  live conversation view or its message bubbles (the `chat` module's `shell`
  surface since todo 3042); the standalone panel is the only surface. Live,
  in-conversation nudging is explicitly not this feature's job.
- **Real-time/synchronous correction** — no per-message latency added to the
  live chat pipeline; hourly batch only.
- **Automated retention/purge** — corrections are kept indefinitely, same as
  chat messages; no auto-expiry job.
- **Fixed error-category taxonomy** — v1 stores whatever categories the LLM
  emits as free-form strings; a curated/constrained taxonomy is a later
  refinement once real data exists.
- **Non-chat-surface English** (e.g. commit messages, todo descriptions,
  note content) — scope is limited to user chat messages read from the
  `chat` table.
- **Vocabulary tracking** — word-level known/unknown state, seeded frequency
  word lists, and the scan-and-mark flow are owned by
  [english-vocabulary](english-vocabulary.md); this feature stays at the
  message/grammar level. They share the English panel and `y english` CLI
  namespace but no tables.
- **Replacing the `refine` skill** — `refine` remains the on-demand, explicit
  single-sentence helper; this feature is the passive, automatic, historical
  counterpart. The two are not merged.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2871 | Storage / API / `y english` CLI / web panel + detail view built; `english-correction` skill and hourly routine registered (disabled) | `pages/design-2871.html` | `pages/plan-2871-english-correction.md` | - | `pages/review-2871-english-correction.md`, `pages/review-2871-english-correction-s5-skill.md` | implemented |
