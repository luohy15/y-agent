---
title: Telegram Delivery
type: prd
project: y-agent
feature: telegram-delivery
status: active
---

# Telegram Delivery

## Problem Statement

Telegram is the mobile surface for y-agent: the owner dispatches and reads
session results from their phone without opening the web app. Before this
feature, Telegram delivery was split across two mechanisms — a DM to the
owner's `user.telegram_id`, and a per-topic forum group where each named
session (`chat.topic`) got its own bound thread and its own automatic replies,
photos, and pre-run mirrors. The forum group added an inbound attack surface
(group messages reachable the same code paths as private ones), a second
binding table (`tg_topic`) with no relationship to the session-topic registry,
and a delivery policy that silently dropped a failed non-manager reply instead
of ever reaching a human or a parent session. Roy uses Telegram DM for
dispatch and the web app for detail; the forum group's per-topic mirror never
became the primary way Roy read a non-manager session's outcome.

## Solution

Only the manager session (`chat.topic == "manager"`, the owner's DM) is
eligible for automatic Telegram delivery: final replies, pre-run message
mirrors, and immediate image attachments. A non-manager named session or an
anonymous chat gets no automatic Telegram push — its outcome lives in web
persistence, unread state, and existing parent-callback / todo-inbox
mechanics, not a Telegram message. This is a narrowing of transport
*eligibility*, not a change to session addressing: `chat.topic` as a named
dispatch address (`y chat --topic dev`), DTO round-trip, topic/trace lookup,
root-topic singleton behavior, and manager-callback rejection are a completely
separate concern (owned by [chat-core](chat-core.md)) and are untouched here.

Terminal delivery (error/timeout) for a non-manager or anonymous chat routes
to a valid same-owner/same-trace parent session when one exists
(`death_delivery.deliver_death`), otherwise to the existing guarded
stalled-claim inbox path; a won stalled claim still escalates to the owner's
DM. These trace-level alerts, plus the reminder delivery and routine-failure
alerts in `admin/handler.py` and the liveness watchdog
(`worker/steps/check_trace_liveness.py`), are **not** per-topic session
replies — they always resolve to the owner's DM directly and are unaffected by
the manager-only gate.

Inbound Telegram is now private-chat-only: the webhook rejects (silently, no
reply into the retired group) any update whose `chat.type != "private"` before
any photo download, command, or chat write. Private `/bind`, `/unbind`,
`/start`, `/clear` (which now unconditionally restarts the manager session —
there is no non-manager forum branch left), explicit `/<chat_id>` and
`/<todo_id>` routing, images, and append-or-steer delivery are all preserved.

The `tg_topic` binding table, its repository/service/entity/DTO/API
registration, forum-topic auto-discovery, thread lookup, and General-topic
fallback are removed from the codebase. `y telegram send --topic` (and the
`SendMessageRequest.topic` request field) is retired: the CLI and the
`/api/telegram/send` endpoint only ever address the owner's DM now.

Explicit `y telegram send --image` (`POST /api/telegram/send`) posts upload
bytes straight to Telegram and SSH-fetches `images` paths via
`send_telegram_photo_reference`. It does not persist a copy under
`assets/images/`, and an undeliverable photo is a hard 502 rather than a
best-effort drop.

## User Stories

1. As a user, I want a completed manager-session turn to be pushed to my
   Telegram DM, so that I learn of completion without watching the screen.
2. As a user, I want a non-manager named session's completion to stay web-only
   (no Telegram push), so that my DM isn't a mixed stream of every dispatched
   sub-session.
3. As a user, I want a failed or timed-out non-manager session to notify a
   valid parent session, or fall back to the existing stalled-todo inbox and
   DM escalation, so that a silent failure never simply disappears.
4. As a user, I want explicit routine alerts (daily-scan, weekly-review,
   org-review, openrouter-credit-check, news-ingest-monitor) to keep arriving
   on my DM regardless of the manager-only session gate, since they are
   explicit alerts, not session replies.
5. As a user, I want a message sent into the (retired) Telegram group to be
   silently ignored, so that no stray input reaches bind/unbind/chat-write
   code paths.
6. As an operator, I want `chat.topic` as a named dispatch address to be
   completely unaffected by this change, so that `y chat --topic dev` and
   trace/topic lookup keep working exactly as before.

## Out of Scope

- `chat.topic` as a named session-dispatch address, DTO round-trip,
  topic/trace resolution, root-topic singleton, trace prefixes, and manager
  callback rejection — owned by [chat-core](chat-core.md).
- Rerouting non-manager sessions' replies to the manager DM, attribution
  headers, or a web-link formatter for DM-mixed content. Roy explicitly
  rejected this expansion (see `pages/plan-3460-telegram-group-removal.md`).
- Session-tree-recovery's persisted dispatch edges and sweeper — a separate,
  not-yet-implemented proposal; this feature does not assume it exists.
- Retiring the physical `tg_topic` table, existing group history, thread
  bindings, or bot group membership. That is a maintainer-only follow-up
  (todo 3468 sub-task 7): the table stays in place, unmapped by the ORM, until
  the maintainer backs it up and drops it by hand.
- Updating `docs/prd/chat-core.md`, `docs/prd/README.md`,
  `docs/prd/bot-usage.md`, and `docs/prd/english-vocabulary.md` wording. Those
  files carry unrelated uncommitted work owned by other traces at the time of
  this delivery and were left untouched; a follow-up should reconcile
  chat-core's "bound Telegram topic" wording (chat-core.md around user story
  50 and its Telegram-adjacent-subsystem note) to say manager-only DM once
  that file is clear to edit.
- Migrating the external routine-skill callers
  (`.agents/skills/{daily-scan,weekly-review,org-review,
  openrouter-credit-check,news-ingest-monitor}/`) off `--topic` /
  `notify_topic` — those live outside this repository and are delivered as
  todo 3468 sub-task 6 by a separate session.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3460 | Read-only inventory and removal proposal for the Telegram group and per-topic delivery; corrected to manager-only-DM policy after Roy's scope feedback | - | `pages/plan-3460-telegram-group-removal.md` | - | - | proposal approved |
| 3468 | Implemented the manager-only gate (worker eligibility, immediate-attachment API path, `deliver_death` topic branch), private-only inbound webhook gate with forum discovery/`/clear`-branch/thread-plumbing removal, and full `tg_topic` API/service/repository/entity/DTO removal and `y telegram send --topic` retirement; routine-caller migration (sub-task 6) delivered separately | - | `pages/plan-3460-telegram-group-removal.md` | - | `pages/review-3468-telegram-removal.md` | shipped |
| 3474 | Explicit send image transport: uploads posted as bytes (no EC2 store), `images` delivered via `send_telegram_photo_reference` with `require_exists=False`, hard 502 on undeliverable | - | `pages/plan-3474-telegram-send-image.md` | - | `pages/review-3474-telegram-send-image.md` | shipped; verification: `pages/deploy-3474-telegram-send-image.md` |
