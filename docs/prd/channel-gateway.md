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
2. The maintainer can distinguish pending confirmation, an active peer with a
   stale bridge, a healthy binding, and a revoked peer. Account and peer IDs,
   heartbeat and poll ages, last delivery error and outbox counts help diagnose
   failures without exposing message text or credentials. Other users see
   WeChat as unsupported, never the maintainer's account or peer.
3. Bind guidance directs users to the Telegram bot's private `/bind` command
   or the maintainer-only `y wechat login` flow. The panel does not mint tokens
   or start QR sessions.
4. Users confirm an unbind before it runs. Unbinding Telegram clears only the
   owner's DM binding; repeating it when unbound is harmless. WeChat unbind
   revokes the bridge and peer and clears contexts and queued messages.
   The confirmation explains this loss. Rebinding uses the original flow.

## Host and module contract

The host CLI owns `y gateway channels status [--json]`, `bind <channel>` and
`unbind <channel> [--yes]`. Status and unbind call authenticated host routes
under `/api/gateway/channels`; bind prints guidance without changing state.
`y gateway send|config|status` remain notification commands.
The authenticated `gateway` module owns the panel, `GET /channels` and
`POST /channels/{channel}/unbind` under `/api/module/gateway`. Backend contract
v40 exposes `channel_list(user_id)` and `channel_unbind(user_id, channel)`.
Both require the dispatcher-bound request owner and return `{channels, notify}`.
The host owns credentials, authorization, state and mutations. WeChat unbind
requires the configured maintainer; unknown channels are rejected without
mutation. Availability and preference come from the [notification
gateway](notify-gateway.md). No new tables or migrations. Deploy v40 before
publishing Gateway; disable or roll back Gateway before downgrading below v40.

## Verification and exclusions

Check health states, secret-free responses, empty and occupied bindings,
owner mismatch, and maintainer denial without sending messages or unbinding
live users. The deployed smoke check reads `y gateway channels status --json`; live
unbind and rebind are opt-in. The gateway does not change [Telegram
delivery](telegram-delivery.md), [WeChat login or delivery](wechat-channel.md),
notification settings, or IM history.
