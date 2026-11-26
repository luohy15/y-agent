---
title: Notification gateway
type: prd
project: y-agent
feature: notify-gateway
status: active
---

# Notification gateway

## Problem Statement

Proactive notifications are hardcoded to Telegram. Routine skills, todo awaiting
and SLA digests, reminders, routine-failure alerts, death notices, and the
homepage access notice each call the Telegram Bot API directly. WeChat can
already queue text, but nothing selects it, and turning Telegram off would
mean editing every caller. Roy wants one switch: try WeChat for the trial, keep
Telegram as the fallback, and revert by changing config.

## Solution

A host-owned gateway chooses the channel at send time. `storage.service.gateway`
reads the owner preference `notify_channel` (`wechat` or `telegram`; unset means
`telegram`), probes availability, tries the preferred channel, then the other.
`POST /api/gateway/send`, `GET /api/gateway/status`, and `PUT /api/gateway/config`
are the authenticated HTTP surface. `y gateway send|config|status` is the CLI.
There is no `y notify` command for this surface.
Admin, worker, and storage callers use the service directly because they are
not request-scoped module clients.

Availability:

- Telegram: bot token and `user.telegram_id`.
- WeChat: a `wechat_account` owned by that user, status `active`, an active
  `wechat_peer` for that user, and `heartbeat` younger than 300 seconds.
  `notify_user` does not require the maintainer gate used by manual `y wechat
  send`. A missing context token still enqueues `blocked_on_context` and counts
  as accepted; the bridge delivers it after the next inbound message.

Fallback is automatic but never silent. Whenever the channel that delivers is
not the preferred one, the result carries `fallback_from` naming the preferred
channel and a warning is logged with the reason (`unavailable` when the
preference was skipped as unavailable, `failed` when it was attempted and
returned failure). A successful send logs one info line naming the delivered
channel and the preference. There is no duplicate fan-out: WeChat delivery is a
single outbox enqueue committed only on success, so a fallback cannot leave a
copy on both channels. The send fails only when neither channel is available or
both attempts fail. The HTTP send then returns 503. WeChat notifications are
text-only. `y telegram send` stays the explicit Telegram escape hatch for images
and diagnostics.

`send` accepts an optional `reply_chat`. The chat must already exist for that
owner; a missing or foreign id returns `chat_not_found` and sends nothing
(HTTP 404). A hit prefixes the delivered text once with `/<chat_id> `, on
whichever channel actually sends, including a fallback. The same prefix on a
later inbound message routes that reply back to the chat. Telegram and WeChat
share one inbound parser for `/<chat_id>` and `/<todo_id>`
(`storage.service.reply_route` plus `storage.service.inbound_route`); a todo
prefix resolves to that todo's existing trace chat, never creates a chat, and
leaves the resulting turn's delivery unchanged. The two channels also share one
inbound quote formatter (`storage.service.inbound_quote`): a reply or selected
quote becomes a sender-headed blockquote (`[Quoted assistant]` /
`[Quoted you]`) capped at 500 characters, with media and unavailable-content
placeholders, before the turn is created. `y gateway send
--reply-chat <id>` passes it. `config` and `status` are unchanged.

For manager turns, the worker mirrors user text from web or CLI through the
gateway before execution. Neither channel echoes its own input. WeChat-origin
turns reply only through the WeChat outbox (`enqueue_reply`), regardless of
the preference. All other manager replies use the gateway, including replies
to Telegram input. Images travel separately and only when Telegram is bound.

No schema migration. The trial is `y gateway config --channel wechat`. Revert is
`--channel telegram` or `--channel default` (delete the preference).

## User Stories

1. As Roy, I want every proactive notification to go through one gateway, so a
   channel change does not require another code edit.
2. As Roy, I want the trial preference to be WeChat, so reminders and routine
   alerts arrive in WeChat while the bridge is healthy.
3. As Roy, I want Telegram to send the same text when WeChat is unavailable or
   the WeChat attempt fails, so a stale bridge does not drop the notice.
4. As Roy, I want to revert to Telegram, or back to the default, with one
   config command.
5. As Roy, I want `y gateway status` to show the preference and which channels
   can deliver, without sending a message.
6. As Roy, I want a WeChat notification to be readable plain text, including
   when the bridge has to wait for a fresh context token.
7. As Roy, I want manager text on my configured channel without receiving a
   second copy of a reply to my WeChat DM.
8. As Roy, I want a gateway prompt that asks for a reply to name its chat, so
   answering `/<chat_id> ...` on WeChat or Telegram comes back to that chat
   and not the manager thread.

## Out of Scope

- WeChat images, attachments, and files.
- Changing inbound routing or moving image delivery off Telegram.
- Deleting `y telegram send` or `POST /api/telegram/send`.
- A deployment-wide or bot-level channel default.
- Bridge recovery beyond the existing bounded outbox retry.
- Editing routine skills that still call `y telegram send`. Those callers live
  in the config checkout and move only after this host surface is deployed.

## Acceptance criteria

- Unset or unknown `notify_channel` prefers Telegram. `wechat` prefers WeChat.
  The order is preferred, then the other, and an unavailable channel is omitted.
- WeChat is available only for the owning user with an active account, an active
  peer, and a heartbeat less than 300 seconds old.
- A WeChat send failure followed by a Telegram success reports channel
  `telegram` and `fallback_from=wechat`, and logs a warning. Both attempts
  failing is a failure and does not claim a fallback.
- An unavailable preferred channel followed by the other channel succeeding
  reports that other channel and `fallback_from=<preferred>`, and logs a
  warning naming the reason. Every successful send logs one info line with the
  delivered channel; no send reaches both channels.
- Host callers for todo awaiting, the SLA digest, access notices, reminders,
  routine failures, and manager death notices use the gateway.
- A WeChat manager DM gets one outbox reply and no gateway send. A Telegram
  DM gets no mirror and one gateway reply. Web and CLI manager text gets a
  gateway mirror then a gateway reply, even when Telegram is unbound.
- `y gateway send` prints a fallback note on stderr when `fallback_from` is set.
- `y gateway send --reply-chat <id>` and `POST /api/gateway/send` with
  `reply_chat` deliver text that starts with `/<id> `. An unknown id is 404
  and neither channel is attempted. A reply that starts with `/<id> ` routes
  to that owner chat on Telegram and WeChat. WeChat still routes it when the
  bridge prepends `> ` quote lines. A miss tells the sender
  `chat /<id> not found` and does not open a manager turn.
- Deploy the host before pointing skills at `y gateway`, then set
  `--channel wechat`. Confirm one plain-text WeChat receipt, switch to
  Telegram and confirm that receipt, then restore WeChat.
