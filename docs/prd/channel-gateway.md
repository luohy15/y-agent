---
title: IM channel gateway
type: prd
project: y-agent
feature: channel-gateway
status: active
---

# IM channel gateway

A bound channel is not necessarily reachable. The Gateway panel and
`y gateway channels status` let a signed-in user check both facts for Telegram and
WeChat without sending a message. They show the notification preference and
fallback order. Unbinding a channel does not rewrite that preference.

## User stories and acceptance

1. A user sees Telegram first and WeChat second, with the same health and peer
   in the panel and CLI. A bound Telegram peer without a configured bot is
   unavailable, not unbound.
2. Any admitted user can distinguish their own pending confirmation, an active
   peer with a stale bridge, a healthy binding, and a revoked peer. Account and
   peer IDs, heartbeat and poll ages, last delivery error and outbox counts
   describe only that user's peer and never include message text, credentials,
   or another user's account or peer. An unadmitted caller sees WeChat as
   unsupported.
3. Bind guidance directs users to the Telegram bot's private `/bind` command,
   the maintainer's `y wechat login` flow, or the caller's own `y wechat bind`.
   The panel does not mint tokens or start QR sessions.
4. Users confirm an unbind before it runs. Unbinding Telegram clears only the
   owner's DM binding; repeating it when unbound is harmless. WeChat unbind
   cancels the caller's live open or awaiting-code session and, when they have
   an active peer, revokes that peer and clears its contexts and queued
   messages. Other peers stay. The confirmation explains this loss. Repeating
   unbind when nothing is live is harmless. Rebinding uses the original flow.

## Host and module contract

The host CLI owns `y gateway channels status [--json]`, `bind <channel>` and
`unbind <channel> [--yes]`. Status and unbind call authenticated host routes
under `/api/gateway/channels`; bind prints guidance without changing state.
`y gateway send|config|status` remain notification commands.
The authenticated `gateway` module owns the panel, `GET /channels` and
`POST /channels/{channel}/unbind` under `/api/module/gateway`. Backend contract
v40 exposes `channel_list(user_id)` and `channel_unbind(user_id, channel)`.
Both require the dispatcher-bound request owner and return `{channels, notify}`.
The host owns credentials, authorization, state and mutations. WeChat
inventory and unbind are caller-scoped: an admitted user sees and removes only
their own peer and live binding session, never another user's. Unknown
channels are rejected without mutation. Availability and preference come from
the [notification gateway](notify-gateway.md). No new tables or migrations.
Deploy v40 before publishing Gateway; disable or roll back Gateway before
downgrading below v40.

## Verification and exclusions

Check health states, secret-free responses, empty and occupied bindings,
and that one user cannot see or unbind another user's peer, without sending
messages or unbinding live users. The deployed smoke check reads `y gateway
channels status --json`; live unbind and rebind are opt-in. The gateway does
not change [Telegram delivery](telegram-delivery.md), [WeChat login or
delivery](wechat-channel.md), notification settings, or IM history.
