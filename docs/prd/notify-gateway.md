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

A host-owned gateway chooses the channel at send time. `storage.service.notify`
reads the owner preference `notify_channel` (`wechat` or `telegram`; unset means
`telegram`), probes availability, tries the preferred channel, then the other.
`POST /api/notify/send`, `GET /api/notify/status`, and `PUT /api/notify/config`
are the authenticated HTTP surface. `y notify send|config|status` is the CLI.
Admin, worker, and storage callers use the service directly because they are
not request-scoped module clients.

Availability:

- Telegram: bot token and `user.telegram_id`.
- WeChat: a `wechat_account` owned by that user, status `active`, an active
  `wechat_peer` for that user, and `heartbeat` younger than 300 seconds.
  `notify_user` does not require the maintainer gate used by manual `y wechat
  send`. A missing context token still enqueues `blocked_on_context` and counts
  as accepted; the bridge delivers it after the next inbound message.

A failed preferred attempt logs a warning and returns `fallback_from`. The send
fails only when neither channel is available or both attempts fail. The HTTP
send then returns 503. WeChat notifications are text-only. `y telegram send`
stays the explicit Telegram escape hatch for images and diagnostics.

Manager-turn replies, the pre-run user mirror, attached-image delivery, and
Telegram inbound replies stay on Telegram. WeChat-triggered turns still answer
on WeChat through `enqueue_reply`.

No schema migration. The trial is `y notify config --channel wechat`. Revert is
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
5. As Roy, I want `y notify status` to show the preference and which channels
   can deliver, without sending a message.
6. As Roy, I want a WeChat notification to be readable plain text, including
   when the bridge has to wait for a fresh context token.
7. As Roy, I want manager replies and inbound Telegram to keep working as they
   do today.

## Out of Scope

- WeChat images, attachments, and files.
- Moving manager reply mirroring, the pre-run mirror, or image delivery off
  Telegram.
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
- Host callers for todo awaiting, the SLA digest, access notices, reminders,
  routine failures, and manager death notices use the gateway. Telegram inbound,
  reply, pre-run, and image paths still call Telegram directly.
- `y notify send` prints a fallback note on stderr when `fallback_from` is set.
- Deploy the host before pointing skills at `y notify`, then set
  `--channel wechat`. Confirm one plain-text WeChat receipt, switch to
  Telegram and confirm that receipt, then restore WeChat.
